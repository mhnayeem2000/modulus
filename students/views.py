from calendar import Calendar, monthrange
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateformat import time_format
from django.utils.formats import date_format

from attendance.models import Attendance
from exams.models import Exam, ExamResult
from portal.access import get_role, role_required
from portal.models import (
    ClassSession,
    Routine,
    StudentFeeRecord,
    SupportSessionAttendance,
    TeacherAttendance,
    UserProfile,
)
from portal.routine_version import get_teacher_routine_version
from portal.study_progress import (
    build_class_session_progress,
    get_study_report_date,
    group_class_session_progress,
    paginate_study_progress,
)
from portal.year_groups import BATCH_LABELS, YEAR_GROUPS
from .forms import StudentAccountForm, StudentForm, StudentUpdateForm
from .attendance_calendar import build_attendance_calendar
from .models import Student


@login_required
def student_detail(request, student_id=None):
    role = get_role(request.user)
    if role == 'student':
        student = Student.objects.filter(user=request.user, is_active=True).first()
        if not student or (student_id is not None and student.pk != student_id):
            raise PermissionDenied
    elif role in ('teacher', 'superadmin'):
        if student_id is None:
            raise PermissionDenied
        student = get_object_or_404(Student, pk=student_id, is_active=True)
    else:
        raise PermissionDenied

    today = timezone.localdate()
    month_cursor = date(today.year, today.month, 1)
    for _ in range(5):
        month_cursor = date(
            month_cursor.year - (month_cursor.month == 1),
            month_cursor.month - 1 if month_cursor.month > 1 else 12,
            1,
        )
    attendance_records = list(
        Attendance.objects.filter(
            student=student,
            date__gte=month_cursor,
            date__lte=today,
        ).order_by('date')
    )
    month_starts = []
    attendance_counts = {}
    current_month = month_cursor
    for _ in range(6):
        month_starts.append(current_month)
        attendance_counts[current_month] = {'attended': 0, 'marked': 0}
        current_month = date(
            current_month.year + (current_month.month == 12),
            current_month.month % 12 + 1,
            1,
        )
    for record in attendance_records:
        month_key = date(record.date.year, record.date.month, 1)
        attendance_counts[month_key]['marked'] += 1
        if record.status in (Attendance.Status.PRESENT, Attendance.Status.LATE):
            attendance_counts[month_key]['attended'] += 1
    attendance_chart = [
        {
            **attendance_counts[month],
            'label': date_format(month, 'M y'),
            'bar_height': 0,
        }
        for month in month_starts
    ]
    max_attendance = max((month['attended'] for month in attendance_chart), default=0)
    for month in attendance_chart:
        month['bar_height'] = round(month['attended'] / max_attendance * 100) if max_attendance else 0
    attended_days = Attendance.objects.filter(
        student=student,
        date__lte=today,
        status__in=(Attendance.Status.PRESENT, Attendance.Status.LATE),
    ).count()
    attendance_calendar_url = (
        reverse('student_own_detail')
        if role == 'student'
        else reverse('student_detail', args=[student.pk])
    )
    attendance_calendar = build_attendance_calendar(
        student,
        request.GET.get('month'),
        attendance_calendar_url,
    )

    exams = Exam.objects.filter(year_group=student.year_group, exam_date__lte=today).order_by(
        'exam_date', 'created_at'
    )
    results = list(
        ExamResult.objects.filter(student=student)
        .select_related('exam')
        .order_by('exam__exam_date', 'exam__created_at')
    )
    result_exam_ids = {result.exam_id for result in results}
    exam_taken_ids = {exam.pk for exam in exams if exam.pk in result_exam_ids}
    progress_groups = {}
    for result in results:
        exam = result.exam
        group_key = (getattr(exam, 'subject', ''), exam.paper)
        group = progress_groups.setdefault(group_key, {
            'label': ' · '.join(part for part in group_key if part) or exam.title,
            'results': [],
        })
        percentage = float(result.marks / exam.total_marks * 100)
        group['results'].append({
            'title': exam.title,
            'date': date_format(exam.exam_date, 'j M y'),
            'chapter': exam.chapter,
            'marks': result.marks,
            'total_marks': exam.total_marks,
            'percentage': percentage,
        })
    for group in progress_groups.values():
        for result in group['results']:
            result['bar_height'] = round(result['percentage'])

    student_fee_records = list(StudentFeeRecord.objects.filter(student=student).order_by('-month'))
    student_fee_total = sum((record.monthly_fee for record in student_fee_records), 0)
    student_fee_paid = sum((record.amount_paid for record in student_fee_records), 0)
    student_fee_due = sum((record.due_amount for record in student_fee_records), 0)
    return render(request, 'students/student_detail.html', {
        'student': student,
        **attendance_calendar,
        'attended_days': attended_days,
        'attendance_chart': attendance_chart,
        'exam_count': exams.count(),
        'exam_taken_count': len(exam_taken_ids),
        'exam_missed_count': exams.exclude(pk__in=exam_taken_ids).count(),
        'exam_results': results,
        'progress_groups': list(progress_groups.values()),
        'student_fee_records': student_fee_records,
        'student_fee_total': student_fee_total,
        'student_fee_paid': student_fee_paid,
        'student_fee_due': student_fee_due,
        'student_fee_up_to_date': student_fee_due == 0,
    })


def get_next_teacher_class(routines, now):
    next_classes = []
    for routine in routines:
        if routine.weekday == now.weekday() and routine.start_time <= now.time().replace(tzinfo=None) < routine.end_time:
            continue
        days_ahead = (routine.weekday - now.weekday()) % 7
        if days_ahead == 0 and routine.start_time <= now.time().replace(tzinfo=None):
            days_ahead = 7
        class_date = now.date() + timedelta(days=days_ahead)
        starts_at = timezone.make_aware(
            datetime.combine(class_date, routine.start_time),
            timezone.get_current_timezone(),
        )
        next_classes.append((starts_at, routine, class_date))
    if not next_classes:
        return None
    starts_at, routine, class_date = min(next_classes, key=lambda item: item[0])
    day_label = 'আজ' if class_date == now.date() else (
        'আগামীকাল' if class_date == now.date() + timedelta(days=1) else date_format(class_date, 'l, j F')
    )
    return {
        'routine': routine,
        'date': class_date,
        'starts_at': starts_at,
        'day_label': day_label,
        'time_label': (
            f'{time_format(routine.start_time, "g:i A")}–'
            f'{time_format(routine.end_time, "g:i A")}'
        ),
    }


def calendar_class_event(routine, status):
    return {
        'routine': routine,
        'routine_id': routine.pk,
        'class_name': routine.get_year_group_display(),
        'subject': routine.subject,
        'start_time': routine.start_time,
        'end_time': routine.end_time,
        'year_key': routine.year_group,
        'status': status,
        'event_type': 'class',
    }


@login_required
def dashboard(request):
    role = get_role(request.user)
    if role == 'student':
        return redirect('student_dashboard')
    if role == 'superadmin':
        return redirect('admin_dashboard')
    return redirect('teacher_dashboard')


@role_required('teacher')
def teacher_dashboard(request):
    today = timezone.localdate()
    calendar_month = today.replace(day=1)
    raw_calendar_month = request.GET.get('month', '')
    if raw_calendar_month:
        try:
            calendar_month = date.fromisoformat(f'{raw_calendar_month}-01')
        except ValueError:
            calendar_month = today.replace(day=1)
    month_index = calendar_month.year * 12 + calendar_month.month - 1
    previous_month_index = month_index - 1
    next_month_index = month_index + 1
    previous_calendar_month = (
        f'{previous_month_index // 12:04d}-{previous_month_index % 12 + 1:02d}'
    )
    next_calendar_month = f'{next_month_index // 12:04d}-{next_month_index % 12 + 1:02d}'
    teacher_routines = list(
        Routine.objects.filter(teacher=request.user).order_by('weekday', 'start_time')
    )
    local_now = timezone.localtime()
    next_class = get_next_teacher_class(teacher_routines, local_now)
    today_attendance = TeacherAttendance.objects.filter(
        teacher=request.user,
        date=today,
    ).first()
    attendance_labels = {
        TeacherAttendance.Status.APPROVED: 'উপস্থিত',
        TeacherAttendance.Status.ABSENT: 'অনুপস্থিত',
        TeacherAttendance.Status.PENDING: 'যাচাইয়ে',
        TeacherAttendance.Status.REJECTED: 'প্রত্যাখ্যাত',
    }
    today_classes = [
        {
            'routine': routine,
            'attendance': today_attendance,
        }
        for routine in teacher_routines
        if routine.weekday == today.weekday()
    ]
    calendar_month_end = date(
        calendar_month.year + (calendar_month.month == 12),
        1 if calendar_month.month == 12 else calendar_month.month + 1,
        1,
    )
    calendar_events_by_date = {}
    for record in TeacherAttendance.objects.filter(
        teacher=request.user,
        date__gte=calendar_month,
        date__lt=calendar_month_end,
        status=TeacherAttendance.Status.APPROVED,
    ).select_related('routine'):
        routine = record.routine
        if routine:
            class_status = 'completed' if record.date < today or (
                record.date == today and routine.end_time <= local_now.time().replace(tzinfo=None)
            ) else 'upcoming'
            calendar_events_by_date.setdefault(record.date, []).append(
                calendar_class_event(routine, class_status),
            )
        else:
            calendar_events_by_date.setdefault(record.date, []).append({
                'routine_id': None,
                'class_name': '',
                'subject': 'যাচাইকৃত উপস্থিতি',
                'start_time': None,
                'end_time': None,
                'year_key': 'first',
                'status': 'completed',
                'event_type': 'class',
            })

    if calendar_month.year == today.year and calendar_month.month == today.month:
        for routine in teacher_routines:
            if (
                routine.weekday == today.weekday()
                and routine.start_time <= local_now.time().replace(tzinfo=None) < routine.end_time
            ):
                today_events = calendar_events_by_date.setdefault(today, [])
                running_event = next(
                    (event for event in today_events if event['routine_id'] == routine.pk),
                    None,
                )
                if running_event:
                    running_event['status'] = 'running'
                else:
                    today_events.append(calendar_class_event(routine, 'running'))

    if (
        next_class
        and next_class['date'].year == calendar_month.year
        and next_class['date'].month == calendar_month.month
    ):
        next_routine = next_class['routine']
        day_events = calendar_events_by_date.setdefault(next_class['date'], [])
        next_event = next(
            (event for event in day_events if event['routine_id'] == next_routine.pk),
            None,
        )
        if next_event:
            next_event['status'] = 'upcoming'
        else:
            day_events.append(calendar_class_event(next_routine, 'upcoming'))

    for exam in Exam.objects.filter(
        created_by=request.user,
        exam_date__gte=calendar_month,
        exam_date__lt=calendar_month_end,
    ).order_by('exam_date', 'created_at'):
        calendar_events_by_date.setdefault(exam.exam_date, []).append({
            'event_type': 'exam',
            'title': exam.title,
            'class_name': exam.get_year_group_display(),
            'subject': exam.paper,
            'start_time': None,
            'end_time': None,
            'year_key': exam.year_group,
            'status': 'exam',
        })

    calendar_weeks = [
        [
            {
                'date': day,
                'in_month': day.month == calendar_month.month,
                'is_today': day == today,
                'classes': calendar_events_by_date.get(day, []),
            }
            for day in week
        ]
        for week in Calendar(firstweekday=0).monthdatescalendar(
            calendar_month.year, calendar_month.month,
        )
    ]
    total_days = monthrange(today.year, today.month)[1]
    teacher_month_records = list(TeacherAttendance.objects.filter(
        teacher=request.user,
        date__year=today.year,
        date__month=today.month,
        status__in=[TeacherAttendance.Status.APPROVED, TeacherAttendance.Status.ABSENT],
    ).values('date__day', 'status'))
    days = {item['date__day']: item['status'] for item in teacher_month_records}
    chart = []
    for day in range(1, total_days + 1):
        status = days.get(day)
        present = int(status == TeacherAttendance.Status.APPROVED)
        absent = int(status == TeacherAttendance.Status.ABSENT)
        recorded = int(status is not None)
        chart.append({
            'day': day,
            'present': present,
            'absent': absent,
            'present_height': round(present * 100 / recorded) if recorded else 0,
            'absent_height': round(absent * 100 / recorded) if recorded else 0,
            'has_data': bool(recorded),
        })

    totals = {
        'present': sum(item['status'] == TeacherAttendance.Status.APPROVED for item in teacher_month_records),
        'absent': sum(item['status'] == TeacherAttendance.Status.ABSENT for item in teacher_month_records),
    }
    reviewed_days = totals['present'] + totals['absent']
    rate = round(totals['present'] * 100 / reviewed_days) if reviewed_days else 0
    month_start = today.replace(day=1)
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    teacher_exams = Exam.objects.filter(
        created_by=request.user, exam_date__gte=month_start, exam_date__lt=next_month,
    )
    monthly_sessions = ClassSession.objects.filter(
        teacher=request.user, date__gte=month_start, date__lt=next_month,
    )
    monthly_class_groups = list(
        monthly_sessions.values('year_group').annotate(total=Count('id')).order_by('year_group')
    )
    for item in monthly_class_groups:
        item['year_key'] = item['year_group']
        item['class_name'] = BATCH_LABELS[item['year_group']]
    monthly_exam_chapters = list(teacher_exams.values(
        'chapter', 'paper', 'year_group',
    ).annotate(total=Count('id')).order_by('year_group', 'chapter'))
    for item in monthly_exam_chapters:
        item['year_key'] = item['year_group']
        item['class_name'] = BATCH_LABELS[item['year_group']]

    study_report_date = get_study_report_date(request.GET.get('study_date', '').strip())
    today_study_sessions, study_report_page = paginate_study_progress(
        build_class_session_progress(
            ClassSession.objects.filter(
                teacher=request.user,
                date=study_report_date,
            ).order_by('year_group', 'subject')
        ),
        request.GET.get('study_page', 1),
    )
    return render(request, 'students/dashboard.html', {
        'today': today,
        'study_report_date': study_report_date,
        'study_report_page': study_report_page,
        'month_label': date_format(today, 'F Y'),
        'student_count': Student.objects.filter(is_active=True).count(),
        'today_attendance_label': attendance_labels.get(
            today_attendance.status if today_attendance else None,
            'নথিভুক্ত নয়',
        ),
        'exam_count': Exam.objects.filter(created_by=request.user).count(),
        'monthly_classes': monthly_sessions.filter(date__lte=today).count(),
        'today_completed_classes': ClassSession.objects.filter(
            teacher=request.user, date=today,
        ).count(),
        'today_study_sessions': today_study_sessions,
        'today_study_year_groups': group_class_session_progress(today_study_sessions),
        'support_session_days': SupportSessionAttendance.objects.filter(
            teacher=request.user,
        ).count(),
        'support_session_joined_today': SupportSessionAttendance.objects.filter(
            teacher=request.user,
            date=today,
        ).exists(),
        'monthly_teacher_attendance': TeacherAttendance.objects.filter(
            teacher=request.user,
            date__gte=month_start,
            date__lte=today,
            status=TeacherAttendance.Status.APPROVED,
        ).count(),
        'monthly_exam_count': teacher_exams.count(),
        'monthly_exam_chapters': monthly_exam_chapters,
        'monthly_class_groups': monthly_class_groups,
        'year_groups': tuple(
            (key, label) for key, label in YEAR_GROUPS if key in {'first', 'second'}
        ),
        'attendance_rate': rate,
        'month_present': totals['present'],
        'month_absent': totals['absent'],
        'reviewed_teacher_days': reviewed_days,
        'chart': chart,
        'recent_exams': Exam.objects.filter(created_by=request.user).order_by('-exam_date', '-created_at')[:5],
        'teacher_routines': teacher_routines,
        'teacher_routine_version': get_teacher_routine_version(request.user),
        'calendar_month': calendar_month,
        'calendar_month_label': date_format(calendar_month, 'F Y'),
        'calendar_month_value': f'{calendar_month.year:04d}-{calendar_month.month:02d}',
        'previous_calendar_month': previous_calendar_month,
        'next_calendar_month': next_calendar_month,
        'calendar_weekdays': ['সোম', 'মঙ্গল', 'বুধ', 'বৃহস্পতি', 'শুক্র', 'শনি', 'রবি'],
        'calendar_weeks': calendar_weeks,
        'calendar_has_events': bool(calendar_events_by_date),
        'today_classes': today_classes,
        'next_class': next_class,
        'attendance_notice': request.GET.get('attendance', ''),
    })


@role_required('teacher', 'superadmin')
def student_list(request):
    can_add_students = request.user.is_superuser
    students = Student.objects.filter(is_active=True)
    query = request.GET.get('q', '').strip()
    if query:
        search_filter = (
            Q(name__icontains=query) |
            Q(student_id__icontains=query) |
            Q(class_name__icontains=query)
        )
        normalized_query = query.casefold()
        if any(marker in normalized_query for marker in ('first', '1st', '১ম', 'প্রথম')):
            search_filter |= Q(year_group='first')
        if any(marker in normalized_query for marker in ('second', '2nd', '২য়', 'দ্বিতীয়')):
            search_filter |= Q(year_group='second')
        students = students.filter(search_filter)
    paginator = Paginator(students, 8)
    page_obj = paginator.get_page(request.GET.get('page'))
    attendance_students = Student.objects.filter(is_active=True).order_by('name')
    selected_attendance_student = None
    try:
        selected_student_id = int(request.GET.get('attendance_student', ''))
    except ValueError:
        selected_student_id = None
    if selected_student_id:
        selected_attendance_student = attendance_students.filter(pk=selected_student_id).first()
    if selected_attendance_student is None:
        selected_attendance_student = attendance_students.first()
    if request.method == 'POST' and not can_add_students:
        raise PermissionDenied('শিক্ষার্থী যোগ করার অনুমতি শুধু সুপার অ্যাডমিনের আছে।')
    form = StudentForm(request.POST if can_add_students and request.method == 'POST' else None)
    if can_add_students and request.method == 'POST' and form.is_valid():
        student = form.save(commit=False)
        username = form.cleaned_data['username']
        with transaction.atomic():
            if username:
                User = get_user_model()
                student_user = User.objects.create_user(
                    username=username,
                    password=form.cleaned_data['password'],
                    first_name=student.name,
                )
                UserProfile.objects.create(
                    user=student_user,
                    role=UserProfile.Role.STUDENT,
                    phone=student.phone,
                )
                student.user = student_user
            student.save()
        return redirect('student_list')
    attendance_calendar = {}
    if selected_attendance_student:
        calendar_query_params = {'attendance_student': selected_attendance_student.pk}
        if query:
            calendar_query_params['q'] = query
        attendance_calendar = build_attendance_calendar(
            selected_attendance_student,
            request.GET.get('month'),
            reverse('student_list'),
            calendar_query_params,
        )
        attendance_calendar['attendance_calendar_student'] = selected_attendance_student
    return render(request, 'students/student_list.html', {
        'students': page_obj.object_list,
        'page_obj': page_obj,
        'page_range': paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1),
        'form': form,
        'query': query,
        'can_add_students': can_add_students,
        'attendance_students': attendance_students,
        'attendance_calendar_student': selected_attendance_student,
        **attendance_calendar,
    })


@role_required('superadmin')
def student_edit(request, student_id):
    student = get_object_or_404(Student.objects.select_related('user'), pk=student_id, is_active=True)
    form = StudentUpdateForm(request.POST or None, instance=student)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            student = form.save()
            if student.user_id:
                student_user = student.user
                student_user.first_name = student.name
                if form.cleaned_data.get('username'):
                    student_user.username = form.cleaned_data['username']
                if form.cleaned_data.get('password'):
                    student_user.set_password(form.cleaned_data['password'])
                student_user.save()
                student_user.profile.phone = student.phone
                student_user.profile.save(update_fields=['phone'])
        return redirect('student_list')
    return render(request, 'students/student_edit.html', {
        'student': student,
        'form': form,
    })


@require_POST
@role_required('superadmin')
def student_delete(request, student_id):
    student = get_object_or_404(Student.objects.select_related('user'), pk=student_id)
    with transaction.atomic():
        student_user = student.user
        student.delete()
        if student_user:
            student_user.delete()
    return redirect('student_list')


@role_required('superadmin')
def student_account(request, student_id):
    student = get_object_or_404(Student, pk=student_id, is_active=True)
    if student.user_id:
        return render(request, 'students/student_account.html', {
            'student': student,
            'account_exists': True,
        })

    form = StudentAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        User = get_user_model()
        with transaction.atomic():
            account = User.objects.create_user(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password'],
                first_name=student.name,
            )
            UserProfile.objects.create(
                user=account,
                role=UserProfile.Role.STUDENT,
                phone=student.phone,
            )
            student.user = account
            student.save(update_fields=['user'])
        return redirect('student_account', student_id=student.pk)

    return render(request, 'students/student_account.html', {
        'student': student,
        'form': form,
        'account_exists': False,
        'can_create_account': request.user.is_superuser,
    })
