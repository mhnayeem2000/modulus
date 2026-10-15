from datetime import date, datetime, time, timedelta

from django.utils import timezone
from django.utils.dateformat import time_format
from django.utils.formats import date_format

from exams.models import Exam
from portal.access import get_role
from portal.models import Routine


def teacher_week_events(request):
    if not request.user.is_authenticated or get_role(request.user) != 'teacher':
        return {'teacher_week_events': [], 'teacher_has_week_events': False}

    now = timezone.localtime()
    today = now.date()
    month_start = today.replace(day=1)
    next_month = date(
        today.year + (today.month == 12),
        1 if today.month == 12 else today.month + 1,
        1,
    )
    teacher_month_exam_count = Exam.objects.filter(
        created_by=request.user,
        exam_date__gte=month_start,
        exam_date__lt=next_month,
    ).count()
    week_end = today + timedelta(days=7)
    routines = Routine.objects.filter(teacher=request.user).order_by('weekday', 'start_time')
    class_events = []
    for routine in routines:
        days_ahead = (routine.weekday - today.weekday()) % 7
        class_date = today + timedelta(days=days_ahead)
        if class_date == today and routine.end_time <= now.time().replace(tzinfo=None):
            class_date += timedelta(days=7)
        if class_date >= week_end:
            continue
        starts_at = timezone.make_aware(
            datetime.combine(class_date, routine.start_time),
            timezone.get_current_timezone(),
        )
        is_running = (
            class_date == today
            and routine.start_time <= now.time().replace(tzinfo=None) < routine.end_time
        )
        class_events.append({
            'kind': 'class',
            'title': routine.subject,
            'class_name': routine.class_name,
            'date': class_date,
            'starts_at': starts_at,
            'time_label': (
                f'{time_format(routine.start_time, "g:i A")}–'
                f'{time_format(routine.end_time, "g:i A")}'
            ),
            'day_label': 'আজ' if class_date == today else (
                'আগামীকাল' if class_date == today + timedelta(days=1)
                else date_format(class_date, 'D, j M')
            ),
            'status': 'running' if is_running else 'upcoming',
        })

    events = sorted(class_events, key=lambda event: event['starts_at'])[:1]
    exams = Exam.objects.filter(
        created_by=request.user,
        exam_date__gte=today,
        exam_date__lt=week_end,
    ).order_by('exam_date', 'created_at')
    for exam in exams:
        events.append({
            'kind': 'exam',
            'title': exam.title,
            'class_name': exam.class_name,
            'date': exam.exam_date,
            'starts_at': timezone.make_aware(
                datetime.combine(exam.exam_date, time.min),
                timezone.get_current_timezone(),
            ),
            'time_label': exam.paper,
            'day_label': 'আজ' if exam.exam_date == today else (
                'আগামীকাল' if exam.exam_date == today + timedelta(days=1)
                else date_format(exam.exam_date, 'D, j M')
            ),
            'status': 'exam',
        })
    events.sort(key=lambda event: (event['starts_at'], event['kind'] == 'exam'))
    return {
        'teacher_week_events': events,
        'teacher_popup_events': events,
        'teacher_has_week_events': bool(events),
        'teacher_month_exam_count': teacher_month_exam_count,
        'teacher_has_month_exam': teacher_month_exam_count > 0,
    }
