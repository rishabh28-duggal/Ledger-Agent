"""Real Excel downloads, scoped to folders selected from the authenticated owner."""
import io
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


def invoice_status(row):
    if row.get('accepted'):
        return 'Approved'
    if row['execution'] == 'completed':
        return (row.get('result') or {}).get('status', 'Needs review')
    return {'queued':'Queued','running':'Processing','failed':'Interrupted'}.get(row['execution'], row['execution'])


def filtered_rows(rows, outcome='', dated='all', search='', as_of=None):
    today = as_of or date.today()
    start = None
    if dated in {'7','30','90'}:
        start = today - timedelta(days=int(dated)-1)
    elif dated == 'month':
        start = today.replace(day=1)
    elif dated == 'year':
        start = today.replace(month=1,day=1)
    query = search.lower()
    result = []
    for row in rows:
        data = row.get('data') or {}
        state = invoice_status(row)
        if outcome == 'Held':
            if state not in {'Needs review','Blocked','Interrupted'}:
                continue
        elif outcome and state != outcome:
            continue
        if start:
            try:
                issued = date.fromisoformat(str(data.get('date') or ''))
            except ValueError:
                continue
            if not start <= issued <= today:
                continue
        if query and query not in ' '.join(str(x or '') for x in
                [row.get('filename'),data.get('invoice_no'),data.get('vendor'),row.get('po')]).lower():
            continue
        result.append(row)
    return result


def group_key(row, group):
    data = row.get('data') or {}
    issued = str(data.get('date') or '')
    if group in {'date','month','year'}:
        return issued[:{'date':10,'month':7,'year':4}[group]] or 'No invoice date'
    return str({'vendor':data.get('vendor'), 'invoice_no':data.get('invoice_no'),
                'po':row.get('po'), 'status':invoice_status(row), 'folder':row.get('folder_name')}.get(group) or 'Not available')


def workbook(rows, group='none'):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Invoices'
    headers = ['Folder','File','Invoice number','Vendor','Invoice date','Currency','Amount','Outcome','Purchase order','Reader','Updated','Receipt findings','Bank findings','Invoice account (masked)']
    if group != 'none':
        headers.insert(0, 'Group')
        rows = sorted(rows, key=lambda row:group_key(row, group))
    sheet.append(headers)
    for row_index, row in enumerate(rows, 2):
        data = row.get('data') or {}
        try:
            amount = Decimal(str(data['total'])) if data.get('total') not in (None,'') else None
            if amount is not None and not amount.is_finite():
                amount = None
        except (InvalidOperation, ValueError):
            amount = None
        values = [row.get('folder_name'),row.get('filename'),data.get('invoice_no'),data.get('vendor'),
                  data.get('date'),data.get('currency'),amount,invoice_status(row),row.get('po'),
                  (row.get('extraction') or {}).get('source'),row.get('updated'),
                  ' '.join(c['message'] for c in (row.get('result') or {}).get('checks',[]) if c['code'].startswith('receipt')),
                  ' '.join(c['message'] for c in (row.get('result') or {}).get('checks',[]) if c['code'].startswith('bank')),
                  data.get('bank_account') or 'Not provided']
        if group != 'none':
            values.insert(0, group_key(row, group))
        # Store all supplied strings as literal text, including '=...', not Excel formulae.
        for col, value in enumerate(values,1):
            if isinstance(value,str):
                value = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', value)
            cell = sheet.cell(row=row_index,column=col,value=value)
            if isinstance(value,str):
                cell.data_type = 's'
            if isinstance(value,Decimal):
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal='right')
    for cell in sheet[1]:
        cell.font = Font(bold=True,color='FFFFFF')
        cell.fill = PatternFill('solid',fgColor='172B4D')
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for col in range(1,len(headers)+1):
        sheet.column_dimensions[get_column_letter(col)].width = 22 if col != 2 else 40
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
