"""Bounded, deterministic vendor spreadsheet parsing and additive import planning."""
import copy
import csv
import hashlib
import io
import json
import re
import uuid
import zipfile

from openpyxl import Workbook, load_workbook
from app.domain import name_norm, norm

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
HEADERS = ['Vendor name', 'GSTIN', 'Status', 'Aliases']


class ImportInvalid(ValueError):
    pass


def fingerprint(meta):
    return hashlib.sha256(json.dumps(meta['master'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def parse(raw, filename, sheet=''):
    if len(raw) > MAX_BYTES:
        raise ImportInvalid('Choose a file up to 2 MB.')
    extension = filename.lower().rsplit('.', 1)[-1]
    sheets = []
    if extension == 'csv':
        try:
            text = raw.decode('utf-8-sig')
            rows = []
            for row in csv.reader(io.StringIO(text), strict=True):
                if len(row) > 20 or len(rows) > MAX_ROWS:
                    raise ImportInvalid('Use at most 500 data rows and 20 columns.')
                rows.append([(v, False) for v in row])
        except (UnicodeError, csv.Error) as exc:
            raise ImportInvalid('Use a valid UTF-8 CSV file.') from exc
    elif extension == 'xlsx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(x.file_size for x in archive.infolist()) > 10 * 1024 * 1024 or len(archive.infolist()) > 200:
                    raise ImportInvalid('Workbook expands beyond the safe import limit.')
                if any('vbaproject' in x.filename.lower() for x in archive.infolist()):
                    raise ImportInvalid('Macro-enabled workbooks are not supported.')
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                sheets = []
                for ws in book:
                    # Inspect bounded rows even when workbook dimensions are missing or forged.
                    if any(any(c.value is not None for c in row) for row in ws.iter_rows(max_row=MAX_ROWS+2, max_col=21)):
                        sheets.append(ws.title)
                preferred = next((n for n in sheets if n.casefold() == 'vendors'), '')
                selected = sheet or preferred or (sheets[0] if len(sheets) == 1 else '')
                if not selected:
                    if not sheets:
                        raise ImportInvalid('The workbook contains no nonempty worksheets.')
                    return {'sheets': sheets, 'choose_sheet': True}
                if selected not in sheets:
                    raise ImportInvalid('Choose a nonempty worksheet from this workbook.')
                ws = book[selected]
                if ws.max_row and ws.max_row > MAX_ROWS+1 or ws.max_column and ws.max_column > 20:
                    raise ImportInvalid('Use at most 500 data rows and 20 columns.')
                rows = [[(str(c.value) if c.value is not None else '', c.data_type == 'f') for c in row]
                        for row in ws.iter_rows(max_row=MAX_ROWS+2, max_col=21)]
                while rows and not any(v for v, _ in rows[-1]):
                    rows.pop()
                if len(rows) > MAX_ROWS+1 or any(row[20][0] for row in rows):
                    raise ImportInvalid('Use at most 500 data rows and 20 columns.')
            finally:
                book.close()
        except ImportInvalid:
            raise
        except Exception as exc:
            raise ImportInvalid('This XLSX file could not be read. Save a fresh .xlsx or UTF-8 CSV file.') from exc
    else:
        raise ImportInvalid('Supported formats: .xlsx and .csv. Legacy .xls is not supported.')
    if not rows:
        raise ImportInvalid('The file is empty.')
    columns = {}
    variants = {'vendorname': 'name', 'name': 'name', 'gstin': 'gstin', 'status': 'status', 'aliases': 'aliases'}
    for i, (value, formula) in enumerate(rows[0]):
        key = variants.get(re.sub('[^a-z]', '', value.strip().lower()))
        if key:
            if key in columns or formula:
                raise ImportInvalid('Ambiguous or formula-based column headers. Use each template column once.')
            columns[key] = i
    if 'name' not in columns:
        raise ImportInvalid('Missing required Vendor name column.')
    output = []
    for number, row in enumerate(rows[1:], 2):
        if not any(v.strip() for v, _ in row):
            continue
        values, errors = {}, []
        for key in ['name', 'gstin', 'status', 'aliases']:
            index = columns.get(key)
            value, formula = row[index] if index is not None and index < len(row) else ('', False)
            value = value.strip()
            if len(value) > 5000:
                raise ImportInvalid('Import fields must be at most 5,000 characters.')
            if formula or value.startswith(('=', '+', '-', '@')):
                errors.append(f'{key.title()}: formulas are not allowed.')
            values[key] = value
        values['gstin'] = values['gstin'].upper()
        defaulted = not values['status']
        state = values['status'].casefold() or 'active'
        if state not in {'active', 'blocked'}:
            errors.append('Status must be Active or Blocked.')
        values['status'] = 'blocked' if state == 'blocked' else 'approved'
        if not values['name'] or len(values['name']) > 150 or not name_norm(values['name']):
            errors.append('Vendor name is required and must be at most 150 characters.')
        if values['gstin'] and not re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]', values['gstin']):
            errors.append('GSTIN has an invalid format (format check only).')
        aliases = list(dict.fromkeys(v.strip() for v in values['aliases'].split(';') if v.strip()))
        if len(aliases) > 30 or any(len(v) > 150 for v in aliases):
            errors.append('Use up to 30 aliases, each at most 150 characters.')
        values['aliases'] = aliases
        output.append(dict(row=number, values=values, errors=errors, defaulted=defaulted))
    if not output:
        raise ImportInvalid('No vendor data rows were found.')
    return {'rows': output, 'sheets': sheets, 'sheet': sheet if extension == 'csv' else selected}


def plan(source, master, update=False, locked=False):
    result = copy.deepcopy(source)
    # Exact normalized identities only; never use fuzzy similarity to merge.
    identities = []
    for item in result:
        v = item['values']
        identities.append((norm(v['gstin']), {name_norm(n) for n in [v['name'], *v['aliases']] if name_norm(n)}))
    capacity = 100 - len(master['vendors'])
    targeted = {}
    for i, item in enumerate(result):
        v = item['values']; gst, names = identities[i]
        item.update(action='Invalid' if item['errors'] else 'New', changes=None)
        if item['errors']:
            continue
        if any((gst and gst == other_gst) or names & other_names for j, (other_gst, other_names) in enumerate(identities) if i != j):
            item.update(action='Conflict', errors=['Duplicate or conflicting identity within this file.'])
            continue
        candidates = []
        for old in master['vendors']:
            old_names = {name_norm(n) for n in [old['name'], *old['aliases']]}
            if (gst and norm(old['gstin']) == gst) or names & old_names:
                candidates.append(old)
        if len(candidates) > 1:
            item.update(action='Conflict', errors=['Multiple existing vendors match. Resolve the identity before importing.'])
            continue
        if candidates:
            old = candidates[0]
            if gst and old['gstin'] and gst != norm(old['gstin']):
                item.update(action='Conflict', errors=['The name matches, but the GSTIN conflicts with the stored vendor.'])
                continue
            proposed = copy.deepcopy(old)
            aliases = list(old['aliases'])
            # Retain the old recognized name when a GSTIN match renames a vendor.
            preserved_names = [old['name']] if name_norm(old['name']) != name_norm(v['name']) else []
            for alias in [*preserved_names, *v['aliases']]:
                if name_norm(alias) not in {name_norm(a) for a in aliases}:
                    aliases.append(alias)
            proposed.update(name=v['name'], gstin=v['gstin'] or old['gstin'], aliases=aliases,
                            status='blocked' if old['status'] == 'blocked' else v['status'])
            if len(aliases) > 30:
                item.update(action='Conflict', errors=['Merged aliases exceed the 30-alias limit.'])
                continue
            item.update(action='Update' if update and proposed != old else 'Existing', vendor_id=old['id'], changes={'before':old, 'after':proposed})
            targeted.setdefault(old['id'], []).append(item)
            if old['status'] == 'blocked' and v['status'] == 'approved':
                item['note'] = 'Stored Blocked status retained; spreadsheet imports cannot reactivate vendors.'
        elif capacity <= 0:
            item.update(action='Invalid', errors=['This folder supports at most 100 vendors.'])
        else:
            capacity -= 1
            item['changes'] = {'before':None, 'after':dict(id='vendor-'+uuid.uuid4().hex, **v)}
        if locked:
            item.update(action='Conflict', errors=['Procurement is locked because this folder contains approved invoices. Start a new folder.'])
    for matches in targeted.values():
        if len(matches) > 1:
            for item in matches:
                item.update(action='Conflict', errors=['Multiple rows target the same existing vendor.'])
    return result


def counts(rows):
    return {'new':sum(r['action']=='New' for r in rows), 'existing':sum(r['action'] in {'Existing','Update'} for r in rows),
            'conflicts':sum(r['action']=='Conflict' for r in rows), 'invalid':sum(r['action']=='Invalid' for r in rows),
            'eligible':sum(r['action'] in {'New','Update'} for r in rows)}


def template_bytes():
    book = Workbook(); ws = book.active; ws.title = 'Vendors'
    ws.append(HEADERS)
    ws.append(['Fictional Example Vendor - REMOVE BEFORE IMPORT', '', 'Active', 'Example alias'])
    ws.freeze_panes = 'A2'
    for key, width in [('A',58),('B',22),('C',16),('D',32)]:
        ws.column_dimensions[key].width = width
    notes = book.create_sheet('Instructions')
    notes.append(['Remove the fictional example row before importing your vendors.'])
    notes.append(['GSTIN is optional. Format checks do not verify government registration or vendor legitimacy.'])
    notes.append(['Status: Active or Blocked. Separate aliases with semicolons.'])
    result = io.BytesIO(); book.save(result); return result.getvalue()
