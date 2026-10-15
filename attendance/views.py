from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from portal.access import role_required
from portal.year_groups import BATCH_CHOICES
from students.models import Student
from .models import (
    Attendance,
    AttendanceSMSBatch,
    AttendanceSMSNotification,
    AttendanceSMSSettings,
    AttendanceWhatsAppNotification,
)
from .sms import (
    SMSDeliveryError,
    get_account_balance,
    send_queued_notifications as send_queued_sms_notifications,
)
from .whatsapp import send_queued_notifications
from exams.models import ExamResultSMSNotification


def _get_sms_settings():
    sms_settings, _ = AttendanceSMSSettings.objects.get_or_create(pk=1)
    return sms_settings


def _is_ajax_request(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


@require_POST
@role_required('superadmin')
def sms_balance_api(request):
    try:
        balance = get_account_balance()
    except SMSDeliveryError as error:
        return JsonResponse({'error': str(error)}, status=502)
    return JsonResponse({'balance': format(balance, 'f')})


@require_POST
@role_required('superadmin')
def sms_state_api(request):
    enabled_value = request.POST.get('enabled')
    if enabled_value not in ('on', 'off'):
        return JsonResponse({'error': 'SMS state নির্বাচনটি সঠিক নয়।'}, status=400)
    sms_settings = _get_sms_settings()
    sms_settings.enabled = enabled_value == 'on'
    sms_settings.updated_by = request.user
    sms_settings.save(update_fields=['enabled', 'updated_by', 'updated_at'])
    state_text = 'চালু' if sms_settings.enabled else 'বন্ধ'
    return JsonResponse({
        'enabled': sms_settings.enabled,
        'message': f'SMS System {state_text} করা হয়েছে।',
    })


@role_required('superadmin')
def attendance_list(request):
    raw_date = request.GET.get('date') or request.POST.get('date')
    try:
        selected_date = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        selected_date = timezone.localdate()
        date_error = 'সঠিক তারিখ নির্বাচন করুন।'
    else:
        date_error = ''
    notification_method = request.POST.get('notification_method', 'sms')
    notification_error = ''
    sms_balance = None
    balance_error = ''
    sms_enabled = _get_sms_settings().enabled

    students = list(Student.objects.filter(is_active=True))
    students_by_year = {
        year_key: [student for student in students if student.year_group == year_key]
        for year_key, _ in BATCH_CHOICES
    }
    existing = {
        record.student_id: record
        for record in Attendance.objects.filter(date=selected_date, student__in=students)
    }
    sms_sent_attendance_ids = {
        notification.attendance.student_id
        for notification in AttendanceSMSNotification.objects.filter(
            attendance__date=selected_date,
            state=AttendanceSMSNotification.Status.SENT,
        ).select_related('attendance')
        if notification.attendance.status == notification.attendance_status
    }
    if request.method == 'POST' and not date_error:
        if request.POST.get('action') == 'check_sms_balance':
            try:
                sms_balance = get_account_balance()
            except SMSDeliveryError as error:
                balance_error = str(error)
            if _is_ajax_request(request):
                if balance_error:
                    return JsonResponse({'error': balance_error}, status=502)
                return JsonResponse({'balance': format(sms_balance, 'f')})
        elif notification_method not in ('whatsapp', 'sms'):
            notification_error = 'WhatsApp অথবা SMS—একটি নোটিফিকেশন মাধ্যম নির্বাচন করুন।'
        else:
            records = []
            notification_ids = []
            with transaction.atomic():
                for student in students:
                    status = request.POST.get(f'status_{student.pk}')
                    if status not in Attendance.Status.values:
                        continue
                    record, _ = Attendance.objects.update_or_create(
                        student=student,
                        date=selected_date,
                        defaults={'status': status, 'marked_by': request.user},
                    )
                    records.append(record)
                    superseded_states = [
                        AttendanceWhatsAppNotification.Status.PENDING,
                        AttendanceWhatsAppNotification.Status.FAILED,
                    ]
                    AttendanceWhatsAppNotification.objects.filter(
                        attendance=record,
                        attendance_status__in=Attendance.Status.values,
                        state__in=superseded_states,
                    ).exclude(attendance_status=status).update(
                        state=AttendanceWhatsAppNotification.Status.CANCELLED,
                        updated_at=timezone.now(),
                    )
                    AttendanceSMSNotification.objects.filter(
                        attendance=record,
                        attendance_status__in=Attendance.Status.values,
                        state__in=[
                            AttendanceSMSNotification.Status.PENDING,
                            AttendanceSMSNotification.Status.FAILED,
                        ],
                    ).exclude(attendance_status=status).update(
                        state=AttendanceSMSNotification.Status.CANCELLED,
                        updated_at=timezone.now(),
                    )
                    if notification_method == 'sms' and sms_enabled:
                        notification, _ = AttendanceSMSNotification.objects.get_or_create(
                            attendance=record,
                            attendance_status=status,
                            defaults={
                                'recipient_phone': student.guardian_phone or '',
                            },
                        )
                        notification_ids.append(notification.pk)
                    elif status in (Attendance.Status.PRESENT, Attendance.Status.ABSENT):
                        notification, _ = AttendanceWhatsAppNotification.objects.get_or_create(
                            attendance=record,
                            attendance_status=status,
                        )
                        notification_ids.append(notification.pk)
            if records:
                if notification_method == 'sms':
                    if not sms_enabled:
                        AttendanceSMSBatch.objects.create(
                            attendance_date=selected_date,
                            sms_enabled=False,
                            estimated_cost=Decimal('0.00'),
                            created_by=request.user,
                        )
                        messages.warning(
                            request,
                            'উপস্থিতি সংরক্ষণ হয়েছে, কিন্তু SMS System বন্ধ থাকায় কোনো SMS পাঠানো হয়নি।',
                        )
                        return redirect(f'{request.path}?date={selected_date.isoformat()}&saved=1')
                    can_send_sms = AttendanceSMSNotification.objects.filter(
                        pk__in=notification_ids,
                    ).exclude(
                        state__in=[
                            AttendanceSMSNotification.Status.SENT,
                            AttendanceSMSNotification.Status.CANCELLED,
                        ],
                    ).exists()
                    balance_before = None
                    balance_before_error = ''
                    if can_send_sms:
                        try:
                            balance_before = get_account_balance()
                        except SMSDeliveryError as error:
                            balance_before_error = str(error)
                    sent_count, failed_count = send_queued_sms_notifications(notification_ids)
                    balance_after = None
                    balance_after_error = ''
                    if sent_count:
                        try:
                            balance_after = get_account_balance()
                        except SMSDeliveryError as error:
                            balance_after_error = str(error)
                    estimated_cost = None
                    if not sent_count and not failed_count:
                        estimated_cost = Decimal('0.00')
                    elif (
                        sent_count
                        and balance_before is not None
                        and balance_after is not None
                        and balance_before >= balance_after
                    ):
                        estimated_cost = (balance_before - balance_after).quantize(Decimal('0.01'))
                    AttendanceSMSBatch.objects.create(
                        attendance_date=selected_date,
                        accepted_count=sent_count,
                        failed_count=failed_count,
                        sms_enabled=True,
                        balance_before=balance_before,
                        balance_after=balance_after,
                        estimated_cost=estimated_cost,
                        created_by=request.user,
                    )
                    notifications = list(
                        AttendanceSMSNotification.objects.filter(pk__in=notification_ids)
                        .select_related('attendance__student')
                    )
                    summary = (
                        f'SMS নোটিফিকেশন: BulkSMSBD {sent_count}টি গ্রহণ করেছে, '
                        f'{failed_count}টি ব্যর্থ হয়েছে।'
                    )
                    if sent_count:
                        if balance_before is not None and balance_after is not None:
                            balance_change = balance_before - balance_after
                            if balance_change >= 0:
                                cost = format(balance_change.quantize(Decimal('0.01')), 'f')
                                current_balance = format(balance_after, 'f')
                                summary += (
                                    f' এই save-এ আনুমানিক SMS খরচ ৳{cost}; '
                                    f'পাঠানোর পর ব্যালেন্স ৳{current_balance}।'
                                )
                            else:
                                summary += (
                                    ' balance check-এর সময় account balance বেড়েছে, '
                                    'তাই এই save-এর SMS খরচ নির্ভুলভাবে মাপা যায়নি।'
                                )
                        else:
                            balance_reason = balance_after_error or balance_before_error
                            summary += (
                                ' এই save-এর SMS খরচ মাপা যায়নি'
                                f' ({balance_reason or "BulkSMSBD balance পাওয়া যায়নি"})।'
                            )
                else:
                    sent_count, failed_count = send_queued_notifications(notification_ids)
                    notifications = list(
                        AttendanceWhatsAppNotification.objects.filter(pk__in=notification_ids)
                        .select_related('attendance__student')
                    )
                    summary = (
                        f'WhatsApp নোটিফিকেশন: এইবার Meta {sent_count}টি গ্রহণ করেছে, '
                        f'{failed_count}টি ব্যর্থ হয়েছে।'
                    )
                accepted_count = sum(
                    notification.state == 'sent'
                    for notification in notifications
                )
                already_accepted_count = max(accepted_count - sent_count, 0)
                if (
                    notification_method == 'sms'
                    and sent_count == 0
                    and failed_count == 0
                    and already_accepted_count
                ):
                    summary += ' এই save-এ নতুন SMS পাঠানো হয়নি; SMS খরচ ৳0.00।'
                accepted_recipients = [
                    f'{notification.attendance.student.guardian_phone or "নম্বর নেই"} '
                    f'({notification.attendance.student.name})'
                    for notification in notifications
                    if notification.state == 'sent'
                ]
                failed_recipients = [
                    f'{notification.attendance.student.guardian_phone or "নম্বর নেই"} '
                    f'({notification.attendance.student.name}): '
                    f'{notification.last_error or "provider message গ্রহণ করেনি"}'
                    for notification in notifications
                    if notification.state == 'failed'
                ]
                late_skipped_count = (
                    sum(record.status == Attendance.Status.LATE for record in records)
                    if notification_method == 'whatsapp'
                    else 0
                )
                if already_accepted_count:
                    provider = 'BulkSMSBD' if notification_method == 'sms' else 'Meta'
                    summary += f' এর মধ্যে {already_accepted_count}টি আগেই {provider} গ্রহণ করেছিল।'
                if accepted_recipients:
                    summary += ' পাঠানো হয়েছে: ' + ', '.join(accepted_recipients) + '।'
                if failed_recipients:
                    summary += ' পাঠানো যায়নি: ' + '; '.join(failed_recipients) + '।'
                if late_skipped_count:
                    summary += (
                        f' {late_skipped_count}টি দেরির WhatsApp পাঠানো হয়নি—'
                        'এ জন্য approved late template configure করতে হবে।'
                    )
                if failed_count or late_skipped_count:
                    messages.warning(request, summary)
                else:
                    messages.info(request, summary)
                return redirect(f'{request.path}?date={selected_date.isoformat()}&saved=1')
            date_error = 'উপস্থিতি সংরক্ষণের জন্য অন্তত একজন শিক্ষার্থীর অবস্থা নির্বাচন করুন।'

    counts = {
        status: sum(record.status == status for record in existing.values())
        for status in Attendance.Status.values
    }
    return render(request, 'attendance/attendance_list.html', {
        'students': students,
        'year_groups': [
            {
                'key': year_key,
                'label': label,
                'students': students_by_year[year_key],
            }
            for year_key, label in BATCH_CHOICES
        ],
        'selected_date': selected_date,
        'existing': existing,
        'counts': counts,
        'date_error': date_error,
        'notification_error': notification_error,
        'notification_method': notification_method,
        'saved': request.GET.get('saved') == '1',
        'sms_balance': sms_balance,
        'balance_error': balance_error,
        'sms_sent_attendance_ids': sms_sent_attendance_ids,
        'sms_enabled': sms_enabled,
    })


@role_required('superadmin')
def sms_system(request):
    sms_settings = _get_sms_settings()
    balance = None
    balance_error = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'set_sms_state':
            enabled_value = request.POST.get('enabled')
            if enabled_value not in ('on', 'off'):
                messages.error(request, 'SMS state নির্বাচনটি সঠিক নয়।')
            else:
                sms_settings.enabled = enabled_value == 'on'
                sms_settings.updated_by = request.user
                sms_settings.save(update_fields=['enabled', 'updated_by', 'updated_at'])
                state_text = 'চালু' if sms_settings.enabled else 'বন্ধ'
                if _is_ajax_request(request):
                    return JsonResponse({
                        'enabled': sms_settings.enabled,
                        'message': f'SMS System {state_text} করা হয়েছে।',
                    })
                messages.success(request, f'SMS System {state_text} করা হয়েছে।')
            if _is_ajax_request(request):
                return JsonResponse({'error': 'SMS state নির্বাচনটি সঠিক নয়।'}, status=400)
            return redirect('sms_system')
        if action == 'check_sms_balance':
            try:
                balance = get_account_balance()
            except SMSDeliveryError as error:
                balance_error = str(error)
            if _is_ajax_request(request):
                if balance_error:
                    return JsonResponse({'error': balance_error}, status=502)
                return JsonResponse({'balance': format(balance, 'f')})

    notification_totals = AttendanceSMSNotification.objects.aggregate(
        sent=Count('pk', filter=Q(state=AttendanceSMSNotification.Status.SENT)),
        failed=Count('pk', filter=Q(state=AttendanceSMSNotification.Status.FAILED)),
        pending=Count('pk', filter=Q(state__in=[
            AttendanceSMSNotification.Status.PENDING,
            AttendanceSMSNotification.Status.SENDING,
        ])),
    )
    batch_totals = AttendanceSMSBatch.objects.aggregate(
        batches=Count('pk'),
        accepted=Sum('accepted_count'),
        estimated_cost=Sum('estimated_cost'),
    )
    exam_sms_totals = ExamResultSMSNotification.objects.aggregate(
        sent=Count('pk', filter=Q(state=ExamResultSMSNotification.Status.SENT)),
        failed=Count('pk', filter=Q(state=ExamResultSMSNotification.Status.FAILED)),
        pending=Count('pk', filter=Q(state__in=[
            ExamResultSMSNotification.Status.PENDING,
            ExamResultSMSNotification.Status.SENDING,
        ])),
    )
    notification_totals['sent'] += exam_sms_totals['sent']
    notification_totals['failed'] += exam_sms_totals['failed']
    notification_totals['pending'] += exam_sms_totals['pending']
    return render(request, 'attendance/sms_system.html', {
        'sms_settings': sms_settings,
        'notification_totals': notification_totals,
        'batch_totals': batch_totals,
        'balance': balance,
        'balance_error': balance_error,
    })


@role_required('superadmin')
def sms_report(request):
    sms_balance = None
    balance_error = ''
    if request.method == 'POST' and request.POST.get('action') == 'check_sms_balance':
        try:
            sms_balance = get_account_balance()
        except SMSDeliveryError as error:
            balance_error = str(error)
        if _is_ajax_request(request):
            if balance_error:
                return JsonResponse({'error': balance_error}, status=502)
            return JsonResponse({'balance': format(sms_balance, 'f')})

    notifications = AttendanceSMSNotification.objects.select_related(
        'attendance__student',
    ).order_by('-created_at', '-pk')
    exam_notifications = ExamResultSMSNotification.objects.select_related(
        'result__exam',
        'result__student',
    ).order_by('-created_at', '-pk')
    exam_recipient_totals = list(
        exam_notifications.values(
            'recipient_phone',
            'result__student__name',
        ).annotate(
            sent=Count('pk', filter=Q(state=ExamResultSMSNotification.Status.SENT)),
            failed=Count('pk', filter=Q(state=ExamResultSMSNotification.Status.FAILED)),
            total_attempts=Sum('attempts'),
        ).order_by('-sent', '-failed', 'result__student__name')
    )
    recipient_totals = list(
        notifications.values(
            'recipient_phone',
            'attendance__student__name',
        ).annotate(
            sent=Count('pk', filter=Q(state=AttendanceSMSNotification.Status.SENT)),
            failed=Count('pk', filter=Q(state=AttendanceSMSNotification.Status.FAILED)),
            total_attempts=Sum('attempts'),
        ).order_by('-sent', '-failed', 'attendance__student__name')
    )
    log_page = Paginator(notifications, 50).get_page(request.GET.get('page'))
    exam_log_page = Paginator(exam_notifications, 50).get_page(
        request.GET.get('exam_page'),
    )
    batch_page = Paginator(AttendanceSMSBatch.objects.all(), 25).get_page(
        request.GET.get('batch_page'),
    )
    return render(request, 'attendance/sms_report.html', {
        'recipient_totals': recipient_totals,
        'exam_recipient_totals': exam_recipient_totals,
        'log_page': log_page,
        'exam_log_page': exam_log_page,
        'batch_page': batch_page,
        'sms_balance': sms_balance,
        'balance_error': balance_error,
    })
