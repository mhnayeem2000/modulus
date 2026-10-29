from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, DecimalField, F, Max, Q, Sum, Value, When
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.dateformat import time_format
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from attendance.models import Attendance
from exams.models import Exam, ExamResult
from students.models import Student
from students.attendance_calendar import build_attendance_calendar
from .access import get_role, role_required
from .forms import (
    AccountPasswordChangeForm,
    AccountProfileForm,
    ClassSessionForm,
    ClassSessionProgressForm,
    LearningMaterialForm,
    RoutineForm,
    StudentFeeRecordForm,
    StudentMonthlyFeeForm,
    StudentFeedbackForm,
    TeacherForm,
    TeacherUpdateForm,
)
from .fee_receipts import build_fee_receipt, receipt_asset_paths
from .fees import fee_summary_for_month, month_display_label, monthly_fee_for_month
from .models import (
    ClassSession,
    ClassSessionProgress,
    LearningMaterial,
    Routine,
    StudentFeeRecord,
    StudentFeedback,
    SupportSessionAttendance,
    TeacherAttendance,
    UserProfile,
)
from .routine_version import get_teacher_routine_version
from .resources import STUDENT_BOOK_SECTIONS, mobile_pdf_preview_url
from .study_progress import (
    build_class_session_progress,
    get_study_report_date,
    group_class_session_progress,
    paginate_study_progress,
)
from .support_sessions import SUPPORT_SESSION_URL
from .year_groups import BATCH_LABELS, YEAR_GROUPS


def selected_month(request):
    raw_month = request.GET.get('month', '')
    if raw_month:
        try:
            month = date.fromisoformat(f'{raw_month}-01')
        except ValueError:
            month = timezone.localdate().replace(day=1)
        else:
            return month, f'{month.year:04d}-{month.month:02d}'
    else:
        month = timezone.localdate().replace(day=1)
    return month, f'{month.year:04d}-{month.month:02d}'


@login_required
def install_app(request):
    return render(request, 'portal/install_app.html')


@login_required
@never_cache
def account_profile(request):
    role = get_role(request.user)
    profile = UserProfile.objects.filter(user=request.user).first()
    student = None
    if role == UserProfile.Role.STUDENT:
        student = Student.objects.filter(user=request.user, is_active=True).first()

    if request.method == 'POST':
        form = AccountProfileForm(
            request.POST,
            instance=request.user,
            profile=profile,
            student=student,
        )
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, 'আপনার তথ্য সফলভাবে সংরক্ষণ করা হয়েছে।')
            return redirect('account_profile')
    else:
        form = AccountProfileForm(instance=request.user, profile=profile, student=student)

    if student:
        editable_details_label = 'আপনার নাম, ইমেইল ও মোবাইল নম্বর'
    elif profile:
        editable_details_label = 'আপনার নাম, ইমেইল ও মোবাইল নম্বর'
    else:
        editable_details_label = 'আপনার নাম ও ইমেইল'

    return render(request, 'portal/account_profile.html', {
        'form': form,
        'profile_user': request.user,
        'editable_details_label': editable_details_label,
        'account_display_name': (
            student.name
            if student
            else request.user.get_full_name() or request.user.username
        ),
        'account_role_label': {
            'student': 'শিক্ষার্থী',
            'teacher': 'শিক্ষক',
            'superadmin': 'সুপার অ্যাডমিন',
        }.get(role, 'ব্যবহারকারী'),
    })


@login_required
@never_cache
def account_password(request):
    if request.method == 'POST':
        form = AccountPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'আপনার পাসওয়ার্ড সফলভাবে পরিবর্তন করা হয়েছে।')
            return redirect('account_password')
    else:
        form = AccountPasswordChangeForm(request.user)
    return render(request, 'portal/account_password.html', {'form': form})


def month_bounds(month):
    next_month = month.replace(
        year=month.year + (month.month == 12),
        month=1 if month.month == 12 else month.month + 1,
    )
    return month, next_month


def student_for_user(user):
    try:
        student = user.student_record
    except Student.DoesNotExist as exc:
        raise PermissionDenied('এই অ্যাকাউন্টের সঙ্গে কোনো শিক্ষার্থী যুক্ত নেই।') from exc
    if not student.is_active:
        raise PermissionDenied('এই শিক্ষার্থীর অ্যাকাউন্টটি নিষ্ক্রিয়।')
    return student


def routines_for_student(student):
    return list(
        Routine.objects.filter(year_group=student.year_group)
        .select_related('teacher')
        .order_by('weekday', 'start_time')
    )


def class_session_submission_deadline(session):
    deadline_date = session.date + timedelta(days=3)
    return timezone.make_aware(
        datetime.combine(deadline_date, datetime.strptime('00:00', '%H:%M').time()),
        timezone.get_current_timezone(),
    )


def format_countdown(seconds):
    total_seconds = max(0, int(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f'{days} দিন {hours:02d} ঘন্টা {minutes:02d} মিনিট'
    if hours:
        return f'{hours} ঘন্টা {minutes:02d} মিনিট {secs:02d} সেকেন্ড'
    if minutes:
        return f'{minutes} মিনিট {secs:02d} সেকেন্ড'
    return f'{secs} সেকেন্ড'


@role_required('student')
def student_dashboard(request):
    student = student_for_user(request.user)
    today = timezone.localdate()
    try:
        study_date = date.fromisoformat(request.GET.get('study_date', ''))
    except ValueError:
        study_date = today
    if study_date > today:
        study_date = today
    local_now = timezone.localtime()
    attendance_calendar = build_attendance_calendar(
        student,
        request.GET.get('month'),
        reverse('student_dashboard'),
    )
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=6 - today.weekday())
    routines = routines_for_student(student)
    class_occurrences = []
    for routine in routines:
        days_ahead = (routine.weekday - today.weekday()) % 7
        class_date = today + timedelta(days=days_ahead)
        if class_date == today:
            now_time = local_now.time().replace(tzinfo=None)
            if routine.start_time <= now_time < routine.end_time:
                status = 'running'
            elif routine.start_time > now_time:
                status = 'upcoming'
            else:
                class_date += timedelta(days=7)
                status = 'upcoming'
        else:
            status = 'upcoming'
        starts_at = timezone.make_aware(
            datetime.combine(class_date, routine.start_time),
            timezone.get_current_timezone(),
        )
        class_occurrences.append((starts_at, routine, class_date, status))
    class_occurrences.sort(
        key=lambda occurrence: (
            occurrence[3] != 'running',
            occurrence[0],
        )
    )
    next_classes = [
        {
            'routine': routine,
            'date': class_date,
            'status': status,
            'day_label': (
                'আজ' if class_date == today
                else 'আগামীকাল' if class_date == tomorrow
                else date_format(class_date, 'l, j F')
            ),
            'time_label': (
                f'{time_format(routine.start_time, "g:i A")}–'
                f'{time_format(routine.end_time, "g:i A")}'
            ),
        }
        for _, routine, class_date, status in class_occurrences[:2]
    ]
    next_class = next_classes[0] if next_classes else None
    next_exam = Exam.objects.filter(
        year_group=student.year_group,
        exam_date__gte=today,
    ).order_by('exam_date', 'created_at').first()
    tomorrow_classes = [
        routine for routine in routines
        if routine.weekday == tomorrow.weekday()
    ]
    weekly_exams = Exam.objects.filter(
        year_group=student.year_group,
        exam_date__gte=today,
        exam_date__lte=week_end,
    ).order_by('exam_date', 'created_at')
    study_sessions = list(
        ClassSession.objects.filter(
            date=study_date,
            year_group=student.year_group,
        ).select_related('teacher').order_by('created_at', 'pk')
    )
    student_progress = {
        progress.session_id: progress
        for progress in ClassSessionProgress.objects.filter(
            student=student,
            session__in=study_sessions,
        )
    }
    now = timezone.now()
    study_context = []
    for session in study_sessions:
        progress = student_progress.get(session.pk)
        deadline = class_session_submission_deadline(session)
        time_left = max(0, (deadline - now).total_seconds())
        is_past_deadline = now >= deadline
        is_complete = bool(progress and progress.is_completed)
        display_status = 'completed' if is_complete else 'pending'
        if is_past_deadline and not is_complete:
            display_status = 'missed'
        study_context.append({
            'session': session,
            'progress': progress,
            'deadline': deadline,
            'time_left_seconds': time_left,
            'time_left_label': format_countdown(time_left),
            'is_past_deadline': is_past_deadline,
            'status': display_status,
            'can_submit': not is_past_deadline,
        })
    student_fee_records = list(StudentFeeRecord.objects.filter(student=student).order_by('-month'))
    for record in student_fee_records:
        record.month_label = month_display_label(record.month)
    student_fee_total = sum((record.monthly_fee for record in student_fee_records), Decimal('0.00'))
    student_fee_paid = sum((record.amount_paid for record in student_fee_records), Decimal('0.00'))
    student_fee_due = sum((record.due_amount for record in student_fee_records), Decimal('0.00'))
    current_fee_month = today.strftime('%Y-%m')
    current_fee_summary = fee_summary_for_month(
        student_fee_records,
        current_fee_month,
        carry_forward=True,
    )
    student_fee_current_record = current_fee_summary['record']
    student_fee_current_monthly_fee = current_fee_summary['monthly_fee']
    student_fee_current_paid = current_fee_summary['amount_paid']
    student_fee_current_due = current_fee_summary['due_amount']
    return render(request, 'portal/student_dashboard.html', {
        'student': student,
        **attendance_calendar,
        'today': today,
        'support_session_url': SUPPORT_SESSION_URL,
        'tomorrow': tomorrow,
        'next_class': next_class,
        'next_classes': next_classes,
        'next_exam': next_exam,
        'tomorrow_classes': tomorrow_classes,
        'week_end': week_end,
        'weekly_exams': weekly_exams,
        'today_study_sessions': study_context,
        'study_date': study_date,
        'student_fee_records': student_fee_records,
        'student_fee_total': student_fee_total,
        'student_fee_paid': student_fee_paid,
        'student_fee_due': student_fee_due,
        'student_fee_up_to_date': (
            student_fee_current_monthly_fee > 0 and student_fee_current_due == 0
        ),
        'student_fee_current_has_charge': student_fee_current_monthly_fee > 0,
        'student_fee_current_month': current_fee_month,
        'student_fee_current_month_label': month_display_label(current_fee_month),
        'student_fee_current_record': student_fee_current_record,
        'student_fee_current_monthly_fee': student_fee_current_monthly_fee,
        'student_fee_current_paid': student_fee_current_paid,
        'student_fee_current_due': student_fee_current_due,
    })


def fee_receipt_response(record):
    outstanding_amount = sum(
        (
            fee_record.due_amount
            for fee_record in StudentFeeRecord.objects.filter(student=record.student)
        ),
        Decimal('0.00'),
    )
    logo_path, font_path = receipt_asset_paths(settings.BASE_DIR)
    receipt_pdf = build_fee_receipt(
        record,
        outstanding_amount,
        logo_path,
        font_path,
    )
    response = HttpResponse(receipt_pdf, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="receipt-{record.student_id}-{record.month}.pdf"'
    )
    response['Cache-Control'] = 'private, no-store'
    return response


@role_required('student')
def student_fee_receipt(request, month):
    try:
        parsed_month = datetime.strptime(month, '%Y-%m')
    except ValueError as exc:
        raise Http404('বেতনের মাসটি সঠিক নয়।') from exc
    if parsed_month.strftime('%Y-%m') != month:
        raise Http404('বেতনের মাসটি সঠিক নয়।')
    student = student_for_user(request.user)
    record = get_object_or_404(
        StudentFeeRecord.objects.select_related('student'),
        student=student,
        month=month,
        amount_paid__gt=0,
    )
    return fee_receipt_response(record)


@role_required('superadmin')
def admin_student_fee_receipt(request, student_id, month):
    try:
        parsed_month = datetime.strptime(month, '%Y-%m')
    except ValueError as exc:
        raise Http404('বেতনের মাসটি সঠিক নয়।') from exc
    if parsed_month.strftime('%Y-%m') != month:
        raise Http404('বেতনের মাসটি সঠিক নয়।')
    record = get_object_or_404(
        StudentFeeRecord.objects.select_related('student'),
        student_id=student_id,
        student__is_active=True,
        month=month,
        amount_paid__gt=0,
    )
    return fee_receipt_response(record)


@role_required('student')
@require_POST
def update_class_session_progress(request, session_id):
    student = student_for_user(request.user)
    session = get_object_or_404(
        ClassSession,
        pk=session_id,
        date__lte=timezone.localdate(),
        year_group=student.year_group,
    )
    form = ClassSessionProgressForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'তথ্য সংরক্ষণ করা যায়নি। সমস্যার বিবরণ ১৫০০ অক্ষরের মধ্যে লিখুন।')
        return redirect('student_dashboard')

    if timezone.now() >= class_session_submission_deadline(session):
        messages.error(request, 'এই ক্লাসের জমা দেওয়ার সময় শেষ হয়ে গেছে। পরে আবার জমা দেওয়া সম্ভব নয়।')
        return redirect(
            f"{reverse('student_dashboard')}?study_date={session.date.isoformat()}#todays-study"
        )

    ClassSessionProgress.objects.update_or_create(
        session=session,
        student=student,
        defaults={
            'is_completed': form.cleaned_data['is_completed'],
            'problem_description': form.cleaned_data['problem_description'].strip(),
        },
    )
    messages.success(request, 'পড়ার অগ্রগতি সংরক্ষণ করা হয়েছে।')
    if session.date == timezone.localdate():
        return redirect('student_dashboard')
    return redirect(
        f"{reverse('student_dashboard')}?study_date={session.date.isoformat()}#todays-study"
    )


@role_required('student')
def student_feedback(request):
    student = student_for_user(request.user)
    if request.method == 'POST':
        form = StudentFeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.student = student
            feedback.save()
            messages.success(request, 'তোমার মতামতটি সুপার অ্যাডমিনের কাছে পাঠানো হয়েছে।')
            return redirect('student_feedback')
    else:
        form = StudentFeedbackForm()
    return render(request, 'portal/student_feedback.html', {
        'student': student,
        'form': form,
    })


@role_required('superadmin')
def admin_student_feedback(request):
    feedback_entries = StudentFeedback.objects.select_related('student').all()
    return render(request, 'portal/admin_student_feedback.html', {
        'feedback_entries': feedback_entries,
        'feedback_count': feedback_entries.count(),
    })


@role_required('student')
def student_routine(request):
    student = student_for_user(request.user)
    routines = routines_for_student(student)
    weekday_rows = build_weekday_rows(routines)
    context = {
        'student': student,
        'routines': routines,
        'weekday_rows': weekday_rows,
        'sessions': ClassSession.objects.filter(year_group=student.year_group).select_related('teacher')[:20],
    }
    return render(request, 'portal/student_routine.html', context)


@role_required('student')
def student_books(request):
    return redirect(f"{reverse('student_materials')}?kind=pdf")


def build_weekday_rows(routines):
    routines_by_weekday = {}
    for routine in routines:
        routines_by_weekday.setdefault(routine.weekday, []).append(routine)
    return [
        {
            'weekday': weekday,
            'label': label,
            'first_class': routines_by_weekday.get(weekday, [None])[0],
            'later_classes': routines_by_weekday.get(weekday, [])[1:],
            'classes': routines_by_weekday.get(weekday, []),
        }
        for weekday, label in Routine.Weekday.choices
    ]


def build_year_routine_groups(routines):
    routine_years = [
        ('first', '১ম বর্ষ'),
        ('second', '২য় বর্ষ'),
    ]
    weekdays = (
        (Routine.Weekday.MONDAY, Routine.Weekday.MONDAY.label),
        (Routine.Weekday.TUESDAY, Routine.Weekday.TUESDAY.label),
        (Routine.Weekday.WEDNESDAY, Routine.Weekday.WEDNESDAY.label),
        (Routine.Weekday.THURSDAY, Routine.Weekday.THURSDAY.label),
        (Routine.Weekday.FRIDAY, Routine.Weekday.FRIDAY.label),
        (Routine.Weekday.SATURDAY, Routine.Weekday.SATURDAY.label),
        (Routine.Weekday.SUNDAY, Routine.Weekday.SUNDAY.label),
    )
    routines_by_year = {key: [] for key, _ in routine_years}
    for routine in routines:
        routines_by_year[routine.year_group].append(routine)

    return [
        {
            'key': key,
            'label': label,
            'class_count': len(routines_by_year[key]),
            'days': [
                {
                    'weekday': weekday,
                    'label': label,
                    'classes': sorted(
                        (
                            routine for routine in routines_by_year[key]
                            if routine.weekday == weekday
                        ),
                        key=lambda routine: (routine.start_time, routine.pk),
                    ),
                }
                for weekday, label in weekdays
            ],
        }
        for key, label in routine_years
    ]


@role_required('student')
def student_exams(request):
    student = student_for_user(request.user)
    exams = Exam.objects.filter(year_group=student.year_group).order_by('exam_date', 'created_at')
    results = {
        result.exam_id: result
        for result in ExamResult.objects.filter(student=student, exam__in=exams).select_related('exam')
    }
    return render(request, 'portal/student_exams.html', {
        'student': student,
        'today': timezone.localdate(),
        'exams': exams,
        'results': results,
    })


@role_required('student')
def student_materials(request):
    student = student_for_user(request.user)
    selected_kind = request.GET.get('kind', LearningMaterial.Kind.SHEET)
    if selected_kind not in (*LearningMaterial.Kind.values, 'pdf'):
        selected_kind = LearningMaterial.Kind.SHEET
    book_sections = [
        {
            **section,
            'chapters': [
                (chapter, url, mobile_pdf_preview_url(url))
                for chapter, url in section['chapters']
            ],
        }
        for section in STUDENT_BOOK_SECTIONS
    ] if selected_kind == 'pdf' else []
    material_groups = {
        kind: LearningMaterial.objects.filter(
            Q(year_group='') | Q(year_group=student.year_group),
            kind=kind,
        ).order_by('subject', 'paper', 'chapter', '-created_at')
        for kind in LearningMaterial.Kind.values
    }
    return render(request, 'portal/student_materials.html', {
        'student': student,
        'sheet_materials': material_groups[LearningMaterial.Kind.SHEET],
        'book_materials': material_groups[LearningMaterial.Kind.BOOK],
        'important_materials': material_groups[LearningMaterial.Kind.IMPORTANT],
        'selected_kind': selected_kind,
        'material_kinds': LearningMaterial.Kind.choices,
        'is_books_page': selected_kind == 'pdf',
        'book_sections': book_sections,
        'book_count': (
            sum(len(section['chapters']) for section in STUDENT_BOOK_SECTIONS)
            if selected_kind == 'pdf'
            else 0
        ),
    })


@role_required('student')
def student_statistics(request):
    student = student_for_user(request.user)
    month, month_value = selected_month(request)
    month_start, next_month = month_bounds(month)
    today = timezone.localdate()
    period_end = min(next_month, today + timedelta(days=1)) if month.year == today.year and month.month == today.month else next_month
    attendance_records = Attendance.objects.filter(
        student=student, date__gte=month_start, date__lt=period_end,
    )
    attended = attendance_records.filter(status__in=[Attendance.Status.PRESENT, Attendance.Status.LATE]).count()
    absent = attendance_records.filter(status=Attendance.Status.ABSENT).count()
    total_class_days = attendance_records.count()
    missed = 0
    results = list(
        ExamResult.objects.filter(
            student=student, exam__exam_date__gte=month_start, exam__exam_date__lt=next_month,
        ).select_related('exam').order_by('-exam__exam_date')
    )
    percentages = [
        result.marks * Decimal(100) / result.exam.total_marks
        for result in results
        if result.exam.total_marks
    ]
    return render(request, 'portal/student_statistics.html', {
        'student': student,
        'month': month,
        'month_value': month_value,
        'month_label': date_format(month, 'F Y'),
        'attendance_rate': round(attended * 100 / total_class_days) if total_class_days else 0,
        'class_days': total_class_days,
        'attended_days': attended,
        'absent_days': absent,
        'unmarked_days': missed,
        'exam_count': len(results),
        'average_marks': round(sum(percentages) / len(percentages)) if percentages else 0,
        'results': results,
        'sessions': ClassSession.objects.filter(
            year_group=student.year_group, date__gte=month_start, date__lt=period_end,
        ).select_related('teacher'),
    })


@role_required('student')
def student_results(request):
    student = student_for_user(request.user)
    results = ExamResult.objects.filter(student=student).select_related('exam').order_by('-exam__exam_date')
    return render(request, 'portal/student_results.html', {
        'student': student,
        'results': results,
    })


@role_required('teacher', 'superadmin')
def class_management(request):
    is_superadmin = request.user.is_superuser
    editing_routine = None
    if is_superadmin and request.method == 'GET' and request.GET.get('edit_routine'):
        editing_routine = get_object_or_404(Routine, pk=request.GET['edit_routine'])
    routine_form = RoutineForm(instance=editing_routine, prefix='routine')
    session_form = ClassSessionForm(prefix='session', teacher=request.user)
    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        action = request.POST.get('action')
        if action == 'delete_routine':
            if not is_superadmin:
                raise PermissionDenied('রুটিন মুছতে পারবেন শুধু সুপার অ্যাডমিন।')
            routine = get_object_or_404(Routine, pk=request.POST.get('routine_id'))
            routine.delete()
            return redirect('class_management')
        if form_type not in {'routine', 'session'}:
            raise PermissionDenied('অনুরোধটি সঠিক নয়।')
        if form_type == 'routine' and not is_superadmin:
            raise PermissionDenied('রুটিন যোগ করার অনুমতি শুধু সুপার অ্যাডমিনের আছে।')
        if form_type == 'session' and is_superadmin:
            raise PermissionDenied('পরিচালিত ক্লাসের তথ্য শিক্ষক যোগ করতে পারবেন।')
        form_class = RoutineForm if form_type == 'routine' else ClassSessionForm
        if form_type == 'routine':
            editing_routine = get_object_or_404(
                Routine,
                pk=request.POST.get('routine_id'),
            ) if request.POST.get('routine_id') else None
        form = form_class(
            request.POST,
            instance=editing_routine,
            prefix=form_type,
        ) if form_type == 'routine' else form_class(
            request.POST,
            prefix=form_type,
            teacher=request.user,
        )
        if form.is_valid():
            record = form.save(commit=False)
            if form_type == 'session':
                record.teacher = request.user
            record.save()
            return redirect('class_management')
        if form_type == 'routine':
            routine_form = form
        else:
            session_form = form

    month, month_value = selected_month(request)
    month_start, next_month = month_bounds(month)
    routines = Routine.objects.all() if is_superadmin else Routine.objects.filter(teacher=request.user)
    has_class_today = Routine.objects.filter(
        teacher=request.user,
        weekday=timezone.localdate().weekday(),
    ).exists()
    sessions = ClassSession.objects.all() if is_superadmin else ClassSession.objects.filter(teacher=request.user)
    exams = Exam.objects.filter(
        exam_date__gte=month_start, exam_date__lt=next_month,
    ) if is_superadmin else Exam.objects.filter(
        created_by=request.user, exam_date__gte=month_start, exam_date__lt=next_month,
    )
    monthly_sessions = sessions.filter(date__gte=month_start, date__lt=next_month)
    monthly_exam_chapters = list(
        exams.values('chapter', 'paper', 'year_group')
        .annotate(total=Count('id'))
        .order_by('year_group', 'chapter')
    )
    for item in monthly_exam_chapters:
        item['class_name'] = BATCH_LABELS[item['year_group']]
    routines = routines.select_related('teacher').order_by('weekday', 'start_time')
    return render(request, 'portal/class_management.html', {
        'routine_form': routine_form,
        'session_form': session_form,
        'has_class_today': has_class_today,
        'is_superadmin': is_superadmin,
        'teacher_routine_version': (
            get_teacher_routine_version(request.user) if not is_superadmin else ''
        ),
        'routines': routines,
        'weekday_rows': build_weekday_rows(routines),
        'year_routine_groups': build_year_routine_groups(routines) if is_superadmin else [],
        'editing_routine': editing_routine,
        'sessions': sessions.select_related('teacher')[:30],
        'month': month,
        'month_value': month_value,
        'monthly_sessions': monthly_sessions.count(),
        'monthly_exams': exams.count(),
        'monthly_exam_chapters': monthly_exam_chapters,
    })


@role_required('teacher')
@never_cache
def teacher_routine_version(request):
    return JsonResponse({
        'version': get_teacher_routine_version(request.user),
    })


@role_required('teacher', 'superadmin')
def teacher_materials(request):
    form = LearningMaterialForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        material = form.save(commit=False)
        material.uploaded_by = request.user
        material.save()
        return redirect('teacher_materials')
    materials = LearningMaterial.objects.select_related('uploaded_by')
    if get_role(request.user) == 'teacher':
        materials = materials.filter(uploaded_by=request.user)
    return render(request, 'portal/teacher_materials.html', {
        'form': form,
        'materials': materials,
    })


@role_required('student', 'teacher', 'superadmin')
def download_material(request, material_id):
    material = get_object_or_404(LearningMaterial, pk=material_id)
    role = get_role(request.user)
    if role == 'teacher' and material.uploaded_by_id != request.user.pk:
        raise PermissionDenied
    if role == 'student':
        student = student_for_user(request.user)
        if material.year_group and material.year_group != student.year_group:
            raise PermissionDenied
    if not material.file:
        if material.external_url:
            return redirect(material.external_url)
        raise Http404('এই শিক্ষাসামগ্রীর কোনো ফাইল বা লিংক নেই।')
    if not material.file.storage.exists(material.file.name):
        raise Http404('ফাইলটি পাওয়া যায়নি।')
    return FileResponse(
        material.file.open('rb'),
        as_attachment=True,
        filename=Path(material.file.name).name,
    )


@role_required('superadmin')
def admin_dashboard(request):
    ensure_teacher_profiles()
    current_month = timezone.localdate().strftime('%Y-%m')
    study_report_date = get_study_report_date(request.GET.get('study_date', '').strip())
    today_study_sessions, study_report_page = paginate_study_progress(
        build_class_session_progress(
            ClassSession.objects.filter(date=study_report_date).order_by(
                'teacher__first_name',
                'teacher__username',
                'year_group',
                'subject',
            )
        ),
        request.GET.get('study_page', 1),
    )
    fee_paid_students = 0
    fee_unpaid_students = 0
    fee_unrecorded_students = 0
    fee_total_earned = Decimal('0.00')
    fee_total_collected = Decimal('0.00')
    fee_total_due = Decimal('0.00')
    for student in Student.objects.filter(is_active=True).prefetch_related('fee_records'):
        records = list(student.fee_records.all())
        current_record = next((record for record in records if record.month == current_month), None)
        monthly_fee = monthly_fee_for_month(records, current_month)
        amount_paid = current_record.amount_paid if current_record else Decimal('0.00')
        due_amount = max(monthly_fee - amount_paid, Decimal('0.00'))
        fee_total_earned += monthly_fee
        fee_total_collected += amount_paid
        fee_total_due += due_amount
        if monthly_fee <= 0:
            fee_unrecorded_students += 1
        elif due_amount:
            fee_unpaid_students += 1
        else:
            fee_paid_students += 1
    return render(request, 'portal/admin_dashboard.html', {
        'teacher_count': get_user_model().objects.filter(profile__role=UserProfile.Role.TEACHER).count(),
        'student_count': Student.objects.filter(is_active=True).count(),
        'class_count': ClassSession.objects.count(),
        'exam_count': Exam.objects.count(),
        'pending_teacher_attendance': TeacherAttendance.objects.filter(
            status=TeacherAttendance.Status.PENDING,
        ).count(),
        'student_feedback_count': StudentFeedback.objects.count(),
        'today_study_sessions': today_study_sessions,
        'today_study_year_groups': group_class_session_progress(today_study_sessions),
        'study_report_date': study_report_date,
        'study_report_page': study_report_page,
        'fee_current_month': current_month,
        'fee_current_month_label': month_display_label(current_month),
        'recent_teachers': get_user_model().objects.filter(
            profile__role=UserProfile.Role.TEACHER,
        ).order_by('first_name', 'username')[:6],
        'fee_paid_students': fee_paid_students,
        'fee_unpaid_students': fee_unpaid_students,
        'fee_unrecorded_students': fee_unrecorded_students,
        'fee_total_earned': fee_total_earned,
        'fee_total_collected': fee_total_collected,
        'fee_total_due': fee_total_due,
    })


@role_required('superadmin')
def admin_student_accounts(request):
    ensure_teacher_profiles()
    fee_form_instance = None
    if request.method == 'POST' and 'student_fee_submit' in request.POST:
        try:
            student_pk = Student._meta.pk.to_python(request.POST.get('student'))
            month = request.POST.get('month', '').strip()
            datetime.strptime(month, '%Y-%m')
        except (TypeError, ValueError, ValidationError):
            pass
        else:
            fee_form_instance = StudentFeeRecord.objects.filter(
                student_id=student_pk,
                month=month,
            ).first()
    fee_form = StudentFeeRecordForm(
        request.POST if request.method == 'POST' and 'student_fee_submit' in request.POST else None,
        instance=fee_form_instance,
    )
    current_month = timezone.localdate().strftime('%Y-%m')
    if request.method == 'POST' and 'student_fee_submit' in request.POST:
        if fee_form.is_valid():
            student = fee_form.cleaned_data['student']
            month = fee_form.cleaned_data['month']
            record, _ = StudentFeeRecord.objects.get_or_create(student=student, month=month)
            record.monthly_fee = fee_form.cleaned_data['monthly_fee']
            record.amount_paid = fee_form.cleaned_data['amount_paid']
            record.note = fee_form.cleaned_data['note']
            record.recorded_by = request.user
            record.save()
            messages.success(request, 'বেতন রেকর্ড সংরক্ষিত হয়েছে।')
            return redirect('admin_student_accounts')
    inline_fee_form = None
    inline_student_id = None
    if request.method == 'POST' and 'student_monthly_fee_submit' in request.POST:
        inline_student_id = request.POST.get('student_id')
        inline_student = get_object_or_404(
            Student,
            pk=inline_student_id,
            is_active=True,
        )
        inline_fee_form = StudentMonthlyFeeForm(
            request.POST,
            prefix=f'monthly_fee_{inline_student_id}',
        )
        if inline_fee_form.is_valid():
            monthly_record, _ = StudentFeeRecord.objects.get_or_create(
                student=inline_student,
                month=current_month,
                defaults={'recorded_by': request.user},
            )
            monthly_record.monthly_fee = inline_fee_form.cleaned_data['monthly_fee']
            monthly_record.recorded_by = request.user
            monthly_record.save(update_fields=['monthly_fee', 'recorded_by', 'updated_at'])
            messages.success(
                request,
                f'{inline_student.name}-এর {current_month} মাসের ধার্য বেতন সংরক্ষণ হয়েছে।',
            )
            return redirect('admin_student_accounts')

    selected_month_date, selected_month_value = selected_month(request)
    selected_month_label = month_display_label(selected_month_value)
    current_month_label = month_display_label(current_month)
    overall_fee_totals = StudentFeeRecord.objects.filter(
        student__is_active=True,
    ).aggregate(
        total_fee=Sum('monthly_fee'),
        total_paid=Sum('amount_paid'),
        total_due=Sum(
            Case(
                When(
                    amount_paid__lt=F('monthly_fee'),
                    then=F('monthly_fee') - F('amount_paid'),
                ),
                default=Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        ),
    )
    student_fee_rows = []
    current_month_estimate = Decimal('0.00')
    current_month_due_estimate = Decimal('0.00')
    current_month_fee_set_count = 0
    selected_month_total_fee = Decimal('0.00')
    selected_month_total_paid = Decimal('0.00')
    selected_month_total_due = Decimal('0.00')
    selected_month_fee_set_count = 0
    selected_month_paid_students = 0
    selected_month_due_students = 0
    for student in Student.objects.filter(is_active=True).prefetch_related('fee_records').order_by('name'):
        records = sorted(student.fee_records.all(), key=lambda record: record.month, reverse=True)
        for record in records:
            record.month_label = month_display_label(record.month)
        total_fee = sum((record.monthly_fee for record in records), Decimal('0.00'))
        total_paid = sum((record.amount_paid for record in records), Decimal('0.00'))
        total_due = sum((record.due_amount for record in records), Decimal('0.00'))
        current_summary = fee_summary_for_month(records, current_month, carry_forward=True)
        current_record = current_summary['record']
        selected_summary = fee_summary_for_month(
            records,
            selected_month_value,
            carry_forward=selected_month_value == current_month,
        )
        selected_record = selected_summary['record']
        last_paid_record = next(
            (record for record in records if record.amount_paid > 0),
            None,
        )
        current_monthly_fee = current_summary['monthly_fee']
        current_month_paid = current_summary['amount_paid']
        current_month_due = current_summary['due_amount']
        if current_monthly_fee > 0:
            current_month_estimate += current_monthly_fee
            current_month_due_estimate += current_month_due
            current_month_fee_set_count += 1
        selected_month_fee = selected_summary['monthly_fee']
        selected_month_paid = selected_summary['amount_paid']
        selected_month_due = selected_summary['due_amount']
        selected_month_has_fee = selected_month_fee > 0
        if selected_month_has_fee:
            selected_month_total_fee += selected_month_fee
            selected_month_total_paid += selected_month_paid
            selected_month_total_due += selected_month_due
            selected_month_fee_set_count += 1
            if selected_month_due:
                selected_month_due_students += 1
            else:
                selected_month_paid_students += 1
        row_monthly_fee_form = (
            inline_fee_form
            if inline_student_id and str(student.pk) == str(inline_student_id)
            else StudentMonthlyFeeForm(
                initial=(
                    {'monthly_fee': current_monthly_fee}
                    if current_record or current_monthly_fee > 0
                    else None
                ),
                prefix=f'monthly_fee_{student.pk}',
            )
        )
        student_fee_rows.append({
            'student': student,
            'records': records,
            'current_record': current_record,
            'selected_record': selected_record,
            'last_paid_record': last_paid_record,
            'selected_month_has_fee': selected_month_has_fee,
            'selected_month_fee': selected_month_fee,
            'selected_month_paid': selected_month_paid,
            'selected_month_due': selected_month_due,
            'current_month_paid': current_month_paid,
            'current_month_due': current_month_due,
            'current_month_fee': current_monthly_fee,
            'monthly_fee_form': row_monthly_fee_form,
            'total_fee': total_fee,
            'total_paid': total_paid,
            'total_due': total_due,
            'is_up_to_date': current_monthly_fee > 0 and current_month_due == 0,
        })
    fee_due_only = request.GET.get('fee_due_only') == '1'
    fee_order = request.GET.get('fee_order', 'due_desc')
    fee_status = request.GET.get('fee_status', 'all')
    if fee_status not in {'all', 'paid', 'due', 'unrecorded'}:
        fee_status = 'all'
    filtered_rows = [
        row for row in student_fee_rows
        if (
            fee_status == 'all'
            or (
                fee_status == 'paid'
                and row['selected_record']
                and row['selected_month_has_fee']
                and row['selected_month_due'] == 0
            )
            or (fee_status == 'due' and row['selected_month_due'] > 0)
            or (
                fee_status == 'unrecorded'
                and not row['selected_month_has_fee']
            )
        )
        and (
            not fee_due_only
            or row['selected_month_due'] > 0
            or not row['selected_record']
        )
    ]
    if fee_order == 'due_asc':
        filtered_rows.sort(key=lambda row: row['selected_month_due'])
    elif fee_order == 'payment_desc':
        filtered_rows.sort(key=lambda row: row['selected_month_paid'], reverse=True)
    elif fee_order == 'name':
        filtered_rows.sort(key=lambda row: row['student'].name.casefold())
    else:
        filtered_rows.sort(key=lambda row: row['selected_month_due'], reverse=True)
    student_fee_page = Paginator(filtered_rows, 10).get_page(request.GET.get('page', 1))
    return render(request, 'portal/admin_student_accounts.html', {
        'student_fee_form': fee_form,
        'student_fee_page': student_fee_page,
        'fee_due_only': fee_due_only,
        'fee_order': fee_order,
        'fee_status': fee_status,
        'current_month': current_month,
        'current_month_label': current_month_label,
        'selected_month': selected_month_value,
        'selected_month_label': selected_month_label,
        'selected_month_date': selected_month_date,
        'selected_month_total_fee': selected_month_total_fee,
        'selected_month_total_paid': selected_month_total_paid,
        'selected_month_total_due': selected_month_total_due,
        'selected_month_paid_students': selected_month_paid_students,
        'selected_month_due_students': selected_month_due_students,
        'selected_month_unrecorded_students': (
            len(student_fee_rows) - selected_month_fee_set_count
        ),
        'overall_total_fee': overall_fee_totals['total_fee'] or Decimal('0.00'),
        'overall_total_paid': overall_fee_totals['total_paid'] or Decimal('0.00'),
        'overall_total_due': overall_fee_totals['total_due'] or Decimal('0.00'),
        'current_month_estimate': current_month_estimate,
        'current_month_due_estimate': current_month_due_estimate,
        'current_month_fee_set_count': current_month_fee_set_count,
        'active_student_count': len(student_fee_rows),
    })


@role_required('teacher')
@require_POST
def join_support_session(request):
    SupportSessionAttendance.objects.get_or_create(
        teacher=request.user,
        date=timezone.localdate(),
    )
    return redirect(SUPPORT_SESSION_URL)


@role_required('teacher')
@require_POST
def request_teacher_attendance(request, routine_id):
    today = timezone.localdate()
    routine = get_object_or_404(
        Routine,
        pk=routine_id,
        teacher=request.user,
        weekday=today.weekday(),
    )
    _, created = TeacherAttendance.objects.get_or_create(
        teacher=request.user,
        date=today,
        defaults={
            'routine': routine,
            'status': TeacherAttendance.Status.PENDING,
        },
    )
    notice = 'pending' if created else 'already-recorded'
    return redirect(f"{reverse('teacher_dashboard')}?attendance={notice}#today-classes")


@role_required('superadmin')
def admin_teacher_attendance(request):
    ensure_teacher_profiles()
    selected_date = timezone.localdate()
    raw_date = request.GET.get('date') or request.POST.get('date')
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            selected_date = timezone.localdate()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action in {'approve', 'reject'}:
            record = get_object_or_404(
                TeacherAttendance,
                pk=request.POST.get('record_id'),
                status=TeacherAttendance.Status.PENDING,
            )
            record.status = (
                TeacherAttendance.Status.APPROVED
                if action == 'approve'
                else TeacherAttendance.Status.REJECTED
            )
            record.reviewed_by = request.user
            record.reviewed_at = timezone.now()
            record.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        elif action == 'mark':
            teacher = get_object_or_404(
                get_user_model().objects.filter(profile__role=UserProfile.Role.TEACHER),
                pk=request.POST.get('teacher_id'),
            )
            status = request.POST.get('status')
            if status not in {'present', 'absent'}:
                raise PermissionDenied('শিক্ষকের উপস্থিতির সঠিক অবস্থা নির্বাচন করুন।')
            record, created = TeacherAttendance.objects.get_or_create(
                teacher=teacher,
                date=selected_date,
                defaults={
                    'status': (
                        TeacherAttendance.Status.APPROVED
                        if status == 'present'
                        else TeacherAttendance.Status.ABSENT
                    ),
                    'reviewed_by': request.user,
                    'reviewed_at': timezone.now(),
                },
            )
            if not created:
                record.status = (
                    TeacherAttendance.Status.APPROVED
                    if status == 'present'
                    else TeacherAttendance.Status.ABSENT
                )
                record.reviewed_by = request.user
                record.reviewed_at = timezone.now()
                record.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        else:
            raise PermissionDenied('অনুরোধটি সঠিক নয়।')
        return redirect(f"{reverse('admin_teacher_attendance')}?date={selected_date.isoformat()}")

    teachers = get_user_model().objects.filter(
        profile__role=UserProfile.Role.TEACHER,
    ).select_related('profile').order_by('first_name', 'username')
    attendance_by_teacher = {
        item.teacher_id: item
        for item in TeacherAttendance.objects.filter(date=selected_date).select_related('routine')
    }
    return render(request, 'portal/admin_teacher_attendance.html', {
        'teachers': teachers,
        'selected_date': selected_date,
        'attendance_by_teacher': attendance_by_teacher,
        'pending_requests': TeacherAttendance.objects.filter(
            status=TeacherAttendance.Status.PENDING,
        ).select_related('teacher', 'routine').order_by('date', 'teacher__first_name'),
        'approved_count': TeacherAttendance.objects.filter(
            date=selected_date,
            status=TeacherAttendance.Status.APPROVED,
        ).count(),
        'pending_count': TeacherAttendance.objects.filter(
            status=TeacherAttendance.Status.PENDING,
        ).count(),
    })


@role_required('superadmin')
def admin_teachers(request):
    User = get_user_model()
    ensure_teacher_profiles()

    form = TeacherForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            teacher = User.objects.create_user(
                username=data['username'],
                password=data['password'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                email=data['email'],
            )
            UserProfile.objects.create(
                user=teacher,
                role=UserProfile.Role.TEACHER,
                phone=data['phone'],
            )
        return redirect('admin_teachers')

    month, month_value = selected_month(request)
    month_start, next_month = month_bounds(month)
    teacher_rows = []
    teachers = User.objects.filter(profile__role=UserProfile.Role.TEACHER).select_related('profile').order_by(
        'first_name', 'last_name', 'username',
    )
    support_session_teachers = teachers.annotate(
        support_session_days=Count('support_session_attendances', distinct=True),
        last_support_session_date=Max('support_session_attendances__date'),
        support_session_joined_today=Count(
            'support_session_attendances',
            filter=Q(support_session_attendances__date=timezone.localdate()),
            distinct=True,
        ),
    ).order_by('-support_session_days', 'first_name', 'username')
    for teacher in teachers:
        sessions = ClassSession.objects.filter(
            teacher=teacher, date__gte=month_start, date__lt=next_month,
        )
        exams = Exam.objects.filter(
            Q(created_by=teacher) | Q(assigned_teacher=teacher),
            exam_date__gte=month_start, exam_date__lt=next_month,
        ).distinct()
        session_chapters = list(
            sessions.values('year_group', 'subject', 'chapter').annotate(total=Count('id')).order_by('year_group', 'chapter')
        )
        exam_chapters = list(
            exams.values('year_group', 'paper', 'chapter').annotate(total=Count('id')).order_by('year_group', 'chapter')
        )
        class_rows = list(
            sessions.values('year_group').distinct(),
        )
        for item in class_rows:
            item['year_key'] = item['year_group']
            item['class_name'] = BATCH_LABELS[item['year_group']]
        for item in session_chapters + exam_chapters:
            item['year_key'] = item['year_group']
            item['class_name'] = BATCH_LABELS[item['year_group']]
        approved_attendance = list(TeacherAttendance.objects.filter(
            teacher=teacher,
            date__gte=month_start,
            date__lt=next_month,
            status=TeacherAttendance.Status.APPROVED,
        ).select_related('routine'))
        year_stats = []
        for year_key, label in YEAR_GROUPS:
            year_stats.append({
                'key': year_key,
                'label': label,
                'class_count': sum(item['year_key'] == year_key for item in class_rows),
                'session_count': sum(
                    item['total'] for item in session_chapters if item['year_key'] == year_key
                ),
                'exam_count': sum(
                    item['total'] for item in exam_chapters if item['year_key'] == year_key
                ),
                'attendance_count': sum(
                    record.routine is not None and record.routine.year_group == year_key
                    for record in approved_attendance
                ),
            })
        teacher_rows.append({
            'teacher': teacher,
            'phone': teacher.profile.phone,
            'class_count': sessions.count(),
            'exam_count': exams.count(),
            'attendance_count': TeacherAttendance.objects.filter(
                teacher=teacher,
                date__gte=month_start,
                date__lt=next_month,
                status=TeacherAttendance.Status.APPROVED,
            ).count(),
            'classes': class_rows,
            'session_chapters': session_chapters,
            'exam_chapters': exam_chapters,
            'year_stats': year_stats,
        })
    return render(request, 'portal/admin_teachers.html', {
        'form': form,
        'teachers': teacher_rows,
        'support_session_teachers': support_session_teachers,
        'support_session_total_joins': SupportSessionAttendance.objects.count(),
        'support_session_today_joins': SupportSessionAttendance.objects.filter(
            date=timezone.localdate(),
        ).count(),
        'year_groups': YEAR_GROUPS,
        'month': month,
        'month_value': month_value,
        'month_label': date_format(month, 'F Y'),
    })


@role_required('superadmin')
def admin_teacher_edit(request, teacher_id):
    User = get_user_model()
    teacher = get_object_or_404(
        User.objects.filter(profile__role=UserProfile.Role.TEACHER).select_related('profile'),
        pk=teacher_id,
    )
    form = TeacherUpdateForm(request.POST or None, teacher=teacher)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            teacher.first_name = data['first_name']
            teacher.last_name = data['last_name']
            teacher.username = data['username']
            teacher.email = data['email']
            if data['password']:
                teacher.set_password(data['password'])
            teacher.save()
            teacher.profile.phone = data['phone']
            teacher.profile.save(update_fields=['phone'])
        return redirect('admin_teachers')
    return render(request, 'portal/admin_teacher_edit.html', {
        'form': form,
        'teacher': teacher,
    })


@require_POST
@role_required('superadmin')
def admin_teacher_delete(request, teacher_id):
    User = get_user_model()
    teacher = get_object_or_404(
        User.objects.filter(profile__role=UserProfile.Role.TEACHER),
        pk=teacher_id,
    )
    teacher.delete()
    return redirect('admin_teachers')


@require_POST
@role_required('superadmin')
def delete_material(request, material_id):
    material = get_object_or_404(LearningMaterial, pk=material_id)
    if material.file:
        material.file.delete(save=False)
    material.delete()
    return redirect('teacher_materials')


def ensure_teacher_profiles():
    User = get_user_model()
    for user in User.objects.filter(is_superuser=False, profile__isnull=True).iterator():
        UserProfile.objects.get_or_create(user=user, defaults={'role': UserProfile.Role.TEACHER})
