import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import Attendance, AttendanceSMSNotification

logger = logging.getLogger(__name__)
SENDING_TIMEOUT = timedelta(minutes=10)
SMS_API_URL = 'https://bulksmsbd.net/api/smsapi'
BALANCE_API_URL = 'https://bulksmsbd.net/api/getBalanceApi'
ERROR_MESSAGES = {
    '1001': 'মোবাইল নম্বরটি সঠিক নয়।',
    '1002': 'Sender ID সঠিক নয় বা বন্ধ আছে।',
    '1003': 'API request-এ প্রয়োজনীয় তথ্য নেই।',
    '1005': 'BulkSMSBD internal error।',
    '1006': 'SMS balance-এর মেয়াদ নেই।',
    '1007': 'SMS balance অপর্যাপ্ত।',
    '1011': 'API key-এর user account পাওয়া যায়নি।',
    '1012': 'Masking SMS-এর message বাংলা হতে হবে।',
    '1013': 'এই API key-এর জন্য Sender ID gateway-তে নেই।',
    '1014': 'এই Sender ID-এর sender type পাওয়া যায়নি।',
    '1015': 'এই API key-এর জন্য Sender ID-তে সক্রিয় gateway নেই।',
    '1016': 'এই Sender ID-এর active price তথ্য নেই।',
    '1017': 'এই Sender ID-এর price তথ্য নেই।',
    '1018': 'BulkSMSBD account বন্ধ আছে।',
    '1019': 'এই sender type-এর account pricing বন্ধ আছে।',
    '1020': 'BulkSMSBD parent account পাওয়া যায়নি।',
    '1021': 'Parent account-এর active sender pricing পাওয়া যায়নি।',
    '1031': 'BulkSMSBD account verified নয়।',
    '1032': 'Server IP BulkSMSBD-তে whitelist করা নেই।',
}


class SMSDeliveryError(Exception):
    pass


def _balance_from_response(response_data):
    balance_keys = {'balance', 'current_balance', 'sms_balance', 'available_balance'}
    if isinstance(response_data, dict):
        for key, value in response_data.items():
            if str(key).lower() in balance_keys:
                if isinstance(value, (dict, list)):
                    continue
                match = re.fullmatch(
                    r'\s*৳?\s*([\d,]+(?:\.\d+)?)\s*(?:BDT|TK|TAKA)?\s*',
                    str(value),
                    re.IGNORECASE,
                )
                if match:
                    try:
                        amount = Decimal(match.group(1).replace(',', ''))
                    except InvalidOperation:
                        continue
                    if amount >= 0:
                        return amount
        for value in response_data.values():
            if isinstance(value, (dict, list)):
                result = _balance_from_response(value)
                if result is not None:
                    return result
    elif isinstance(response_data, list):
        for value in response_data:
            if isinstance(value, (dict, list)):
                result = _balance_from_response(value)
                if result is not None:
                    return result
    elif isinstance(response_data, str):
        match = re.fullmatch(
            r'\s*৳?\s*([\d,]+(?:\.\d+)?)\s*(?:BDT|TK|TAKA)?\s*',
            response_data,
            re.IGNORECASE,
        )
        if match:
            try:
                amount = Decimal(match.group(1).replace(',', ''))
            except InvalidOperation:
                return None
            if amount >= 0:
                return amount
    return None


def get_account_balance():
    if not settings.BULKSMSBD_API_KEY:
        raise SMSDeliveryError('BULKSMSBD_API_KEY local server environment-এ configure করা নেই।')

    url = f'{BALANCE_API_URL}?{urllib.parse.urlencode({"api_key": settings.BULKSMSBD_API_KEY})}'
    request = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_data = response.read().decode('utf-8').strip()
    except urllib.error.HTTPError as error:
        raise SMSDeliveryError(f'BulkSMSBD balance API HTTP {error.code}.') from None
    except urllib.error.URLError:
        raise SMSDeliveryError('BulkSMSBD balance API-তে সংযোগ করা যায়নি।') from None
    except (TimeoutError, OSError):
        raise SMSDeliveryError('BulkSMSBD balance API-তে সংযোগ timeout হয়েছে।') from None
    except (AttributeError, TypeError, UnicodeDecodeError):
        raise SMSDeliveryError('BulkSMSBD থেকে balance response পড়া যায়নি।') from None

    try:
        parsed_response = json.loads(response_data)
    except json.JSONDecodeError:
        parsed_response = response_data
    balance = _balance_from_response(parsed_response)
    if balance is None:
        raise SMSDeliveryError('BulkSMSBD-এর response থেকে account balance বোঝা যায়নি।')
    return balance


def _phone_number_for_sms(phone):
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = f'88{digits}'
    if not digits or len(digits) < 8 or len(digits) > 15:
        raise SMSDeliveryError('অভিভাবকের মোবাইল নম্বরটি সঠিক নয়।')
    return digits


def _message_for_notification(notification):
    attendance = notification.attendance
    student = attendance.student
    school_name = settings.WHATSAPP_SCHOOL_NAME
    date_text = attendance.date.strftime('%d-%m-%Y')
    status_message = {
        Attendance.Status.PRESENT: f'আজ {date_text} তারিখে উপস্থিত ছিল',
        Attendance.Status.ABSENT: f'আজ {date_text} তারিখে অনুপস্থিত ছিল',
        Attendance.Status.LATE: f'আজ {date_text} তারিখে দেরি করে উপস্থিত হয়েছে',
    }[attendance.status]
    return f'প্রিয় অভিভাবক, আপনার সন্তান {student.name} {school_name}-এ {status_message}।'


def send_sms_message(phone, message):
    if not settings.BULKSMSBD_API_KEY:
        raise SMSDeliveryError('BULKSMSBD_API_KEY local server environment-এ configure করা নেই।')

    params = {
        'api_key': settings.BULKSMSBD_API_KEY,
        'type': 'unicode',
        'number': _phone_number_for_sms(phone),
        'senderid': settings.BULKSMSBD_SENDER_ID,
        'message': message,
    }
    url = f'{SMS_API_URL}?{urllib.parse.urlencode(params)}'
    request = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise SMSDeliveryError(f'BulkSMSBD API HTTP {error.code}.') from None
    except urllib.error.URLError:
        raise SMSDeliveryError('BulkSMSBD API-তে সংযোগ করা যায়নি।') from None
    except (TimeoutError, OSError):
        raise SMSDeliveryError('BulkSMSBD API-তে সংযোগ timeout হয়েছে।') from None
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise SMSDeliveryError('BulkSMSBD থেকে বৈধ JSON response পাওয়া যায়নি।') from None

    if not isinstance(response_data, dict):
        raise SMSDeliveryError('BulkSMSBD থেকে বৈধ response পাওয়া যায়নি।')
    response_code = str(response_data.get('response_code', 'unknown'))
    if response_code != '202':
        error_message = response_data.get('error_message')
        if error_message:
            if 'is_masking' in str(error_message).lower():
                raise SMSDeliveryError(
                    'BulkSMSBD account-এ normal/non-masking sender configuration পাওয়া যায়নি। '
                    'এটি provider-side error; BulkSMSBD support-কে account-এর non-masking SMS route '
                    'সক্রিয় করতে বলুন।'
                )
        known_error = ERROR_MESSAGES.get(response_code)
        if known_error:
            raise SMSDeliveryError(f'BulkSMSBD ({response_code}): {known_error}')
        if error_message:
            raise SMSDeliveryError(f'BulkSMSBD: {str(error_message)[:300]}')
        raise SMSDeliveryError(
            f'BulkSMSBD SMS গ্রহণ করেনি (response code {response_code}).'
        )
    return str(response_data.get('sms_id') or response_data.get('message_id') or '')


def _send_sms(notification):
    return send_sms_message(
        notification.attendance.student.guardian_phone,
        _message_for_notification(notification),
    )


def send_notification(notification_id):
    now = timezone.now()
    with transaction.atomic():
        notification = (
            AttendanceSMSNotification.objects
            .select_related('attendance__student')
            .get(pk=notification_id)
        )
        if notification.state in (
            AttendanceSMSNotification.Status.SENT,
            AttendanceSMSNotification.Status.CANCELLED,
        ):
            return None
        if notification.attendance.status != notification.attendance_status:
            AttendanceSMSNotification.objects.filter(pk=notification.pk).update(
                state=AttendanceSMSNotification.Status.CANCELLED,
                updated_at=now,
            )
            return None

        claimable_statuses = [
            AttendanceSMSNotification.Status.PENDING,
            AttendanceSMSNotification.Status.FAILED,
        ]
        claimed = AttendanceSMSNotification.objects.filter(pk=notification.pk).filter(
            Q(state__in=claimable_statuses)
            | Q(state=AttendanceSMSNotification.Status.SENDING, updated_at__lt=now - SENDING_TIMEOUT)
        ).update(
            state=AttendanceSMSNotification.Status.SENDING,
            attempts=F('attempts') + 1,
            last_error='',
            updated_at=now,
        )
        if not claimed:
            return None
        notification.refresh_from_db()

    try:
        provider_message_id = _send_sms(notification)
    except SMSDeliveryError as error:
        AttendanceSMSNotification.objects.filter(
            pk=notification.pk,
            state=AttendanceSMSNotification.Status.SENDING,
        ).update(
            state=AttendanceSMSNotification.Status.FAILED,
            last_error=str(error),
            updated_at=timezone.now(),
        )
        logger.warning(
            'SMS attendance notification failed: notification_id=%s attendance_id=%s reason=%s',
            notification.pk,
            notification.attendance_id,
            error,
        )
        return False

    AttendanceSMSNotification.objects.filter(
        pk=notification.pk,
        state=AttendanceSMSNotification.Status.SENDING,
    ).update(
        state=AttendanceSMSNotification.Status.SENT,
        provider_message_id=provider_message_id,
        sent_at=timezone.now(),
        last_error='',
        updated_at=timezone.now(),
    )
    logger.info(
        'SMS attendance notification accepted: notification_id=%s attendance_id=%s',
        notification.pk,
        notification.attendance_id,
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
