import json
import logging
import re
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import Attendance, AttendanceWhatsAppNotification

logger = logging.getLogger(__name__)
SENDING_TIMEOUT = timedelta(minutes=10)


class WhatsAppDeliveryError(Exception):
    pass


def _phone_number_for_meta(phone):
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = f'88{digits}'
    if not digits or len(digits) < 8 or len(digits) > 15:
        raise WhatsAppDeliveryError('অভিভাবকের WhatsApp নম্বরটি সঠিক নয়।')
    return digits


def _template_payload(notification):
    attendance = notification.attendance
    student = attendance.student
    is_present = attendance.status == Attendance.Status.PRESENT
    template_name = (
        settings.WHATSAPP_PRESENT_TEMPLATE_NAME
        if is_present
        else settings.WHATSAPP_ABSENT_TEMPLATE_NAME
    )
    if not template_name:
        raise WhatsAppDeliveryError('এই উপস্থিতির জন্য approved WhatsApp template configure করা নেই।')

    parameters = [
        {'type': 'text', 'text': student.name},
    ]
    if is_present:
        parameters.append({
            'type': 'text',
            'text': attendance.date.strftime('%d %B %Y'),
        })

    return {
        'messaging_product': 'whatsapp',
        'to': _phone_number_for_meta(student.guardian_phone),
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': settings.WHATSAPP_TEMPLATE_LANGUAGE},
            'components': [{'type': 'body', 'parameters': parameters}],
        },
    }


def _meta_error_message(error):
    try:
        details = json.loads(error.read().decode('utf-8'))
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        details = {}
    api_error = details.get('error', {}) if isinstance(details, dict) else {}
    if not isinstance(api_error, dict):
        api_error = {}
    code = api_error.get('code')
    message = api_error.get('message')
    description = f'Meta API HTTP {error.code}'
    if code:
        description += f' (code {code})'
    if code == 190:
        return (
            f'{description}: Meta access token invalid, expired, or revoked. '
            'Meta Developer Dashboard থেকে নতুন WhatsApp access token তৈরি করুন '
            '(whatsapp_business_messaging permissionসহ) এবং local server environment-এ '
            'WHATSAPP_ACCESS_TOKEN হিসেবে সেট করুন।'
        )
    if message:
        description += f': {str(message)[:400]}'
    return description


def _send_template(notification):
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        raise WhatsAppDeliveryError('WhatsApp API credentials server environment-এ configure করা নেই।')
    if not settings.WHATSAPP_API_VERSION:
        raise WhatsAppDeliveryError('WhatsApp API version configure করা নেই।')

    payload = _template_payload(notification)
    url = (
        f'https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/'
        f'{settings.WHATSAPP_PHONE_NUMBER_ID}/messages'
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise WhatsAppDeliveryError(_meta_error_message(error)) from None
    except urllib.error.URLError:
        raise WhatsAppDeliveryError('Meta WhatsApp API-তে সংযোগ করা যায়নি।') from None
    except (TimeoutError, OSError):
        raise WhatsAppDeliveryError('Meta WhatsApp API-তে সংযোগ timeout হয়েছে।') from None
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise WhatsAppDeliveryError('Meta API থেকে বৈধ JSON response পাওয়া যায়নি।') from None

    if not isinstance(response_data, dict):
        raise WhatsAppDeliveryError('Meta API থেকে বৈধ message response পাওয়া যায়নি।')
    messages = response_data.get('messages', [])
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict) or not messages[0].get('id'):
        raise WhatsAppDeliveryError('Meta API message গ্রহণের confirmation দেয়নি।')
    return messages[0]['id']


def send_notification(notification_id):
    now = timezone.now()
    with transaction.atomic():
        notification = (
            AttendanceWhatsAppNotification.objects
            .select_related('attendance__student')
            .get(pk=notification_id)
        )
        if notification.state in (
            AttendanceWhatsAppNotification.Status.SENT,
            AttendanceWhatsAppNotification.Status.CANCELLED,
        ):
            return None
        if notification.attendance.status != notification.attendance_status:
            AttendanceWhatsAppNotification.objects.filter(pk=notification.pk).update(
                state=AttendanceWhatsAppNotification.Status.CANCELLED,
                updated_at=now,
            )
            return None
        if (
            notification.state == AttendanceWhatsAppNotification.Status.SENDING
            and notification.updated_at >= now - SENDING_TIMEOUT
        ):
            return None

        claimable_statuses = [
            AttendanceWhatsAppNotification.Status.PENDING,
            AttendanceWhatsAppNotification.Status.FAILED,
        ]
        claimed = AttendanceWhatsAppNotification.objects.filter(pk=notification.pk).filter(
            Q(state__in=claimable_statuses)
            | Q(state=AttendanceWhatsAppNotification.Status.SENDING, updated_at__lt=now - SENDING_TIMEOUT)
        ).update(
            state=AttendanceWhatsAppNotification.Status.SENDING,
            attempts=F('attempts') + 1,
            last_error='',
            updated_at=now,
        )
        if not claimed:
            return None
        notification.refresh_from_db()

    try:
        provider_message_id = _send_template(notification)
    except WhatsAppDeliveryError as error:
        AttendanceWhatsAppNotification.objects.filter(
            pk=notification.pk,
            state=AttendanceWhatsAppNotification.Status.SENDING,
        ).update(
            state=AttendanceWhatsAppNotification.Status.FAILED,
            delivery_status='failed',
            last_error=str(error),
            updated_at=timezone.now(),
        )
        logger.warning(
            'WhatsApp attendance notification failed: notification_id=%s attendance_id=%s reason=%s',
            notification.pk,
            notification.attendance_id,
            error,
        )
        return False

    AttendanceWhatsAppNotification.objects.filter(
        pk=notification.pk,
        state=AttendanceWhatsAppNotification.Status.SENDING,
    ).update(
        state=AttendanceWhatsAppNotification.Status.SENT,
        delivery_status='accepted',
        provider_message_id=provider_message_id,
        sent_at=timezone.now(),
        last_error='',
        updated_at=timezone.now(),
    )
    logger.info(
        'WhatsApp attendance notification accepted: notification_id=%s attendance_id=%s provider_message_id=%s',
        notification.pk,
        notification.attendance_id,
        provider_message_id,
    )
    return True


def send_queued_notifications(notification_ids):
    sent = 0
    failed = 0
    for notification_id in notification_ids:
        result = send_notification(notification_id)
        if result is True:
            sent += 1
        elif result is False:
            failed += 1
    return sent, failed
