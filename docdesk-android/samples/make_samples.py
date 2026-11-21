#!/usr/bin/env python3
"""Creates test documents for DocDesk in ./out.

Requirements:  pip install reportlab pypdf pillow openpyxl python-docx
Run:           python3 make_samples.py

All data is fictitious. See docs/TESTING.md for what each file is meant to test.
"""
import io
import os
import random
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
random.seed(42)


def indian(v: Decimal) -> str:
    """12,34,567.89"""
    neg = v < 0
    s = f"{abs(v):.2f}"
    i, f = s.split(".")
    if len(i) > 3:
        head, tail = i[:-3], i[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        i = ",".join(parts + [tail])
    return ("-" if neg else "") + i + "." + f


def transactions(n=55):
    narrs = [
        "UPI/ramesh traders/payment for invoice 1043 and freight charges",
        "NEFT/SALARY CREDIT/ACME PVT LTD", "ATM CASH WITHDRAWAL MG ROAD", "IMPS/rent for April/landlord",
        "GST PAYMENT CHALLAN 2024-25 Q1 through net banking", "POS/BIG BAZAAR", "INTEREST CREDIT",
        "CHQ DEP/CLEARING", "ECS/LIC PREMIUM", "UPI/electricity bill/BESCOM consumer 9930012",
    ]
    bal = Decimal("50000.00")
    rows = []
    for k in range(n):
        d = f"{(k % 28) + 1:02d}/{4 + k // 28:02d}/2024"
        narr = random.choice(narrs)
        ref = random.choice(["", f"{random.randint(0, 999999):06d}", f"N{random.randint(100000, 999999)}", f"000{random.randint(10000000, 99999999)}"])
        if random.random() < 0.35:
            amt = Decimal(random.randint(5000, 250000)) + Decimal(random.randint(0, 99)) / 100
            bal += amt
            rows.append((d, narr, ref, "", indian(amt), indian(bal)))
        else:
            amt = Decimal(random.randint(100, 30000)) + Decimal(random.randint(0, 99)) / 100
            bal -= amt
            rows.append((d, narr, ref, indian(amt), "", indian(bal)))
    return rows


def wrap(text, width_chars):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def bank_statement_pdf(path, rows):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    cols = [15 * mm, 38 * mm, 98 * mm, 128 * mm, 152 * mm, 178 * mm]  # x of Date, Narration, Ref, Withdrawal(right), Deposit(right), Balance(right)
    pages = [rows[i:i + 22] for i in range(0, len(rows), 22)]
    total_dr = sum(Decimal(r[3].replace(",", "")) for r in rows if r[3])
    total_cr = sum(Decimal(r[4].replace(",", "")) for r in rows if r[4])
    for pn, page in enumerate(pages):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(15 * mm, h - 18 * mm, "SAMPLE BANK LTD - Statement of Account")
        c.setFont("Helvetica", 8.5)
        c.drawString(15 * mm, h - 24 * mm, "Account: 001234567890   IFSC: SMPL0000123   Period: 01/04/2024 to 30/05/2024")
        if pn == 0:
            c.drawString(15 * mm, h - 30 * mm, "Opening Balance 50,000.00")
        y = h - 40 * mm
        c.setFont("Helvetica-Bold", 8.5)
        for x, t, right in zip(cols, ["Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"], [0, 0, 0, 1, 1, 1]):
            (c.drawRightString if right else c.drawString)(x + (20 * mm if right else 0), y, t)
        c.line(15 * mm, y - 2, w - 15 * mm, y - 2)
        y -= 5 * mm
        c.setFont("Helvetica", 8.5)
        for d, narr, ref, dr, cr, bal in page:
            lines = wrap(narr, 32)
            c.drawString(cols[0], y, d)
            c.drawString(cols[1], y, lines[0])
            c.drawString(cols[2], y, ref)
            if dr: c.drawRightString(cols[3] + 20 * mm, y, dr)
            if cr: c.drawRightString(cols[4] + 20 * mm, y, cr)
            c.drawRightString(cols[5] + 20 * mm, y, bal)
            for extra in lines[1:]:
                y -= 3.6 * mm
                c.drawString(cols[1], y, extra)
            y -= 5 * mm
        if pn == len(pages) - 1:
            y -= 4 * mm
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(15 * mm, y, f"Total Withdrawals {indian(total_dr)}    Total Deposits {indian(total_cr)}")
            c.drawString(15 * mm, y - 5 * mm, f"Closing Balance {rows[-1][5]}")
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(w / 2, 10 * mm, f"Page {pn + 1} of {len(pages)} - This is a computer generated statement")
        c.showPage()
    c.save()


def font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def scanned_statement_pdf(path, rows):
    """Pages are images only (no text layer), slightly rotated and noisy like a phone scan."""
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    for page in [rows[:18], rows[18:36]]:
        img = Image.new("L", (1654, 2339), 248)  # A4 at 200 dpi
        d = ImageDraw.Draw(img)
        f, fb = font(26), font(30)
        d.text((100, 100), "SAMPLE BANK LTD - Statement of Account", font=fb, fill=20)
        xs = [100, 330, 860, 1230, 1400, 1580]
        y = 220
        for x, t, right in zip(xs, ["Date", "Narration", "Ref", "Withdrawal", "Deposit", "Balance"], [0, 0, 0, 1, 1, 1]):
            if right:
                tw = d.textlength(t, font=f); d.text((x - tw, y), t, font=f, fill=20)
            else:
                d.text((x, y), t, font=f, fill=20)
        y += 55
        for r in page:
            vals = [r[0], wrap(r[1], 26)[0], r[2], r[3], r[4], r[5]]
            for i, (x, t) in enumerate(zip(xs, vals)):
                if i >= 3:
                    tw = d.textlength(t, font=f); d.text((x - tw, y), t, font=f, fill=25)
                else:
                    d.text((x, y), t, font=f, fill=25)
            y += 48
        img = img.rotate(0.6, fillcolor=248, resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.6))
        noise = Image.effect_noise(img.size, 12).convert("L")
        img = Image.blend(img, noise, 0.06)
        buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=70); buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, w, h)
        c.showPage()
    c.save()


def invoice_pdf(path):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 18); c.drawString(20 * mm, h - 25 * mm, "TAX INVOICE")
    c.setFont("Helvetica", 9)
    for i, t in enumerate(["Sample Supplies Pvt Ltd, 12 Market Road, Pune 411001", "GSTIN: 27ABCDE1234F1Z5", "Invoice No: INV/2024-25/0042    Date: 15-Apr-2024", "Bill to: Example Traders, Mumbai"]):
        c.drawString(20 * mm, h - (35 + i * 5) * mm, t)
    y = h - 70 * mm
    head = ["S.No", "Description", "HSN", "Qty", "Rate", "Amount"]
    xs = [20, 32, 110, 135, 160, 190]
    c.setFont("Helvetica-Bold", 9)
    for x, t, r in zip(xs, head, [0, 0, 0, 1, 1, 1]):
        (c.drawRightString if r else c.drawString)(x * mm, y, t)
    c.setFont("Helvetica", 9)
    items = [("A4 copier paper (500 sheets)", "4802", 20, Decimal("285.00")), ("Toner cartridge 88A", "8443", 3, Decimal("2450.00")),
             ("Box files", "4820", 15, Decimal("95.50")), ("Annual maintenance - printers", "9987", 1, Decimal("12000.00"))]
    sub = Decimal(0)
    for n, (desc, hsn, q, rate) in enumerate(items, 1):
        y -= 6 * mm
        amt = rate * q; sub += amt
        for x, t, r in zip(xs, [str(n), desc, hsn, str(q), indian(rate), indian(amt)], [0, 0, 0, 1, 1, 1]):
            (c.drawRightString if r else c.drawString)(x * mm, y, t)
    gst = (sub * Decimal("0.18")).quantize(Decimal("0.01"))
    for label, v in [("Sub-total", sub), ("CGST 9%", gst / 2), ("SGST 9%", gst / 2), ("Total", sub + gst)]:
        y -= 7 * mm
        c.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 9)
        c.drawRightString(160 * mm, y, label); c.drawRightString(190 * mm, y, indian(v))
    c.showPage(); c.save()


def mixed_report_pdf(path):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 20); c.drawString(20 * mm, h - 25 * mm, "Quarterly Business Review")
    c.setFont("Helvetica-Bold", 13); c.drawString(20 * mm, h - 38 * mm, "1. Summary")
    c.setFont("Helvetica", 10.5)
    text = ("Revenue for the quarter increased compared with the previous quarter, driven by higher volumes in the retail "
            "segment. Operating costs remained broadly stable. The board approved the capital expenditure plan for the next year.")
    y = h - 46 * mm
    for line in wrap(text, 90):
        c.drawString(20 * mm, y, line); y -= 5 * mm
    y -= 3 * mm
    for b in ["Revenue up 12% quarter on quarter", "Two new branches opened", "Receivable days reduced from 54 to 47"]:
        c.drawString(24 * mm, y, "\u2022  " + b); y -= 5.5 * mm
    img = Image.new("RGB", (600, 300), "white"); d = ImageDraw.Draw(img)
    for i, v in enumerate([120, 180, 150, 220]):
        d.rectangle([60 + i * 130, 280 - v, 140 + i * 130, 280], fill=(30, 79, 163))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    c.drawImage(ImageReader(buf), 20 * mm, y - 75 * mm, 120 * mm, 60 * mm)
    c.setFont("Helvetica-Oblique", 9); c.drawString(20 * mm, y - 80 * mm, "Figure 1: Quarterly revenue (illustrative)")
    c.showPage()
    # Page 2: scanned (image only)
    img = Image.new("L", (1654, 2339), 250); d = ImageDraw.Draw(img); f = font(32)
    d.text((120, 150), "Annexure A - signed minutes (scanned)", font=f, fill=20)
    for i in range(12):
        d.text((120, 260 + i * 60), f"Item {i + 1}: resolution recorded and approved by the members present.", font=font(26), fill=30)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=75); buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, w, h); c.showPage(); c.save()


def large_pdf(path, pages=100):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    for p in range(pages):
        c.setFont("Helvetica-Bold", 16); c.drawString(20 * mm, h - 25 * mm, f"Large document - page {p + 1}")
        c.setFont("Helvetica", 10)
        for i in range(40):
            c.drawString(20 * mm, h - (35 + i * 6) * mm, f"Line {i + 1} of page {p + 1}: sample text for performance testing.")
        c.showPage()
    c.save()


def protected_pdfs(src):
    r = PdfReader(src)
    w = PdfWriter(); [w.add_page(p) for p in r.pages]
    w.encrypt(user_password="test1234", owner_password="owner-secret", algorithm="AES-256")
    with open(os.path.join(OUT, "protected_password_test1234.pdf"), "wb") as f: w.write(f)
    # Opens without a password, but copying/extracting and editing are not allowed.
    w = PdfWriter(); [w.add_page(p) for p in r.pages]
    from pypdf.constants import UserAccessPermissions as P
    w.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-256", permissions_flag=P.PRINT)
    with open(os.path.join(OUT, "restricted_no_copy.pdf"), "wb") as f: w.write(f)


def damaged_pdf(src):
    data = open(src, "rb").read()
    with open(os.path.join(OUT, "damaged_truncated.pdf"), "wb") as f: f.write(data[: len(data) // 3])
    with open(os.path.join(OUT, "not_a_pdf.pdf"), "wb") as f: f.write(b"This is plain text with a .pdf name.\n")


def workbook(path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb = Workbook()
    ws = wb.active; ws.title = "Ledger"
    thin = Side(style="thin")
    ws.merge_cells("A1:F1"); ws["A1"] = "General Ledger - FY 2024-25"; ws["A1"].font = Font(bold=True, size=14); ws["A1"].alignment = Alignment(horizontal="center")
    hdr = ["Date", "Voucher", "Particulars", "Debit", "Credit", "Balance"]
    for i, t in enumerate(hdr, 1):
        cell = ws.cell(row=3, column=i, value=t); cell.font = Font(bold=True); cell.fill = PatternFill("solid", fgColor="D9E2FF"); cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    import datetime
    bal = 0
    for r in range(4, 64):
        dr = random.choice([0, round(random.uniform(1000, 900000), 2)]); cr = 0 if dr else round(random.uniform(1000, 500000), 2)
        bal += dr - cr
        vals = [datetime.date(2024, 4, 1) + datetime.timedelta(days=r), f"JV/{r:04d}", f"Entry {r} - long particulars text that may need wrapping in the PDF", dr or None, cr or None, bal]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=i, value=v); c.border = Border(left=thin, right=thin)
            if i == 1: c.number_format = "dd-mm-yyyy"
            if i >= 4: c.number_format = '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00'
    for col, wdt in zip("ABCDEF", [12, 10, 48, 14, 14, 16]): ws.column_dimensions[col].width = wdt
    ws.print_area = "A1:F40"
    s2 = wb.create_sheet("Summary")
    s2["A1"] = "Particulars"; s2["B1"] = "Amount"; s2["A1"].font = s2["B1"].font = Font(bold=True)
    for i, (k, v) in enumerate([("Revenue", 2450000.5), ("Expenses", -1830000), ("Tax", -150000.25)], 2):
        s2.cell(row=i, column=1, value=k); c = s2.cell(row=i, column=2, value=v); c.number_format = "#,##0.00;(#,##0.00)"
    s2["A6"] = "Net (formula - no cached value)"; s2["B6"] = "=SUM(B2:B4)"
    s2["A8"] = "Margin"; s2["B8"] = 0.2346; s2["B8"].number_format = "0.0%"
    s3 = wb.create_sheet("Wide")
    for col in range(1, 31):
        s3.cell(row=1, column=col, value=f"Month {col}").font = Font(bold=True)
        for row in range(2, 25): s3.cell(row=row, column=col, value=row * col * 101.5).number_format = "#,##0.00"
    hid = wb.create_sheet("Hidden notes"); hid["A1"] = "This sheet is hidden"; hid.sheet_state = "hidden"
    wb.save(path)


def word_doc(path):
    from docx import Document
    from docx.shared import Inches, Pt
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "Sample Consultants LLP - Engagement Letter"
    doc.sections[0].footer.paragraphs[0].text = "Confidential"
    doc.add_heading("Engagement Letter for Audit Services", 0)
    doc.add_heading("1. Scope of work", level=1)
    p = doc.add_paragraph("We are pleased to confirm our acceptance of the audit engagement. ")
    p.add_run("The audit will be conducted in accordance with the Standards on Auditing. ").bold = True
    p.add_run("Our report will be addressed to the members.").italic = True
    for b in ["Statutory audit of financial statements", "Tax audit under section 44AB", "Review of GST returns"]:
        doc.add_paragraph(b, style="List Bullet")
    for b in ["Planning", "Fieldwork", "Reporting"]:
        doc.add_paragraph(b, style="List Number")
    doc.add_heading("2. Fees", level=1)
    t = doc.add_table(rows=1, cols=3); t.style = "Table Grid"
    for i, x in enumerate(["Service", "Fee (₹)", "Due"]): t.rows[0].cells[i].text = x
    for row in [("Statutory audit", "1,50,000.00", "On completion"), ("Tax audit", "75,000.00", "30-Sep-2024"), ("GST review", "40,000.00", "Quarterly")]:
        cells = t.add_row().cells
        for i, x in enumerate(row): cells[i].text = x
    img = Image.new("RGB", (400, 120), (230, 238, 248)); ImageDraw.Draw(img).text((20, 45), "Firm logo (sample image)", fill=(30, 79, 163))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    doc.add_picture(buf, width=Inches(3))
    doc.add_page_break()
    doc.add_heading("3. हिंदी अनुभाग (Hindi section)", level=1)
    doc.add_paragraph("यह एक नमूना अनुच्छेद है जो हिंदी पाठ के रूपांतरण का परीक्षण करता है।").runs[0].font.size = Pt(12)
    doc.save(path)


def legacy_copies():
    """Old-format .xls/.doc copies made with LibreOffice (skipped if it is not installed)."""
    import shutil, subprocess
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        print("LibreOffice not found: skipping .xls/.doc samples")
        return
    for src, fmt in [("workbook_multi_sheet.xlsx", "xls"), ("word_tables_images.docx", "doc")]:
        subprocess.run([office, "--headless", "--convert-to", fmt, "--outdir", OUT, os.path.join(OUT, src)], check=False, capture_output=True, timeout=180)


def main():
    rows = transactions()
    bank_statement_pdf(os.path.join(OUT, "bank_statement_text.pdf"), rows)
    scanned_statement_pdf(os.path.join(OUT, "bank_statement_scanned.pdf"), rows)
    invoice_pdf(os.path.join(OUT, "invoice.pdf"))
    mixed_report_pdf(os.path.join(OUT, "report_mixed_text_and_scan.pdf"))
    large_pdf(os.path.join(OUT, "large_100_pages.pdf"))
    protected_pdfs(os.path.join(OUT, "invoice.pdf"))
    damaged_pdf(os.path.join(OUT, "invoice.pdf"))
    workbook(os.path.join(OUT, "workbook_multi_sheet.xlsx"))
    word_doc(os.path.join(OUT, "word_tables_images.docx"))
    legacy_copies()
    for f in sorted(os.listdir(OUT)):
        print(f"{os.path.getsize(os.path.join(OUT, f)) / 1024:8.1f} KB  {f}")


if __name__ == "__main__":
    main()
