from datetime import date
from io import BytesIO
import json
import urllib.error
import urllib.parse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from students.models import Student
from .models import (
    Attendance,
    AttendanceSMSBatch,
    AttendanceSMSNotification,
    AttendanceSMSSettings,
    AttendanceWhatsAppNotification,
)
from .sms import SMSDeliveryError, _send_sms
from .whatsapp import _meta_error_message


class AttendanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='teacher', password='safe-test-password')
        self.admin = get_user_model().objects.create_superuser(
            username='attendance-admin',
            password='safe-admin-password',
        )
        self.student = Student.objects.create(
            name='আয়েশা রহমান',
            student_id='ST-1024',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.client.force_login(self.admin)

    def test_superadmin_can_mark_and_update_daily_attendance(self):
        url = reverse('attendance_list')
        payload = {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            'notification_method': 'whatsapp',
        }

        response = self.client.post(url, payload)
        self.assertRedirects(response, f'{url}?date=2026-10-10&saved=1')
        self.client.post(url, {**payload, f'status_{self.student.pk}': Attendance.Status.ABSENT})

        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().status, Attendance.Status.ABSENT)

    def test_attendance_list_separates_first_and_second_year_with_tabs(self):
        second_year_student = Student.objects.create(
            name='নাবিল আহমেদ',
            student_id='ST-2048',
            class_name='HSC 2nd Year · বিজ্ঞান',
            year_group='second',
        )

        response = self.client.get(reverse('attendance_list'))

        self.assertEqual(response.status_code, 200)
        year_groups = response.context['year_groups']
        self.assertEqual([group['key'] for group in year_groups], ['first', 'second'])
        self.assertEqual([student.pk for student in year_groups[0]['students']], [self.student.pk])
        self.assertEqual([student.pk for student in year_groups[1]['students']], [second_year_student.pk])
        self.assertContains(response, '১ম বর্ষ')
        self.assertContains(response, '২য় বর্ষ')
        self.assertContains(response, 'data-attendance-year-tabs')

    def test_notification_method_defaults_to_sms(self):
        response = self.client.get(reverse('attendance_list'))

        self.assertEqual(response.context['notification_method'], 'sms')
        self.assertContains(response, '<option value="sms" selected>')

    def test_sms_system_can_be_toggled_and_off_prevents_sms_send(self):
        response = self.client.get(reverse('sms_system'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['sms_settings'].enabled)

        toggle_off = self.client.post(reverse('sms_system'), {
            'action': 'set_sms_state',
            'enabled': 'off',
        })
        self.assertRedirects(toggle_off, reverse('sms_system'))
        sms_settings = AttendanceSMSSettings.objects.get(pk=1)
        self.assertFalse(sms_settings.enabled)
        self.assertEqual(sms_settings.updated_by, self.admin)

        with patch('attendance.sms.urllib.request.urlopen') as provider_call:
            response = self.client.post(reverse('attendance_list'), {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.PRESENT,
                'notification_method': 'sms',
            }, follow=True)

        self.assertContains(response, 'SMS System বন্ধ থাকায় কোনো SMS পাঠানো হয়নি')
        self.assertTrue(Attendance.objects.filter(status=Attendance.Status.PRESENT).exists())
        self.assertFalse(AttendanceSMSNotification.objects.exists())
        provider_call.assert_not_called()
        batch = AttendanceSMSBatch.objects.get()
        self.assertFalse(batch.sms_enabled)
        self.assertEqual(str(batch.estimated_cost), '0.00')
        report = self.client.get(reverse('sms_report'))
        self.assertContains(report, 'বন্ধ ছিল')

        self.client.post(reverse('sms_system'), {
            'action': 'set_sms_state',
            'enabled': 'on',
        })
        sms_settings.refresh_from_db()
        self.assertTrue(sms_settings.enabled)

    def test_sms_system_toggle_ajax_returns_state_without_redirect(self):
        response = self.client.post(
            reverse('sms_state_api'),
            {
                'action': 'set_sms_state',
                'enabled': 'off',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'enabled': False, 'message': 'SMS System বন্ধ করা হয়েছে।'},
        )
        self.assertFalse(AttendanceSMSSettings.objects.get(pk=1).enabled)

    def test_balance_ajax_returns_json_without_rendering_a_page(self):
        with self.settings(BULKSMSBD_API_KEY='test-api-key'), patch(
            'attendance.sms.urllib.request.urlopen',
            return_value=BytesIO(b'{"balance":"123.45"}'),
        ):
            response = self.client.post(
                reverse('sms_balance_api'),
                {'action': 'check_sms_balance'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'balance': '123.45'})
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_sms_system_form_uses_dedicated_ajax_endpoint(self):
        response = self.client.get(reverse('sms_system'))

        self.assertContains(response, f'action="{reverse("sms_state_api")}"')
        self.assertContains(response, f'action="{reverse("sms_balance_api")}"')

    def test_sms_report_summarizes_recipients_and_message_results(self):
        record = Attendance.objects.create(
            student=self.student,
            date=date(2026, 10, 10),
            status=Attendance.Status.PRESENT,
        )
        AttendanceSMSNotification.objects.create(
            attendance=record,
            attendance_status=Attendance.Status.PRESENT,
            recipient_phone='01712345678',
            state=AttendanceSMSNotification.Status.SENT,
            attempts=1,
        )
        failed_record = Attendance.objects.create(
            student=Student.objects.create(
                name='নাবিল আহমেদ',
                student_id='ST-2048',
                class_name='HSC 2026 · বিজ্ঞান',
            ),
            date=date(2026, 10, 10),
            status=Attendance.Status.ABSENT,
        )
        AttendanceSMSNotification.objects.create(
            attendance=failed_record,
            attendance_status=Attendance.Status.ABSENT,
            recipient_phone='01812345678',
            state=AttendanceSMSNotification.Status.FAILED,
            attempts=2,
            last_error='BulkSMSBD (1001): invalid number',
        )

        response = self.client.get(reverse('sms_report'))

        self.assertEqual(response.status_code, 200)
        attendance_recipients = {
            item['recipient_phone']: item
            for item in response.context['recipient_totals']
        }
        self.assertEqual(attendance_recipients['01712345678']['sent'], 1)
        self.assertEqual(attendance_recipients['01812345678']['failed'], 1)
        self.assertEqual(
            sum(item['total_attempts'] for item in attendance_recipients.values()),
            3,
        )
        self.assertContains(response, '01712345678')
        self.assertContains(response, 'আয়েশা রহমান')
        self.assertContains(response, 'BulkSMSBD (1001): invalid number')
        self.assertContains(response, 'নম্বর ও শিক্ষার্থী অনুযায়ী হিসাব')
        self.assertContains(response, 'sms-report-primary-grid')
        self.assertContains(response, 'পরীক্ষার নম্বরের SMS')
        self.assertContains(response, 'SMS attempt-এর বিস্তারিত')
        self.assertContains(response, 'sms-report-recipient-grid')
        self.assertNotContains(response, 'aria-label="SMS সারসংক্ষেপ"')

    def test_attendance_page_marks_successfully_sent_sms_with_tick(self):
        record = Attendance.objects.create(
            student=self.student,
            date=date(2026, 10, 10),
            status=Attendance.Status.PRESENT,
        )
        AttendanceSMSNotification.objects.create(
            attendance=record,
            attendance_status=Attendance.Status.PRESENT,
            recipient_phone='01712345678',
            state=AttendanceSMSNotification.Status.SENT,
        )

        response = self.client.get(reverse('attendance_list'), {'date': '2026-10-10'})

        self.assertContains(response, 'aria-label="SMS পাঠানো হয়েছে"')

    def test_bulk_sms_balance_button_fetches_balance_without_exposing_api_key(self):
        with self.settings(BULKSMSBD_API_KEY='test-api-key'), patch(
            'attendance.sms.urllib.request.urlopen',
            return_value=BytesIO(b'{"balance":"123.45"}'),
        ) as mocked_request:
            response = self.client.post(reverse('attendance_list'), {
                'action': 'check_sms_balance',
                'date': '2026-10-10',
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'বর্তমান ব্যালেন্স: <strong>৳123.45</strong>')
        self.assertNotContains(response, 'test-api-key')
        request = mocked_request.call_args.args[0]
        self.assertEqual(
            urllib.parse.urlparse(request.full_url).path,
            '/api/getBalanceApi',
        )
        self.assertEqual(
            urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query),
            {'api_key': ['test-api-key']},
        )

    def test_attendance_balance_ajax_returns_json_without_reloading_page(self):
        with self.settings(BULKSMSBD_API_KEY='test-api-key'), patch(
            'attendance.sms.urllib.request.urlopen',
            return_value=BytesIO(b'{"balance":"123.45"}'),
        ):
            response = self.client.post(
                reverse('sms_balance_api'),
                {'action': 'check_sms_balance', 'date': '2026-10-10'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'balance': '123.45'})

    def test_sms_save_reports_balance_change_cost(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        balance_responses = iter([b'{"balance":"100.00"}', b'{"balance":"98.75"}'])

        def provider_response(request, timeout):
            if urllib.parse.urlparse(request.full_url).path.endswith('/getBalanceApi'):
                return BytesIO(next(balance_responses))
            return BytesIO(b'{"response_code":202,"success_message":"SMS Submitted Successfully"}')

        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
        ), patch('attendance.sms.urllib.request.urlopen', side_effect=provider_response):
            response = self.client.post(reverse('attendance_list'), {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.PRESENT,
                'notification_method': 'sms',
            }, follow=True)

        self.assertContains(response, 'এই save-এ আনুমানিক SMS খরচ ৳1.25')
        self.assertContains(response, 'পাঠানোর পর ব্যালেন্স ৳98.75')
        batch = AttendanceSMSBatch.objects.get()
        self.assertEqual(batch.accepted_count, 1)
        self.assertEqual(str(batch.estimated_cost), '1.25')
        self.assertEqual(str(batch.balance_after), '98.75')

    def test_bulksmsbd_missing_sender_configuration_has_actionable_error(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        record = Attendance.objects.create(
            student=self.student,
            date=date(2026, 10, 10),
            status=Attendance.Status.PRESENT,
        )
        notification = AttendanceSMSNotification.objects.create(
            attendance=record,
            attendance_status=Attendance.Status.PRESENT,
        )
        response_body = (
            b'{"response_code":1005,"error_message":'
            b'"Attempt to read property \\"is_masking\\" on null"}'
        )

        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            return_value=BytesIO(response_body),
        ), self.assertRaisesRegex(SMSDeliveryError, 'BulkSMSBD support'):
            _send_sms(notification)

    def test_teacher_cannot_view_or_mark_student_attendance(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('attendance_list'), {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            'notification_method': 'whatsapp',
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Attendance.objects.exists())

    def test_invalid_posted_date_does_not_write_attendance(self):
        response = self.client.post(reverse('attendance_list'), {
            'date': 'not-a-date',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'সঠিক তারিখ নির্বাচন করুন')
        self.assertFalse(Attendance.objects.exists())

    def test_invalid_meta_token_error_explains_how_to_fix_credentials(self):
        error = urllib.error.HTTPError(
            url='https://graph.facebook.com/test/messages',
            code=401,
            msg='Unauthorized',
            hdrs=None,
            fp=BytesIO(b'{"error":{"code":190,"message":"Authentication Error"}}'),
        )

        message = _meta_error_message(error)

        self.assertIn('code 190', message)
        self.assertIn('WHATSAPP_ACCESS_TOKEN', message)
        self.assertIn('নতুন WhatsApp access token', message)

    def test_present_attendance_sends_approved_template_to_guardian_once(self):
        self.student.guardian_phone = '+8801712345678'
        self.student.save(update_fields=['guardian_phone'])
        response_mock = BytesIO(b'{"messages":[{"id":"wamid.present"}]}')
        payload = {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            'notification_method': 'whatsapp',
        }

        with self.settings(
            WHATSAPP_ACCESS_TOKEN='test-token-only',
            WHATSAPP_PHONE_NUMBER_ID='test-phone-id',
            WHATSAPP_API_VERSION='v26.0',
            WHATSAPP_PRESENT_TEMPLATE_NAME='present_notice',
            WHATSAPP_ABSENT_TEMPLATE_NAME='absent_notice',
            WHATSAPP_TEMPLATE_LANGUAGE='en',
            WHATSAPP_SCHOOL_NAME='Modulus Edu',
        ), patch('attendance.whatsapp.urllib.request.urlopen', return_value=response_mock) as mocked_send:
            response = self.client.post(reverse('attendance_list'), payload, follow=True)
            repeated_response = self.client.post(reverse('attendance_list'), payload, follow=True)

        self.assertContains(response, 'এইবার Meta 1টি গ্রহণ করেছে, 0টি ব্যর্থ হয়েছে')
        self.assertContains(repeated_response, '1টি আগেই Meta গ্রহণ করেছিল')
        self.assertEqual(mocked_send.call_count, 1)
        request = mocked_send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v26.0/test-phone-id/messages')
        self.assertTrue(request.headers['Authorization'].startswith('Bearer '))
        message = json.loads(request.data.decode('utf-8'))
        self.assertEqual(message['to'], '8801712345678')
        self.assertEqual(message['template']['name'], 'present_notice')
        self.assertEqual(message['template']['language']['code'], 'en')
        self.assertEqual(
            [parameter['text'] for parameter in message['template']['components'][0]['parameters']],
            ['আয়েশা রহমান', '10 October 2026'],
        )
        notification = AttendanceWhatsAppNotification.objects.get()
        self.assertEqual(notification.state, AttendanceWhatsAppNotification.Status.SENT)
        self.assertEqual(notification.provider_message_id, 'wamid.present')
        self.assertEqual(notification.attempts, 1)

    def test_absent_status_uses_absence_template(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        response_mock = BytesIO(b'{"messages":[{"id":"wamid.absent"}]}')

        with self.settings(
            WHATSAPP_ACCESS_TOKEN='test-token',
            WHATSAPP_PHONE_NUMBER_ID='test-phone-id',
            WHATSAPP_API_VERSION='v26.0',
            WHATSAPP_PRESENT_TEMPLATE_NAME='present_notice',
            WHATSAPP_ABSENT_TEMPLATE_NAME='absent_notice',
            WHATSAPP_TEMPLATE_LANGUAGE='en',
            WHATSAPP_SCHOOL_NAME='Modulus Edu',
        ), patch('attendance.whatsapp.urllib.request.urlopen', return_value=response_mock) as mocked_send:
            self.client.post(reverse('attendance_list'), {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.ABSENT,
                'notification_method': 'whatsapp',
            })

        payload = json.loads(mocked_send.call_args.args[0].data.decode('utf-8'))
        self.assertEqual(payload['template']['name'], 'absent_notice')
        self.assertEqual(payload['template']['language']['code'], 'en')
        self.assertEqual(payload['to'], '8801712345678')
        self.assertEqual(
            [parameter['text'] for parameter in payload['template']['components'][0]['parameters']],
            ['আয়েশা রহমান'],
        )
        self.assertEqual(
            AttendanceWhatsAppNotification.objects.get().attendance_status,
            Attendance.Status.ABSENT,
        )

    def test_sms_sends_present_absent_and_late_messages_once(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        absent_student = Student.objects.create(
            name='নাবিল আহমেদ',
            student_id='ST-2048',
            class_name='HSC 2026 · বিজ্ঞান',
            guardian_phone='+8801812345678',
        )
        late_student = Student.objects.create(
            name='সুমাইয়া আক্তার',
            student_id='ST-3072',
            class_name='HSC 2026 · বিজ্ঞান',
            guardian_phone='01912345678',
        )
        response_body = b'{"response_code":202,"success_message":"SMS Submitted Successfully"}'
        payload = {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            f'status_{absent_student.pk}': Attendance.Status.ABSENT,
            f'status_{late_student.pk}': Attendance.Status.LATE,
            'notification_method': 'sms',
        }

        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
            WHATSAPP_SCHOOL_NAME='Modulus Edu',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            side_effect=lambda *args, **kwargs: BytesIO(response_body),
        ) as mocked_send:
            response = self.client.post(reverse('attendance_list'), payload, follow=True)
            self.client.post(reverse('attendance_list'), payload)

        self.assertContains(response, 'BulkSMSBD 3টি গ্রহণ করেছে, 0টি ব্যর্থ হয়েছে')
        self.assertContains(response, 'পাঠানো হয়েছে:')
        self.assertContains(response, '01712345678')
        self.assertEqual(
            response.content.decode().count('aria-label="SMS পাঠানো হয়েছে"'),
            3,
        )
        sms_calls = [
            call for call in mocked_send.call_args_list
            if urllib.parse.urlparse(call.args[0].full_url).path.endswith('/smsapi')
        ]
        self.assertEqual(len(sms_calls), 3)
        messages_by_number = {}
        for call in sms_calls:
            request = call.args[0]
            params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            messages_by_number[params['number'][0]] = params['message'][0]
            self.assertEqual(params['type'], ['unicode'])
            self.assertEqual(params['senderid'], ['8809617643378'])
            self.assertEqual(params['api_key'], ['test-api-key'])

        self.assertIn('উপস্থিত ছিল', messages_by_number['8801712345678'])
        self.assertIn('অনুপস্থিত ছিল', messages_by_number['8801812345678'])
        self.assertIn('দেরি করে উপস্থিত হয়েছে', messages_by_number['8801912345678'])
        self.assertEqual(AttendanceSMSNotification.objects.count(), 3)
        self.assertEqual(
            AttendanceSMSNotification.objects.filter(state=AttendanceSMSNotification.Status.SENT).count(),
            3,
        )

    def test_sms_is_not_resent_for_same_status_but_is_sent_when_status_changes(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        response_body = b'{"response_code":202,"success_message":"SMS Submitted Successfully"}'
        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            side_effect=lambda *args, **kwargs: BytesIO(response_body),
        ) as mocked_send:
            absent = {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.ABSENT,
                'notification_method': 'sms',
            }
            present = {
                **absent,
                f'status_{self.student.pk}': Attendance.Status.PRESENT,
            }
            self.client.post(reverse('attendance_list'), absent)
            repeated_absent = self.client.post(reverse('attendance_list'), absent, follow=True)
            self.client.post(reverse('attendance_list'), present)
            repeated_present = self.client.post(reverse('attendance_list'), present, follow=True)

        sms_calls = [
            call for call in mocked_send.call_args_list
            if urllib.parse.urlparse(call.args[0].full_url).path.endswith('/smsapi')
        ]
        self.assertEqual(len(sms_calls), 2)
        self.assertEqual(AttendanceSMSNotification.objects.count(), 2)
        self.assertContains(repeated_absent, '1টি আগেই BulkSMSBD গ্রহণ করেছিল')
        self.assertContains(repeated_absent, 'SMS খরচ ৳0.00')
        self.assertContains(repeated_present, '1টি আগেই BulkSMSBD গ্রহণ করেছিল')
        self.assertEqual(AttendanceSMSBatch.objects.count(), 4)
        self.assertEqual(
            AttendanceSMSBatch.objects.filter(estimated_cost=0).count(),
            2,
        )
        for notification in AttendanceSMSNotification.objects.all():
            self.assertEqual(notification.state, AttendanceSMSNotification.Status.SENT)

    def test_sms_failure_is_reported_without_rolling_back_attendance(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        payload = {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            'notification_method': 'sms',
        }
        response_body = b'{"response_code":1005,"error_message":"Internal Error"}'

        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            side_effect=lambda *args, **kwargs: BytesIO(response_body),
        ):
            response = self.client.post(reverse('attendance_list'), payload, follow=True)

        self.assertContains(response, 'BulkSMSBD 0টি গ্রহণ করেছে, 1টি ব্যর্থ হয়েছে')
        self.assertContains(response, 'BulkSMSBD (1005): BulkSMSBD internal error')
        self.assertContains(response, '01712345678')
        self.assertTrue(Attendance.objects.filter(status=Attendance.Status.PRESENT).exists())
        self.assertEqual(
            AttendanceSMSNotification.objects.get().state,
            AttendanceSMSNotification.Status.FAILED,
        )

    def test_whatsapp_late_status_is_not_sent_as_absence_template(self):
        with patch('attendance.whatsapp.urllib.request.urlopen') as mocked_send:
            response = self.client.post(reverse('attendance_list'), {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.LATE,
                'notification_method': 'whatsapp',
            }, follow=True)

        self.assertContains(response, 'দেরির WhatsApp পাঠানো হয়নি')
        mocked_send.assert_not_called()
        self.assertFalse(AttendanceWhatsAppNotification.objects.exists())

    def test_failed_message_keeps_attendance_and_can_be_retried(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        payload = {
            'date': '2026-10-10',
            f'status_{self.student.pk}': Attendance.Status.PRESENT,
            'notification_method': 'whatsapp',
        }

        with self.settings(
            WHATSAPP_ACCESS_TOKEN='test-token',
            WHATSAPP_PHONE_NUMBER_ID='test-phone-id',
            WHATSAPP_API_VERSION='v26.0',
            WHATSAPP_PRESENT_TEMPLATE_NAME='present_notice',
            WHATSAPP_ABSENT_TEMPLATE_NAME='absent_notice',
            WHATSAPP_TEMPLATE_LANGUAGE='en',
            WHATSAPP_SCHOOL_NAME='Modulus Edu',
        ), patch(
            'attendance.whatsapp.urllib.request.urlopen',
            side_effect=urllib.error.URLError('offline'),
        ):
            response = self.client.post(reverse('attendance_list'), payload, follow=True)

        self.assertContains(response, 'এইবার Meta 0টি গ্রহণ করেছে, 1টি ব্যর্থ হয়েছে')
        self.assertContains(response, 'Meta WhatsApp API-তে সংযোগ করা যায়নি')
        self.assertEqual(Attendance.objects.get().status, Attendance.Status.PRESENT)
        notification = AttendanceWhatsAppNotification.objects.get()
        self.assertEqual(notification.state, AttendanceWhatsAppNotification.Status.FAILED)
        self.assertEqual(notification.attempts, 1)
        self.assertTrue(notification.last_error)

        with patch('attendance.whatsapp._send_template', return_value='wamid.retried'):
            call_command('retry_whatsapp_attendance')

        notification.refresh_from_db()
        self.assertEqual(notification.state, AttendanceWhatsAppNotification.Status.SENT)
        self.assertEqual(notification.attempts, 2)

    def test_missing_guardian_number_fails_notification_without_rolling_back_attendance(self):
        with self.settings(
            WHATSAPP_ACCESS_TOKEN='test-token',
            WHATSAPP_PHONE_NUMBER_ID='test-phone-id',
            WHATSAPP_API_VERSION='v26.0',
            WHATSAPP_PRESENT_TEMPLATE_NAME='attendance_present_v1',
            WHATSAPP_ABSENT_TEMPLATE_NAME='attendance_absent_v1',
        ), patch('attendance.whatsapp.urllib.request.urlopen') as mocked_send:
            response = self.client.post(reverse('attendance_list'), {
                'date': '2026-10-10',
                f'status_{self.student.pk}': Attendance.Status.PRESENT,
                'notification_method': 'whatsapp',
            }, follow=True)

        self.assertContains(response, 'এইবার Meta 0টি গ্রহণ করেছে, 1টি ব্যর্থ হয়েছে')
        self.assertContains(response, 'অভিভাবকের WhatsApp নম্বরটি সঠিক নয়')
        self.assertTrue(Attendance.objects.filter(status=Attendance.Status.PRESENT).exists())
        self.assertEqual(AttendanceWhatsAppNotification.objects.get().state, AttendanceWhatsAppNotification.Status.FAILED)
        mocked_send.assert_not_called()

    def test_absent_day_is_included_in_monthly_dashboard_rate(self):
        Attendance.objects.create(
            student=self.student,
            date=date(2026, 10, 10),
            status=Attendance.Status.ABSENT,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['attendance_rate'], 0)
        self.assertContains(response, 'উপস্থিতি বিশ্লেষণ')
