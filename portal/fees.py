from datetime import date
from decimal import Decimal

from django.utils.formats import date_format


def monthly_fee_for_month(records, month):
    current_record = next((record for record in records if record.month == month), None)
    if current_record:
        return current_record.monthly_fee

    previous_records = [
        record for record in records
        if record.month < month
    ]
    if not previous_records:
        return Decimal('0.00')
    return max(previous_records, key=lambda record: record.month).monthly_fee


def fee_summary_for_month(records, month, carry_forward=False):
    record = next((record for record in records if record.month == month), None)
    monthly_fee = (
        record.monthly_fee
        if record
        else monthly_fee_for_month(records, month) if carry_forward else Decimal('0.00')
    )
    amount_paid = record.amount_paid if record else Decimal('0.00')
    return {
        'record': record,
        'monthly_fee': monthly_fee,
        'amount_paid': amount_paid,
        'due_amount': max(monthly_fee - amount_paid, Decimal('0.00')),
    }


def month_display_label(month):
    return date_format(date.fromisoformat(f'{month}-01'), 'F Y')
