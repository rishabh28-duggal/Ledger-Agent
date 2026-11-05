"""Plain-language next steps for deterministic review findings."""
def fix_for(check):
    code=check['code'];level=check['level']
    if level=='pass':return 'No action needed.'
    if code=='uncertain_lines':return 'Compare every line, quantity, unit, price and amount with the original. Correct the values and confirm the source.'
    if code.startswith('uncertain_'):return 'Compare the field with the source PDF; verify it if correct, or correct it and rerun.'
    if code.startswith('missing_'):return 'Ask the vendor to supply the missing '+code[8:].replace('_',' ')+'.'
    if code.startswith('duplicate'):return 'Open the original invoice. Do not approve another copy; ask whether this replaces an existing obligation.'
    if code=='possible_duplicate':return 'Compare the linked prior invoice and ask the vendor whether this is a reissue.'
    if code.startswith('quantity') or code=='balance':return 'Request a corrected invoice within the remaining PO commitment, or obtain an authorised PO amendment.'
    if code.startswith('po'):return 'Select or correct the PO reference, then rerun vendor ownership and balance checks.'
    if code=='gstin':return 'Compare the printed GSTIN with the master; correct an extraction error or investigate the mismatch.'
    if code.startswith('vendor'):return 'Ask procurement to confirm vendor identity and approved status.'
    if code.startswith('price'):return 'Confirm the agreed unit price and tax basis; request correction or an authorised PO amendment.'
    if code in ['total','subtotal','tax_math'] or code.startswith('line_math'):return 'Check the printed amounts and tax-rate format; correct extraction errors or request a corrected invoice.'
    if code=='date':return 'Verify the invoice date and request clarification if it is outside policy.'
    if code.startswith('mapping') or code.startswith('unit'):return 'Confirm item identity and compatible units against the PO; resolve ambiguity before approval.'
    return 'Resolve the stated prerequisite against the source document and rerun checks.'

