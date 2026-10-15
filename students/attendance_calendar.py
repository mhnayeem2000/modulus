from calendar import Calendar
from datetime import date
from urllib.parse import urlencode

from django.utils import timezone
from django.utils.dateformat import format as date_format

from attendance.models import Attendance


WEEKDAYS = ('সোম', 'মঙ্গল', 'বুধ', 'বৃহস্পতি', 'শুক্র', 'শনি', 'রবি')


def build_attendance_calendar(student, month_value=None, base_url='', query_params=None):
    today = timezone.localdate()
    try:
        selected_month = date.fromisoformat(f'{month_value}-01') if month_value else today.replace(day=1)
    except ValueError:
        selected_month = today.replace(day=1)
    if selected_month.year in (1, 9999):
        selected_month = today.replace(day=1)

    previous_month = date(
        selected_month.year - (selected_month.month == 1),
        selected_month.month - 1 if selected_month.month > 1 else 12,
        1,
    )
    next_month = date(
        selected_month.year + (selected_month.month == 12),
        selected_month.month % 12 + 1,
        1,
    )
    statuses = {
        record.date: record.status
        for record in Attendance.objects.filter(
            student=student,
            date__gte=selected_month,
            date__lt=next_month,
        )
    }
    weeks = []
    for week in Calendar(firstweekday=0).monthdatescalendar(selected_month.year, selected_month.month):
        weeks.append([
            {
                'date': day,
                'in_month': day.month == selected_month.month,
                'is_today': day == today,
                'status': statuses.get(day),
            }
            for day in week
        ])

    month_records = [
        status for record_date, status in statuses.items()
        if record_date.month == selected_month.month and record_date.year == selected_month.year
    ]
    params = dict(query_params or {})
    params['month'] = previous_month.strftime('%Y-%m')
    previous_url = f'{base_url}?{urlencode(params)}'
    params['month'] = next_month.strftime('%Y-%m')
    next_url = f'{base_url}?{urlencode(params)}'

    return {
        'attendance_calendar_month': selected_month,
        'attendance_calendar_month_label': date_format(selected_month, 'F Y'),
        'attendance_calendar_month_value': selected_month.strftime('%Y-%m'),
        'attendance_calendar_previous_url': previous_url,
        'attendance_calendar_next_url': next_url,
        'attendance_calendar_weekdays': WEEKDAYS,
        'attendance_calendar_weeks': weeks,
        'attendance_calendar_counts': {
            'present': month_records.count(Attendance.Status.PRESENT),
            'late': month_records.count(Attendance.Status.LATE),
            'absent': month_records.count(Attendance.Status.ABSENT),
            'marked': len(month_records),
        },
    }
