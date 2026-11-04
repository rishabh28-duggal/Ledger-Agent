"""Reproducible invoice fixtures with independent extraction ground truth."""
from pathlib import Path
import json,io
from decimal import Decimal
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor,Color
from PIL import Image,ImageFilter,ImageEnhance
import pypdfium2 as pdfium
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test_pack';PDFS=OUT/'invoices';PDFS.mkdir(parents=True,exist_ok=True)
DATE=date(2026,11,4)
INK='#203d39';GREY='#66756e';LIGHT='#eef3ef'

def text(c,x,y,value,size=10,bold=False,color=INK):
 c.setFillColor(HexColor(color));c.setFont('Helvetica-Bold' if bold else 'Helvetica',size);c.drawString(x,y,str(value))
def right(c,x,y,value,size=10,bold=False):
 c.setFillColor(HexColor(INK));c.setFont('Helvetica-Bold' if bold else 'Helvetica',size);c.drawRightString(x,y,str(value))
def footer(c,page=1,pages=1):
 c.setStrokeColor(HexColor('#dce4df'));c.line(42,67,553,67)
 text(c,42,51,'SYNTHETIC EVALUATION FIXTURE - NOT A PAYABLE DOCUMENT',7,color=GREY)
 right(c,553,51,f'{page} / {pages}',8)
 text(c,42,38,'Synthetic GSTIN format fixtures only; no registration or legal validity claimed.',7,color=GREY)
def amount(n):return f'{Decimal(str(n)):,.2f}'
def identity(c,name,gstin):
 text(c,42,690,name,15,True);text(c,42,670,'Registered office: 18 Example Business Park, Hyderabad 500000',8,color=GREY)
 text(c,42,654,'GSTIN: '+gstin,9)
 text(c,42,639,'Vendor reference: DEMO-ACME-001',8,color=GREY)
def parties(c,y=585):
 text(c,42,y,'BILL TO',8,True,color=GREY);text(c,42,y-20,'Ledger Demo Company',11,True)
 text(c,42,y-37,'Procurement Department, Example Campus',9)
 text(c,345,y,'SHIP TO',8,True,color=GREY);text(c,345,y-20,'Facilities - Main Office',10,True)
 text(c,345,y-37,'Hyderabad, India (fictional)',9)
def grid(c,rows,y=476):
 c.setFillColor(HexColor(LIGHT));c.rect(42,y,511,29,fill=1,stroke=0)
 for x,label in [(52,'Description'),(302,'Qty'),(345,'Unit'),(398,'Rate (INR)'),(482,'Net (INR)')]:text(c,x,y+10,label,8,True)
 y-=31
 for item,qty,rate in rows:
  text(c,52,y,item,10);right(c,324,y,qty);text(c,345,y,'each',9);right(c,461,y,amount(rate),9);right(c,543,y,amount(qty*rate),9)
  c.setStrokeColor(HexColor('#e5ebe7'));c.line(42,y-15,553,y-15);y-=43
 return y

def totals(c,subtotal,y=310,missing=False):
 tax=Decimal(str(subtotal))*Decimal('.18');total=Decimal(str(subtotal))+tax
 for label,value,bold in [('Taxable value',amount(subtotal),False),('GST 18%',amount(tax),False),('Amount payable (INR)','Not supplied' if missing else amount(total),True)]:
  text(c,316,y,label,9,bold);right(c,543,y,value,11 if bold else 10,bold);y-=27
 text(c,42,y-4,'All unit prices exclude GST; no freight, discounts or other adjustments.',8,color=GREY)
 return total

def modern(path,no,qty,missing=False):
 c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('Acme - '+(no or 'incomplete invoice'))
 c.setFillColor(HexColor('#205c49'));c.rect(0,738,595,104,fill=1,stroke=0)
 text(c,42,783,'ACME / FURNITURE',23,True,'#ffffff');text(c,42,758,'TAX INVOICE',10,False,'#d7e8dc')
 identity(c,'Acme Furniture Private Limited','36ZZZCA0001A1Z8')
 text(c,42,618,'Invoice no.: '+(no or 'Not supplied'),10,True);text(c,345,618,'Issued: 04 Nov 2026',10)
 parties(c,575);text(c,42,510,'Purchase order: PO-1042',10,True);text(c,345,510,'Currency: INR | Terms: Net 30',9)
 grid(c,[('Office chair',qty,2000)],455);totals(c,qty*2000,335,missing)
 text(c,42,152,'Payment instructions',9,True);text(c,42,135,'Demo settlement details omitted. Do not make a payment against this fixture.',8,color=GREY)
 footer(c);c.save()

def duplicate(path):
 c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('Acme reissued invoice')
 text(c,42,777,'INVOICE COPY',27,True,color='#524233');text(c,42,750,'Acme Furniture Pvt Ltd',17,True)
 text(c,42,729,'GSTIN: 36ZZZCA0001A1Z8 | Vendor reference: DEMO-ACME-001',9)
 c.setStrokeColor(HexColor('#b9a38a'));c.line(42,711,553,711)
 text(c,42,680,'Document ID',8,color=GREY);text(c,42,660,'RT-ACME-6001',13,True)
 text(c,280,680,'Invoice date',8,color=GREY);text(c,280,660,'2026-11-04',11)
 text(c,430,680,'Order ref.',8,color=GREY);text(c,430,660,'PO-1042',11)
 parties(c,605);grid(c,[('Office chair',60,2000)],480);totals(c,120000,350)
 text(c,42,180,'Reissued copy: same invoice identity and amount as the original.',9)
 text(c,42,162,'Currency INR. Prices exclude GST. This copy does not create a new charge.',8)
 footer(c);c.save()

def multi(path):
 c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('Orbit - two-page invoice')
 for page,qty in [(1,80),(2,120)]:
  c.setFillColor(HexColor('#21395b'));c.rect(42,735,511,67,fill=1,stroke=0)
  text(c,58,774,'ORBIT',25,True,'#ffffff');text(c,58,752,'OFFICE SUPPLIES',9,False,'#d4e0ef')
  text(c,345,774,'INVOICE RT-ORBIT-2201',12,True,'#ffffff');text(c,345,752,'04 November 2026 | INR',9,False,'#ffffff')
  text(c,42,706,'Supplier: Orbit Office Supplies | GSTIN: 36ZZZCO0002B1Z8',9)
  text(c,42,686,'Vendor reference: DEMO-ORBIT-002 | Customer: Ledger Demo Company | PO-2001',9)
  text(c,42,666,'Unit prices exclude GST. Unit of measure: each.',9)
  text(c,42,610,'Shipment '+('A - first batch' if page==1 else 'B - second batch'),12,True)
  grid(c,[('Laptop stand',qty,1000)],530)
  if page==1:
   text(c,316,411,'Page 1 net subtotal',10);right(c,543,411,'80,000.00',11,True)
   text(c,42,355,'Continued on page 2. This page subtotal is not the invoice total.',10)
   text(c,42,333,'The final GST and amount payable appear only on the last page.',9,color=GREY)
  else:
   text(c,316,411,'Net brought forward',10);right(c,543,411,'80,000.00',10)
   text(c,316,385,'Current page net',10);right(c,543,385,'120,000.00',10)
   totals(c,200000,330)
   text(c,42,155,'Final invoice summary covers both shipments, 200 units in total.',9)
  footer(c,page,2);c.showPage()
 c.save()

def ambiguous(path):
 c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('Nova equipment invoice without PO')
 text(c,42,774,'nova',38,True,color='#4b437a');text(c,42,747,'Nova Equipment',14,True)
 text(c,365,774,'INVOICE',17,True);text(c,365,752,'RT-NOVA-3301',11)
 text(c,42,713,'GSTIN: 36ZZZCN0003C1Z8 | Vendor reference: DEMO-NOVA-003',9)
 text(c,42,693,'Issued 04/11/2026',9)
 parties(c,652)
 text(c,42,560,'Customer reference: Facilities team',9);text(c,345,560,'Billing currency: INR',9)
 grid(c,[('Monitor',10,10000)],478);totals(c,100000,340)
 text(c,42,190,'Buyer purchase-order reference has not been supplied.',9)
 text(c,42,171,'Please quote invoice number RT-NOVA-3301 in any correspondence.',9)
 footer(c);c.save()

modern(PDFS/'R01_acme_modern_happy.pdf','RT-ACME-6001',60)
modern(PDFS/'R02_acme_partial_overrun.pdf','RT-ACME-6050',50)
duplicate(PDFS/'R03_acme_reissued_duplicate.pdf')
multi(PDFS/'R04_orbit_two_page_invoice.pdf')
ambiguous(PDFS/'R05_nova_missing_po.pdf')
modern(PDFS/'R06_acme_incomplete_invoice.pdf',None,10,True)
# Create a genuine image-only PDF with a small rotation and scanner texture.
buffer=PDFS/'_scan_source.pdf';modern(buffer,'RT-ACME-SCAN10',10)
doc=pdfium.PdfDocument(str(buffer));page=doc[0];bitmap=page.render(scale=2)
im=bitmap.to_pil().convert('RGB');im=im.rotate(.6,resample=Image.Resampling.BICUBIC,expand=False,fillcolor='white')
im=ImageEnhance.Contrast(im).enhance(.85).filter(ImageFilter.GaussianBlur(.35))
im.save(PDFS/'R07_acme_scanned_invoice.pdf','PDF',resolution=144)
im.close();bitmap.close();page.close();doc.close();buffer.unlink()

def payload(v,no,po,lines,total_missing=False):
 subtotal=sum(q*p for _,q,p in lines);tax=Decimal(subtotal)*Decimal('.18')
 return {'vendor':v,'invoice_no':no,'date':DATE.isoformat(),'po_ref':po,'currency':'INR','tax_basis':'exclusive','tax_rate':18,'subtotal':subtotal,'tax':float(tax),'total':None if total_missing else float(subtotal+tax),'lines':[{'item':item,'qty':qty,'unit_price':price,'line_total':qty*price,'unit':'each'} for item,qty,price in lines]}
entries=[]
def add(file,expected,status,setup,notes):
 entries.append({'file':'invoices/'+file,'expected_extraction':expected,'expected_recommendation':status,'required_setup':setup,'notes':notes})
add('R01_acme_modern_happy.pdf',payload('Acme Furniture Private Limited','RT-ACME-6001','PO-1042',[('Office chair',60,2000)]),'Ready for approval','Fresh workspace; no invoices accepted.','After explicit approval: 60 chairs consumed; INR 94400 remaining.')
add('R02_acme_partial_overrun.pdf',payload('Acme Furniture Private Limited','RT-ACME-6050','PO-1042',[('Office chair',50,2000)]),'Needs review','R01 must already be Accepted against PO-1042.','Bills 50, only 40 remain. Amount INR 118000 exceeds remaining INR 94400. Alone in a fresh workspace it legitimately passes.')
add('R03_acme_reissued_duplicate.pdf',payload('Acme Furniture Pvt Ltd','RT-ACME-6001','PO-1042',[('Office chair',60,2000)]),'Blocked','R01 already exists with extracted vendor and invoice identity.','Different file/layout, same vendor plus normalised invoice number and amount. Not a hash-only duplicate.')
add('R04_orbit_two_page_invoice.pdf',payload('Orbit Office Supplies','RT-ORBIT-2201','PO-2001',[('Laptop stand',80,1000),('Laptop stand',120,1000)]),'Ready for approval','Fresh workspace or no similar Orbit invoice already processed.','Extract two lines across both pages. Net brought forward is NOT a third line. Aggregating to one 200-unit line is also semantically acceptable; evaluate total quantity/value rather than exact row count.')
add('R05_nova_missing_po.pdf',payload('Nova Equipment','RT-NOVA-3301',None,[('Monitor',10,10000)]),'Needs review','Fresh workspace with default PO-3001 and PO-3002 both open.','Missing PO must remain null. Show both candidates. After reviewer selects a valid PO, expect Ready for approval.')
add('R06_acme_incomplete_invoice.pdf',payload('Acme Furniture Private Limited',None,'PO-1042',[('Office chair',10,2000)],True),'Needs review','Run independently or after R01; enough remaining quantity either way.','Invoice number and amount payable are explicitly not supplied. Total stays null, even though subtotal plus tax could be computed. Do not fabricate fields.')
add('R07_acme_scanned_invoice.pdf',payload('Acme Furniture Private Limited','RT-ACME-SCAN10','PO-1042',[('Office chair',10,2000)]),'Ready for approval','Fresh workspace, independent of R06 and other similar Acme 10-chair invoices.','Genuine image-only PDF. Requires Groq/Gemini; local text reader must fail clearly. Low-confidence or missing evidence may correctly route it to review rather than Ready.')
for e in entries:
 reader=PdfReader(str(OUT/e['file']));e['pages']=len(reader.pages)
 if e['file'].endswith('R07_acme_scanned_invoice.pdf'):assert not ''.join(p.extract_text() for p in reader.pages).strip()
 expected=e['expected_extraction'];expected['gstin']={'Acme Furniture Private Limited':'36ZZZCA0001A1Z8','Acme Furniture Pvt Ltd':'36ZZZCA0001A1Z8','Orbit Office Supplies':'36ZZZCO0002B1Z8','Nova Equipment':'36ZZZCN0003C1Z8'}[expected['vendor']]
 expected['vendor_reference']={'36ZZZCA0001A1Z8':'DEMO-ACME-001','36ZZZCO0002B1Z8':'DEMO-ORBIT-002','36ZZZCN0003C1Z8':'DEMO-NOVA-003'}[expected['gstin']]
 assert Decimal(str(expected['subtotal']))+Decimal(str(expected['tax']))==Decimal(str(expected['total'])) if expected['total'] is not None else True
(OUT/'answer_key.json').write_text(json.dumps({'fixture_date':DATE.isoformat(),'synthetic':True,'uses_existing_master':'samples/master.json','evaluation_notes':'Recommendations assume correct, evidence-backed extraction and the stated workspace setup. Evidence/uncertainty may conservatively require review. Never put this answer key into the model prompt.','cases':entries},indent=2))
print('Created',len(entries),'PDF fixtures; total pages',sum(e['pages'] for e in entries))
