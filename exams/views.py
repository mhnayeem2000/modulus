from decimal import Decimal, InvalidOperation
from calendar import Calendar
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from attendance.models import AttendanceSMSSettings
from portal.access import role_required
from students.models import Student
from .forms import ExamForm
from .models import Exam, ExamResult, ExamResultSMSNotification
from .sms import send_result_sms_notifications


@role_required('teacher', 'superadmin')
def exam_list(request):
    form = ExamForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        exam = form.save(commit=False)
        exam.created_by = request.user
        exam.save()
        return redirect('exam_list')

    exams = Exam.objects.all() if request.user.is_superuser else Exam.objects.filter(created_by=request.user)
    exams = exams.annotate(result_count=Count('results')).order_by('-exam_date', '-created_at')
    page_obj = Paginator(exams, 8).get_page(request.GET.get('page'))

    today = timezone.localdate()
    try:
        year_text, month_text = request.GET.get('month', '').split('-', 1)
        calendar_month = date(int(year_text), int(month_text), 1)
    except (TypeError, ValueError):
        calendar_month = today.replace(day=1)
    next_month = (
        date(calendar_month.year + 1, 1, 1)
        if calendar_month.month == 12
        else date(calendar_month.year, calendar_month.month + 1, 1)
    )
    previous_month = calendar_month - timedelta(days=1)
    previous_month = previous_month.replace(day=1)
    calendar_exams = exams.filter(
        exam_date__gte=calendar_month,
        exam_date__lt=next_month,
    )
    exams_by_date = {}
    for exam in calendar_exams:
        exams_by_date.setdefault(exam.exam_date, []).append(exam)
    calendar_days = [
        [
            {
                'date': day,
                'in_month': day.month == calendar_month.month,
                'exams': exams_by_date.get(day, []),
            }
            for day in week
        ]
        for week in Calendar(firstweekday=0).monthdatescalendar(
            calendar_month.year,
            calendar_month.month,
        )
    ]
    return render(request, 'exams/exam_list.html', {
        'form': form,
        'exams': page_obj.object_list,
        'page_obj': page_obj,
        'calendar_month': calendar_month,
        'previous_month': previous_month,
        'next_month': next_month,
        'calendar_days': calendar_days,
        'calendar_weekdays': ['সোম', 'মঙ্গল', 'বুধ', 'বৃহঃ', 'শুক্র', 'শনি', 'রবি'],
    })


@role_required('teacher', 'superadmin')
def exam_edit(request, exam_id):
    exams = Exam.objects.all() if request.user.is_superuser else Exam.objects.filter(created_by=request.user)
    exam = get_object_or_404(exams, pk=exam_id)
    form = ExamForm(request.POST or None, instance=exam)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'পরীক্ষার বিষয়, পত্র ও অধ্যায়ের তথ্য সংরক্ষণ হয়েছে।')
        return redirect('exam_list')
    return render(request, 'exams/exam_edit.html', {
        'exam': exam,
        'form': form,
    })


@role_required('teacher', 'superadmin')
def exam_results(request, exam_id):
    exams = Exam.objects.all() if request.user.is_superuser else Exam.objects.filter(created_by=request.user)
    exam = get_object_or_404(exams, pk=exam_id)
    students = Student.objects.filter(is_active=True, year_group=exam.year_group)
    saved = request.GET.get('saved') == '1'
    error = ''
    if request.method == 'POST':
        submitted_marks = {}
        for student in students:
            raw_marks = request.POST.get(f'marks_{student.pk}', '').strip()
            if not raw_marks:
                continue
            try:
                marks = Decimal(raw_marks)
            except InvalidOperation:
                error = f'{student.name}-এর নম্বরটি সঠিক নয়।'
                break
            if not marks.is_finite() or marks < 0 or marks > exam.total_marks:
                error = f'{student.name}-এর নম্বর ০ থেকে {exam.total_marks}-এর মধ্যে হতে হবে।'
                break
            submitted_marks[student.pk] = marks

        if not error and submitted_marks:
            sms_settings, _ = AttendanceSMSSettings.objects.get_or_create(pk=1)
            notification_ids = []
            changed_results = 0
            with transaction.atomic():
                for student in students:
                    if student.pk in submitted_marks:
                        result, created = ExamResult.objects.get_or_create(
                            exam=exam,
                            student=student,
                            defaults={
                                'marks': submitted_marks[student.pk],
                                'recorded_by': request.user,
                            },
                        )
                        if not created:
                            result = ExamResult.objects.select_for_update().get(pk=result.pk)
                            changed = result.marks != submitted_marks[student.pk]
                            result.recorded_by = request.user
                            if changed:
                                result.marks = submitted_marks[student.pk]
                            result.save(update_fields=['marks', 'recorded_by', 'updated_at'])
                        else:
                            changed = True
                        if not changed:
                            if sms_settings.enabled:
                                failed_notification = result.sms_notifications.filter(
                                    marks=submitted_marks[student.pk],
                                    state=ExamResultSMSNotification.Status.FAILED,
                                ).order_by('-created_at').first()
                                if failed_notification:
                                    notification_ids.append(failed_notification.pk)
                            continue
                        changed_results += 1
                        if not sms_settings.enabled:
                            continue
                        notification = ExamResultSMSNotification.objects.create(
                            result=result,
                            marks=submitted_marks[student.pk],
                            recipient_phone=student.guardian_phone or '',
                        )
                        notification_ids.append(notification.pk)
            if notification_ids:
                sent_count, failed_count = send_result_sms_notifications(notification_ids)
                notification_rows = list(
                    ExamResultSMSNotification.objects.filter(pk__in=notification_ids)
                    .select_related('result__student')
                )
                sent_recipients = [
                    f'{item.recipient_phone} ({item.result.student.name})'
                    for item in notification_rows
                    if item.state == ExamResultSMSNotification.Status.SENT
                ]
                failed_recipients = [
                    f'{item.recipient_phone or "নম্বর নেই"} ({item.result.student.name}): '
                    f'{item.last_error}'
                    for item in notification_rows
                    if item.state == ExamResultSMSNotification.Status.FAILED
                ]
                summary = (
                    f'নম্বরের SMS: BulkSMSBD {sent_count}টি গ্রহণ করেছে, '
                    f'{failed_count}টি ব্যর্থ হয়েছে।'
                )
                if sent_recipients:
                    summary += ' পাঠানো হয়েছে: ' + ', '.join(sent_recipients) + '।'
                if failed_recipients:
                    summary += ' পাঠানো যায়নি: ' + '; '.join(failed_recipients) + '।'
                if failed_count:
                    messages.warning(request, summary)
                else:
                    messages.info(request, summary)
            elif changed_results and not sms_settings.enabled:
                messages.warning(
                    request,
                    'নম্বর সংরক্ষণ হয়েছে, কিন্তু SMS System বন্ধ থাকায় কোনো SMS পাঠানো হয়নি।',
                )
            return redirect(f"{reverse('exam_results', args=[exam.pk])}?saved=1")
        if not error:
            error = 'ফলাফল সংরক্ষণের জন্য অন্তত একজন শিক্ষার্থীর নম্বর দিন।'

    result_map = {result.student_id: result for result in exam.results.filter(student__in=students)}
    return render(request, 'exams/exam_results.html', {
        'exam': exam,
        'students': students,
        'result_map': result_map,
        'saved': saved,
        'error': error,
        'sms_enabled': AttendanceSMSSettings.objects.filter(pk=1).values_list(
            'enabled',
            flat=True,
        ).first() is not False,
    })
