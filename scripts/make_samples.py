"""Generate visibly synthetic demo PDFs and purchasing master data."""
from pathlib import Path
import json
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from PIL import Image, ImageDraw, ImageFilter
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'samples';OUT.mkdir(exist_ok=True)
vendors=[{'id':'acme','name':'Acme Furniture Private Limited','aliases':['Acme Furniture','Acme Furniture Pvt Ltd'],'gstin':'DEMO-ACME-001','status':'approved'}, {'id':'orbit','name':'Orbit Office Supplies','aliases':['Orbit Office'],'gstin':'DEMO-ORBIT-002','status':'approved'}, {'id':'nova','name':'Nova Equipment','aliases':[],'gstin':'DEMO-NOVA-003','status':'approved'}, {'id':'blocked','name':'Blocked Trading','aliases':[],'gstin':'DEMO-BLOCKED','status':'blocked'}]
def po(number,vendor,item,qty,price):
 return dict(number=number,vendor_id=vendor,status='open',currency='INR',date=date.today().isoformat(),tax_basis='exclusive',tax_rate=18,total=str(round(qty*price*1.18,2)),lines=[dict(id=number+'-1',item=item,aliases=[item.lower()],qty=qty,price=price,tax_basis='exclusive',tax_rate=18,unit='each')])
pos=[po('PO-1042','acme','Office chair',100,2000),po('PO-2001','orbit','Laptop stand',1000,1000),po('PO-3001','nova','Monitor',100,10000),po('PO-3002','nova','Monitor',80,10000)]
(OUT/'master.json').write_text(json.dumps({'vendors':vendors,'pos':pos},indent=2))
def invoice(filename,vendor,no,ref,item,qty,price,total_override=None,missing=False):
 subtotal=qty*price;tax=round(subtotal*.18,2);total=round(subtotal+tax,2)
 rows=[('Vendor',vendor['name']),('GSTIN',vendor['gstin']),('Invoice',no or 'MISSING'),('Date',date.today().isoformat()),('PO',ref or 'MISSING'),('Currency','INR'),('Tax basis','exclusive'),('Tax rate','18'),('Item',f'{item} | {qty} | {price:.2f} | {subtotal:.2f} | each'),('Subtotal',f'{subtotal:.2f}'),('Tax',f'{tax:.2f}'),('Total','UNCLEAR' if missing else f'{total_override if total_override is not None else total:.2f}')]
 c=canvas.Canvas(str(OUT/filename),pagesize=(595,842));c.setTitle('Synthetic invoice — '+(no or 'missing number'))
 c.setFillColor(HexColor('#113e37'));c.rect(0,720,595,122,fill=1,stroke=0);c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',26);c.drawString(40,780,'INVOICE');c.setFont('Helvetica',10);c.drawString(40,752,'SYNTHETIC TEST DOCUMENT - NOT PAYABLE')
 c.setFillColor(HexColor('#203d36'));y=677
 for label,val in rows:
  c.setFont('Helvetica',11);c.drawString(40,y,f'{label}: {val}');y-=30
 c.setFont('Helvetica',9);c.drawString(40,85,'All company details and identifiers are fictional demo data.');c.save()
invoice('01_happy_60_chairs.pdf',vendors[0],'INV-2051','PO-1042','Office chair',60,2000)
invoice('02_split_50_chairs.pdf',vendors[0],'INV-2087','PO-1042','Office chair',50,2000)
invoice('03_original_duplicate.pdf',vendors[1],'INV-0093','PO-2001','Laptop stand',200,1000)
invoice('04_near_duplicate.pdf',vendors[1],'INV-0093-R','PO-2001','Laptop stand',200,1000)
invoice('05_missing_information.pdf',vendors[0],None,'PO-1042','Office chair',10,2000,missing=True)
invoice('06_ambiguous_po.pdf',vendors[2],'NOVA-101',None,'Monitor',10,10000)
invoice('07_arithmetic_error.pdf',vendors[0],'INV-3000','PO-1042','Office chair',10,2000,total_override=99999)
invoice('08_unknown_vendor.pdf',dict(name='Unknown Vendor',gstin='DEMO-UNKNOWN'),'UNK-001','PO-1042','Office chair',10,2000)
# A real image-only PDF: the local parser must refuse this, rather than simulate OCR.
image=Image.new('RGB',(1190,1684),'#f7f6ef');d=ImageDraw.Draw(image)
from PIL import ImageFont
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)
for i,line in enumerate(['SYNTHETIC SCANNED INVOICE - NOT PAYABLE','Vendor: Acme Furniture Private Limited','GSTIN: DEMO-ACME-001','Invoice: MISSING','Date: '+date.today().isoformat(),'PO: PO-1042','Currency: INR','Tax basis: exclusive','Tax rate: 18','Item: Office chair | 10 | 2000.00 | 20000.00 | each','Subtotal: 20000.00','Tax: 3600.00','Total: [unreadable]']):d.text((60,100+90*i),line,font=font,fill='#253f38')
image=image.filter(ImageFilter.GaussianBlur(.6));image.save(OUT/'09_scan_requires_gemini.pdf','PDF',resolution=144)
