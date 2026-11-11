"""Gemini extraction with independent text/OCR fallback. Never uses answer keys.

Fallback values always require source confirmation. Missing fields stay null.
PDF text and OCR are processed page by page; totals come from labelled summaries,
not the largest number or procurement master data.
"""
import asyncio
import base64
import io
import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx
from PIL import Image, ImageOps
from pypdf import PdfReader
from app.domain import Invoice, Line
from app.extraction_schema import PROMPT, gemini_schema

MAX_PAGES = 30
MAX_SIZE = 10 * 1024 * 1024
# A per-process circuit breaker avoids a full timeout for every invoice in a batch.
# It is an optimization, never relied on for correctness across cloud instances.
_circuit_until = 0.0
_circuit_reason = ''

def inspect_file(raw):
    if not raw or len(raw) > MAX_SIZE:
        raise ValueError('Each invoice must be non-empty and at most 10 MB.')
    if raw.startswith(b'%PDF-'):
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError('This PDF is password protected. Upload an unlocked copy.')
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError(f'An invoice may contain 1–{MAX_PAGES} pages.')
        return 'application/pdf', len(reader.pages)
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {'PNG','JPEG','WEBP','TIFF','BMP'}:
                raise ValueError('Unsupported image format.')
            frames = getattr(im, 'n_frames', 1)
            if frames > MAX_PAGES or im.width * im.height > 30_000_000:
                raise ValueError('Image exceeds the page or 30-megapixel limit.')
            im.verify()
        return 'image/' + ('jpeg' if raw[:2] == b'\xff\xd8' else 'png'), frames
    except (ValueError, Image.DecompressionBombError):
        raise
    except Exception:
        raise ValueError('Upload a readable PDF, PNG, JPG, WebP, TIFF or BMP.') from None

def text_pages(raw):
    """OCR only pages with little embedded text. No network or model required."""
    import pytesseract
    pages = []
    if raw.startswith(b'%PDF-'):
        import pypdfium2 as pdfium
        native = PdfReader(io.BytesIO(raw))
        doc = None
        try:
            for index, page in enumerate(native.pages):
                text = page.extract_text(extraction_mode='layout') or ''
                method = 'PDF text'
                if len(text.strip()) < 60:
                    if doc is None:
                        doc = pdfium.PdfDocument(raw)
                    rendered = doc[index]
                    bitmap = rendered.render(scale=2.5)
                    im = bitmap.to_pil()
                    # Bound memory even for very large PDF page dimensions.
                    im.thumbnail((2600, 3400))
                    text = pytesseract.image_to_string(im, config='--psm 3', timeout=35)
                    method = 'Local OCR'
                    bitmap.close(); rendered.close()
                pages.append((index + 1, text, method))
        finally:
            if doc is not None:
                doc.close()
    else:
        with Image.open(io.BytesIO(raw)) as im:
            for index in range(getattr(im, 'n_frames', 1)):
                im.seek(index)
                frame = ImageOps.exif_transpose(im.copy()).convert('RGB')
                frame.thumbnail((2600, 3400))
                pages.append((index + 1, pytesseract.image_to_string(frame, config='--psm 3', timeout=35), 'Local OCR'))
    return pages

NUM = r'[-+]?(?:\d[\d,]*)(?:\.\d{1,2})?'

def amount(value):
    try:
        return str(Decimal(value.replace(',', '').strip()))
    except InvalidOperation:
        return None

def parse_pages(pages):
    data = {}; evidence = {}; lines = []; trace = []
    patterns = {
        'bank_beneficiary':r'^\s*(?:Beneficiary(?: name)?|Account holder)\s*:\s*([^\n|]+)',
        'bank_account':r'^\s*(?:Bank account(?: number| no\.?)?|Account(?: number| no\.?)?|A/c(?: no\.?)?)\s*:\s*([^\n|]+)',
        'bank_ifsc':r'\bIFSC(?: code)?\s*:\s*([A-Z0-9 ?*-]+)',
        'vendor': r'^\s*(?:Vendor|Supplier|Seller|From)\s*:\s*([^|\n]+)',
        'gstin': r'\bGSTIN\s*[:#-]?\s*([A-Z0-9]{15})\b',
        'vendor_reference': r'Vendor reference\s*:\s*([^|\n]+)',
        'invoice_no': r'\bInvoice\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_.-]*\d[A-Z0-9/_.-]*)',
        'po_ref': r'\b(?:Purchase\s+order|PO(?:\s*(?:number|no\.?))?)\s*[:#]?\s*(PO[-/][A-Z0-9/-]+)',
        'date': r'\b(?:Date|Issued|Invoice date)\s*:\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[ /-](?:[A-Za-z]+|\d{1,2})[ /-]\d{4})',
        'currency': r'\b(INR|USD|EUR|GBP|AED)\b',
        'subtotal': r'^\s*(?:Subtotal|Sub total|Taxable value|Net subtotal)\s*[:=]?\s*('+NUM+r')\s*$',
        'tax': r'^\s*(?:Tax|GST(?:\s+\d+(?:\.\d+)?\s*%)?|Total tax)\s*[:=]?\s*('+NUM+r')\s*$',
        'total': r'^\s*(?:Grand total|Total(?:\s+amount)?|Amount payable(?:\s*\([A-Z]{3}\))?|Balance due)\s*[:=]?\s*('+NUM+r')\s*$',
        'tax_rate': r'\b(?:Tax rate\s*:\s*|GST\s+)(\d+(?:\.\d+)?)\s*%?',
        'tax_basis': r'\b(?:Tax basis\s*:\s*)(exclusive|inclusive)\b',
    }
    conflicts = set()
    for page, text, method in pages:
        trace.append({'page':page, 'method':method, 'characters':len(text.strip())})
        # Supplier is often a standalone heading above a labelled GSTIN.
        for field, pattern in patterns.items():
            for match in re.finditer(pattern, text, re.I | re.M):
                value = match.group(1).strip()
                if value.upper() in {'MISSING','UNCLEAR','UNKNOWN'}:
                    continue
                if field in {'subtotal','tax','total','tax_rate'}:
                    value = amount(value)
                elif field in {'currency','gstin','po_ref'}:
                    value = value.upper()
                elif field == 'tax_basis':
                    value = value.lower()
                if value is None:
                    continue
                if field in data and data[field] != value:
                    conflicts.add(field)
                data[field] = value
                evidence[field] = {'page':page, 'snippet':match.group(0).strip()[:240], 'confidence':'requires source verification', 'method':method}
        if 'vendor' not in data:
            match = re.search(r'^\s*([^\n:|]{4,90}(?:Private Limited|Pvt\.? Ltd\.?|Office Supplies|Equipment))\s*$', text, re.M | re.I)
            if match:
                data['vendor'] = match.group(1).strip()
                evidence['vendor'] = {'page':page,'snippet':match.group(0).strip(),'confidence':'requires source verification','method':method}
        if 'date' not in data:
            match = re.search(r'\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b', text)
            if match:
                data['date'] = match.group(1)
                evidence['date'] = {'page':page,'snippet':match.group(0),'method':method,'confidence':'requires source verification'}
        if 'tax_basis' not in data:
            match = re.search(r'\b(?:prices?\s+exclud(?:e|es|ing)\s+(?:GST|tax)|prices?\s+includ(?:e|es|ing)\s+(?:GST|tax))', text, re.I)
            if match:
                data['tax_basis'] = 'exclusive' if 'exclud' in match.group(0).lower() else 'inclusive'
                evidence['tax_basis'] = {'page':page,'snippet':match.group(0),'method':method,'confidence':'requires source verification'}
        # Labelled rows, or a conventional Description | Qty | Unit | Rate | Net table.
        for line in text.splitlines():
            labelled = re.match(r'^\s*Item:\s*(.*?)\s*\|\s*('+NUM+r')\s*\|\s*('+NUM+r')\s*\|\s*('+NUM+r')\s*\|\s*(\w+)\s*$', line, re.I)
            tabular = re.match(r'^\s*(.+?)\s+('+NUM+r')\s+(each|pcs|units|kg|hours|hrs|box|boxes)\s+('+NUM+r')\s+('+NUM+r')\s*$', line, re.I)
            if labelled:
                item, qty, price, total, unit = labelled.groups()
            elif tabular:
                item, qty, unit, price, total = tabular.groups()
            else:
                continue
            lines.append(Line(item=item.strip(), qty=amount(qty), unit_price=amount(price), line_total=amount(total), unit=unit.lower()).model_dump(mode='json'))
            evidence['lines'] = {'page':page,'snippet':line.strip()[:240],'confidence':'requires source verification','method':method}
    # A conflicted label must be resolved by a person, never silently select one.
    for field in conflicts:
        data[field] = None
        evidence[field]['conflict'] = True
    if data.get('date'):
        raw = data['date']
        parsed = None
        for fmt in ['%Y-%m-%d','%d %b %Y','%d %B %Y','%d-%b-%Y','%d/%m/%Y','%d-%m-%Y']:
            try:
                parsed = datetime.strptime(raw, fmt).date().isoformat(); break
            except ValueError:
                continue
        data['date'] = parsed
    bank_fields=['bank_beneficiary','bank_account','bank_ifsc']
    if any(k in conflicts for k in bank_fields) or (data.get('bank_account') and not re.fullmatch(r'[0-9\s-]{6,100}',data['bank_account'])):
        data['bank_ambiguous']=True
    data['lines'] = lines
    data['evidence'] = evidence
    # Full fallback confirmation includes line items, unlike scalar-only verification.
    data['uncertain_fields'] = [k for k,v in data.items() if k not in {'evidence','lines'} and v is not None] + (['lines'] if lines else [])
    inv = Invoice.model_validate(data)
    return inv, trace

async def gemini(raw, mime):
    global _circuit_until, _circuit_reason
    if time.monotonic() < _circuit_until:
        raise ValueError(_circuit_reason)
    key = os.getenv('GEMINI_API_KEY','').strip()
    if not key:
        raise ValueError('Gemini key is not configured')
    model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    # TIFF/BMP are normalized to a PDF; retain the original file as evidence.
    if mime != 'application/pdf':
        with Image.open(io.BytesIO(raw)) as source:
            frames = []
            for index in range(getattr(source, 'n_frames', 1)):
                source.seek(index)
                frames.append(ImageOps.exif_transpose(source.copy()).convert('RGB'))
            buf = io.BytesIO(); frames[0].save(buf, format='PDF', save_all=True, append_images=frames[1:])
            raw = buf.getvalue(); mime = 'application/pdf'
    async with httpx.AsyncClient(timeout=45) as client:
        for attempt in range(2):
            try:
                response = await client.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                    headers={'x-goog-api-key':key},
                    json={'systemInstruction':{'parts':[{'text':PROMPT}]},
                          'contents':[{'role':'user','parts':[{'inlineData':{'mimeType':mime,'data':base64.b64encode(raw).decode()}},{'text':'Extract all pages. Preserve absent fields as null.'}]}],
                          'generationConfig':{'responseMimeType':'application/json','responseJsonSchema':gemini_schema(),'maxOutputTokens':16000}})
                if response.status_code in {429,500,502,503,504} and attempt == 0:
                    await asyncio.sleep(1); continue
                if response.status_code != 200:
                    raise ValueError(f'Gemini unavailable (HTTP {response.status_code})')
                body = response.json(); candidate = body.get('candidates',[{}])[0]
                if candidate.get('finishReason') != 'STOP':
                    raise ValueError('Gemini output was incomplete')
                text = ''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
                inv = Invoice.model_validate_json(text)
                for field in ['vendor','invoice_no','date','currency','total','lines','subtotal','tax','tax_rate','tax_basis','gstin','po_ref','bank_beneficiary','bank_account','bank_ifsc']:
                    if getattr(inv,field) is None or getattr(inv,field) == []:
                        continue
                    ev = inv.evidence.get(field, {})
                    if not ev.get('snippet') or not ev.get('page') or ev.get('confidence') != 'high':
                        inv.uncertain_fields.append(field)
                inv.uncertain_fields = list(dict.fromkeys(inv.uncertain_fields))
                return inv
            except httpx.RequestError:
                if attempt == 0:
                    continue
                _circuit_reason = 'Gemini connection timed out or was unavailable'
            except Exception as exc:
                # Never expose provider bodies, credentials or an unvalidated response.
                _circuit_reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('Gemini ') else 'Gemini returned invalid invoice data'
            _circuit_until = time.monotonic() + 60
            raise ValueError(_circuit_reason)

async def read(raw, mime, local_only=False):
    reason = None
    if not local_only:
        try:
            inv = await gemini(raw, mime)
            return inv, {'source':'Gemini','fallback':False,'note':'Extracted with Gemini. Policy checks run separately.','pages':[]}
        except Exception as exc:
            reason = str(exc)
    try:
        pages = await asyncio.to_thread(text_pages, raw)
        inv, trace = parse_pages(pages)
        return inv, {'source':'Local OCR + rules' if any(p[2]=='Local OCR' for p in pages) else 'PDF text + rules',
                     'fallback':True, 'note':(reason + '. ' if reason else '') + 'Fallback extraction requires source confirmation. Missing fields remain empty.', 'pages':trace}
    except Exception:
        # A damaged/unreadable page must still reach the manual review queue.
        return Invoice(), {'source':'Manual review','fallback':True,'note':(reason+'. ' if reason else '')+'Text/OCR could not read this document. Enter the fields from the original and rerun checks.','pages':[]}
