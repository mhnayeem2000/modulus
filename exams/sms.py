import logging
import re

from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceSMSSettings
from attendance.sms import SMSDeliveryError, send_sms_message

from .models import ExamResultSMSNotification

logger = logging.getLogger(__name__)
MAX_RESULT_SMS_LENGTH = 160


def build_result_sms_message(notification):
    result = notification.result
    exam = result.exam
    student = result.student
    subject = exam.subject.strip()
    paper = exam.paper.strip()
    chapter = exam.chapter.strip()
    if not subject:
        raise SMSDeliveryError(
            'পরীক্ষার বিষয় নির্ধারিত নেই। পরীক্ষা সম্পাদনা করে বিষয় নির্বাচন করুন।'
        )
    if not paper:
        raise SMSDeliveryError(
            'পরীক্ষার পত্র নির্ধারিত নেই। পরীক্ষা সম্পাদনা করে পত্র নির্বাচন করুন।'
        )
    if not chapter:
        raise SMSDeliveryError(
            'পরীক্ষার অধ্যায় নির্ধারিত নেই। পরীক্ষা সম্পাদনা করে অধ্যায় নির্বাচন করুন।'
        )
    paper = re.sub(r'\s*(?:paper|পত্র)\s*$', '', paper, flags=re.IGNORECASE).strip()
    chapter = re.sub(
        r'\s*(?:chapter|অধ্যায়|অধ্যায়)\s*$',
        '',
        chapter,
        flags=re.IGNORECASE,
    ).strip()
    paper = f'{paper} Paper'
    chapter = f'{chapter} Chapter'
    score = f'{notification.marks.normalize():f}/{exam.total_marks}'
    results = exam.results.all()
    rank = 1 + results.filter(marks__gt=notification.marks).count()
    rank_out_of = results.count()
    notification.rank = rank
    notification.rank_out_of = rank_out_of
    fields = [
        student.name.strip() or 'শিক্ষার্থী',
        subject,
        paper,
        chapter,
    ]

    def compose():
        return (
            f'প্রিয় অভিভাবক, {fields[0]} {fields[1]} {fields[2]} {fields[3]} - এ '
            f'{score} পেয়েছে। Rank: {rank}/{rank_out_of}\n'
            '-Modulus Edu'
        )

    while len(compose()) > MAX_RESULT_SMS_LENGTH:
        longest_index = max(range(len(fields)), key=lambda index: len(fields[index]))
        field = fields[longest_index]
        excess = len(compose()) - MAX_RESULT_SMS_LENGTH
        keep_length = max(1, len(field) - excess)
        if keep_length == len(field):
            break
        fields[longest_index] = (
            f'{field[:keep_length - 1]}…' if keep_length > 1 else '…'
        )
    return compose()


def send_result_sms(notification_id):
    now = timezone.now()
    with transaction.atomic():
        sms_settings = AttendanceSMSSettings.objects.filter(pk=1).only('enabled').first()
        notification = (
            ExamResultSMSNotification.objects
            .select_related('result__exam', 'result__student')
            .select_for_update()
            .get(pk=notification_id)
        )
        if notification.state in (
            ExamResultSMSNotification.Status.SENT,
            ExamResultSMSNotification.Status.CANCELLED,
        ):
            return None
        if sms_settings is None or not sms_settings.enabled:
            ExamResultSMSNotification.objects.filter(pk=notification.pk).update(
                state=ExamResultSMSNotification.Status.CANCELLED,
                last_error='SMS System বন্ধ থাকায় SMS পাঠানো হয়নি।',
                updated_at=now,
            )
            return None
        claimed = ExamResultSMSNotification.objects.filter(
            pk=notification.pk,
            state__in=[
                ExamResultSMSNotification.Status.PENDING,
                ExamResultSMSNotification.Status.FAILED,
            ],
        ).update(
            state=ExamResultSMSNotification.Status.SENDING,
            attempts=notification.attempts + 1,
            last_error='',
            updated_at=now,
        )
        if not claimed:
            return None
        notification.refresh_from_db()

    try:
        message = build_result_sms_message(notification)
        ExamResultSMSNotification.objects.filter(pk=notification.pk).update(
            rank=notification.rank,
            rank_out_of=notification.rank_out_of,
        )
        provider_message_id = send_sms_message(notification.recipient_phone, message)
    except SMSDeliveryError as error:
        ExamResultSMSNotification.objects.filter(
            pk=notification.pk,
            state=ExamResultSMSNotification.Status.SENDING,
        ).update(
            state=ExamResultSMSNotification.Status.FAILED,
            last_error=str(error),
            updated_at=timezone.now(),
        )
        logger.warning(
            'Exam result SMS failed: notification_id=%s result_id=%s reason=%s',
            notification.pk,
            notification.result_id,
            error,
        )
        return False

    ExamResultSMSNotification.objects.filter(
        pk=notification.pk,
        state=ExamResultSMSNotification.Status.SENDING,
    ).update(
        state=ExamResultSMSNotification.Status.SENT,
        provider_message_id=provider_message_id,
        sent_at=timezone.now(),
        last_error='',
        updated_at=timezone.now(),
    )
    logger.info(
        'Exam result SMS accepted: notification_id=%s result_id=%s',
        notification.pk,
        notification.result_id,
    )
    return True


def send_result_sms_notifications(notification_ids):
    sent = 0
    failed = 0
    for notification_id in notification_ids:
        result = send_result_sms(notification_id)
        if result is True:
            sent += 1
        elif result is False:
            failed += 1
    return sent, failed
