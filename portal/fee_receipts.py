from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from fpdf import FPDF

from .fees import month_display_label


PAGE_WIDTH = 148
PAGE_HEIGHT = 210


def build_fee_receipt(record, outstanding_amount, logo_path, font_path):
    pdf = FPDF(orientation='P', unit='mm', format=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.set_margins(14, 12, 14)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.add_font('NotoSansBengali', fname=str(font_path))
    pdf.set_text_shaping(use_shaping_engine=True, script='Beng', language='bn')

    pdf.set_draw_color(45, 58, 91)
    pdf.set_line_width(0.7)
    pdf.rect(7, 7, PAGE_WIDTH - 14, PAGE_HEIGHT - 14, style='D')
    pdf.set_draw_color(218, 224, 237)

    pdf.image(str(logo_path), x=(PAGE_WIDTH - 38) / 2, y=13, w=38)
    pdf.set_y(34)
    pdf.set_text_color(34, 47, 76)
    pdf.set_font('NotoSansBengali', size=17)
    pdf.cell(0, 9, 'MONEY RECEIPT', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(101, 114, 139)
    pdf.set_font('NotoSansBengali', size=9)
    pdf.cell(0, 6, 'বেতন জমার রসিদ', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)

    pdf.set_draw_color(218, 224, 237)
    pdf.line(14, pdf.get_y(), PAGE_WIDTH - 14, pdf.get_y())
    pdf.ln(4)
    pdf.set_text_color(72, 84, 109)
    pdf.set_font('NotoSansBengali', size=9)
    pdf.cell(60, 6, f'রসিদ নং: MR-{record.pk}-{record.month}')
    receipt_date = timezone.localtime(record.updated_at)
    pdf.cell(60, 6, f'তারিখ: {receipt_date:%d-%m-%Y}', align='R', new_x='LMARGIN', new_y='NEXT')

    pdf.set_fill_color(244, 246, 252)
    pdf.set_text_color(55, 70, 101)
    pdf.set_font('NotoSansBengali', size=10)
    receipt_month = month_display_label(record.month)
    pdf.cell(
        0,
        8,
        f'{receipt_month} মাসের বেতন হিসাব',
        fill=True,
        align='C',
        new_x='LMARGIN',
        new_y='NEXT',
    )
    pdf.ln(4)

    student = record.student
    rows = (
        ('শিক্ষার্থীর নাম', student.name),
        ('শিক্ষার্থী আইডি', student.student_id),
        ('ব্যাচ / শ্রেণি', student.class_name),
        ('বর্ষ', student.get_year_group_display()),
        ('মোবাইল নম্বর', student.phone or 'তথ্য দেওয়া নেই'),
    )
    for label, value in rows:
        start_y = pdf.get_y()
        pdf.set_xy(15, start_y)
        pdf.set_text_color(104, 116, 138)
        pdf.set_font('NotoSansBengali', size=9)
        pdf.multi_cell(39, 6, label)
        label_end_y = pdf.get_y()
        pdf.set_xy(54, start_y)
        pdf.set_text_color(40, 51, 75)
        pdf.set_font('NotoSansBengali', size=9)
        pdf.multi_cell(78, 6, value)
        pdf.set_y(max(label_end_y, pdf.get_y()) + 1.5)

    pdf.ln(1)
    pdf.set_draw_color(218, 224, 237)
    pdf.line(14, pdf.get_y(), PAGE_WIDTH - 14, pdf.get_y())
    pdf.ln(3)
    financial_rows = (
        ('নির্ধারিত বেতন', record.monthly_fee),
        ('জমা', record.amount_paid),
        ('বাকি', record.due_amount),
        ('সকল মাসের মোট বকেয়া', outstanding_amount),
    )
    for label, amount in financial_rows:
        start_y = pdf.get_y()
        pdf.set_xy(15, start_y)
        pdf.set_text_color(76, 88, 111)
        pdf.set_font('NotoSansBengali', size=9)
        pdf.multi_cell(73, 7, label)
        label_end_y = pdf.get_y()
        pdf.set_xy(89, start_y)
        pdf.set_text_color(35, 49, 77)
        pdf.set_font('NotoSansBengali', size=9)
        pdf.multi_cell(42, 7, f'{amount:,.2f} টাকা', align='R')
        pdf.set_y(max(label_end_y, pdf.get_y()) + 1)

    if outstanding_amount == Decimal('0.00'):
        stamp_y = min(pdf.get_y() + 2, 161)
        pdf.set_draw_color(30, 142, 101)
        pdf.set_text_color(30, 142, 101)
        pdf.set_line_width(1.1)
        pdf.ellipse(48, stamp_y, 52, 15, style='D')
        pdf.set_xy(48, stamp_y + 3)
        pdf.set_font('NotoSansBengali', size=12)
        pdf.cell(52, 8, 'PAID · পরিশোধিত', align='C')

    pdf.set_y(183)
    pdf.set_draw_color(218, 224, 237)
    pdf.line(14, pdf.get_y(), PAGE_WIDTH - 14, pdf.get_y())
    pdf.ln(3)
    pdf.set_text_color(110, 119, 137)
    pdf.set_font('NotoSansBengali', size=7)
    pdf.multi_cell(
        0,
        4,
        'এই রসিদটি সিস্টেম থেকে স্বয়ংক্রিয়ভাবে তৈরি; স্বাক্ষরের প্রয়োজন নেই।',
        align='C',
    )
    return bytes(pdf.output())


def receipt_asset_paths(base_dir):
    static_dir = Path(base_dir) / 'static'
    return (
        static_dir / 'images' / 'modulus-logo.png',
        static_dir / 'fonts' / 'NotoSansBengali-Regular.ttf',
    )
