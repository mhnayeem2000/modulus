from decimal import Decimal
from io import BytesIO
import urllib.parse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import AttendanceSMSSettings
from students.models import Student
from .forms import ExamForm
from .models import Exam, ExamResult, ExamResultSMSNotification
from .sms import SMSDeliveryError, build_result_sms_message


class ExamResultTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='teacher', password='safe-test-password')
        self.student = Student.objects.create(
            name='আয়েশা রহমান',
            student_id='ST-1024',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.exam = Exam.objects.create(
            title='সাপ্তাহিক পরীক্ষা ০৩',
            exam_date='2026-10-10',
            class_name=self.student.class_name,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট ও ক্রস গুণন',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

    def test_teacher_can_open_exam_list(self):
        response = self.client.get(reverse('exam_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.exam.title)

    def test_exam_list_paginates_owner_scoped_exams_and_keeps_month_selection(self):
        for index in range(9):
            Exam.objects.create(
                title=f'October exam {index}',
                exam_date=f'2026-10-{index + 11:02d}',
                class_name=self.student.class_name,
                subject='পদার্থবিজ্ঞান',
                paper='১ম পত্র',
                chapter='ভেক্টর',
                topic='অনুশীলন',
                total_marks=20,
                created_by=self.user,
            )
        another_teacher = get_user_model().objects.create_user(
            username='another-exam-teacher',
            password='safe-test-password',
        )
        Exam.objects.create(
            title='Private exam',
            exam_date='2026-10-15',
            class_name=self.student.class_name,
            subject='রসায়ন',
            paper='১ম পত্র',
            chapter='পরমাণু',
            topic='অনুশীলন',
            total_marks=20,
            created_by=another_teacher,
        )

        response = self.client.get(reverse('exam_list'), {
            'month': '2026-10',
            'page': '2',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 10)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertContains(response, '?month=2026-10&page=1')
        self.assertNotContains(response, 'Private exam')
        october_day = next(
            day
            for week in response.context['calendar_days']
            for day in week
            if day['date'].isoformat() == '2026-10-10'
        )
        self.assertEqual([exam.pk for exam in october_day['exams']], [self.exam.pk])

    def test_exam_calendar_month_navigation_changes_the_calendar_month(self):
        response = self.client.get(reverse('exam_list'), {'month': '2026-10'})

        self.assertEqual(response.context['calendar_month'].isoformat(), '2026-10-01')
        self.assertEqual(response.context['previous_month'].isoformat(), '2026-09-01')
        self.assertEqual(response.context['next_month'].isoformat(), '2026-11-01')
        self.assertTrue(any(
            exam.pk == self.exam.pk
            for week in response.context['calendar_days']
            for day in week
            for exam in day['exams']
        ))

    def test_teacher_can_record_student_marks(self):
        response = self.client.post(reverse('exam_results', args=[self.exam.pk]), {
            f'marks_{self.student.pk}': '16.5',
        })

        self.assertRedirects(
            response,
            f'{reverse("exam_results", args=[self.exam.pk])}?saved=1',
        )
        self.assertEqual(ExamResult.objects.get().marks, 16.5)

    def test_marks_save_sends_bangla_sms_under_160_characters_once_and_again_when_marks_change(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        higher_student = Student.objects.create(
            name='রাফি',
            student_id='ST-1025',
            class_name=self.student.class_name,
        )
        tied_student = Student.objects.create(
            name='সুমাইয়া',
            student_id='ST-1026',
            class_name=self.student.class_name,
        )
        ExamResult.objects.create(exam=self.exam, student=higher_student, marks=18)
        ExamResult.objects.create(exam=self.exam, student=tied_student, marks=16.5)
        AttendanceSMSSettings.objects.update_or_create(pk=1, defaults={'enabled': True})
        response_body = b'{"response_code":202,"success_message":"SMS Submitted Successfully"}'
        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            side_effect=lambda *args, **kwargs: BytesIO(response_body),
        ) as mocked_send:
            first_response = self.client.post(reverse('exam_results', args=[self.exam.pk]), {
                f'marks_{self.student.pk}': '16.5',
            }, follow=True)
            self.client.post(reverse('exam_results', args=[self.exam.pk]), {
                f'marks_{self.student.pk}': '16.5',
            })
            self.client.post(reverse('exam_results', args=[self.exam.pk]), {
                f'marks_{self.student.pk}': '17',
            })

        self.assertContains(first_response, 'নম্বরের SMS: BulkSMSBD 1টি গ্রহণ করেছে')
        self.assertEqual(mocked_send.call_count, 2)
        notification = ExamResultSMSNotification.objects.first()
        self.assertEqual(notification.state, ExamResultSMSNotification.Status.SENT)
        self.assertEqual(notification.recipient_phone, '01712345678')
        self.assertEqual(ExamResultSMSNotification.objects.count(), 2)
        for call, expected_score in zip(mocked_send.call_args_list, ('16.5/20', '17/20')):
            request = call.args[0]
            params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            message = params['message'][0]
            self.assertLessEqual(len(message), 160)
            self.assertTrue(message.startswith('প্রিয় অভিভাবক, আপনার আয়েশা রহমান'))
            self.assertIn('পদার্থবিজ্ঞান ১ম Paper ভেক্টর Chapter', message)
            self.assertIn(f'{expected_score} পেয়েছে।', message)
            self.assertIn('Rank: 2/3', message)
            self.assertTrue(message.endswith('-Modulus Edu'))
            self.assertEqual(params['number'], ['8801712345678'])

    def test_marks_are_saved_without_sms_when_sms_system_is_off(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        AttendanceSMSSettings.objects.update_or_create(pk=1, defaults={'enabled': False})

        with patch('attendance.sms.urllib.request.urlopen') as mocked_send:
            response = self.client.post(reverse('exam_results', args=[self.exam.pk]), {
                f'marks_{self.student.pk}': '16.5',
            }, follow=True)

        self.assertContains(response, 'SMS System বন্ধ থাকায় কোনো SMS পাঠানো হয়নি')
        self.assertEqual(ExamResult.objects.get().marks, Decimal('16.5'))
        self.assertFalse(ExamResultSMSNotification.objects.exists())
        mocked_send.assert_not_called()

    def test_superadmin_can_record_marks_and_sms_appears_in_combined_sms_report(self):
        self.student.guardian_phone = '01712345678'
        self.student.save(update_fields=['guardian_phone'])
        AttendanceSMSSettings.objects.update_or_create(pk=1, defaults={'enabled': True})
        superadmin = get_user_model().objects.create_superuser(
            username='exam-admin',
            password='safe-admin-password',
        )
        self.client.force_login(superadmin)
        with self.settings(
            BULKSMSBD_API_KEY='test-api-key',
            BULKSMSBD_SENDER_ID='8809617643378',
        ), patch(
            'attendance.sms.urllib.request.urlopen',
            return_value=BytesIO(b'{"response_code":202,"sms_id":"exam-message"}'),
        ):
            self.client.post(reverse('exam_results', args=[self.exam.pk]), {
                f'marks_{self.student.pk}': '16',
            })

        response = self.client.get(reverse('sms_report'))

        self.assertEqual(response.context['totals']['sent'], 1)
        self.assertContains(response, 'পরীক্ষার নম্বরের SMS')
        self.assertContains(response, 'exam-message')
        self.assertContains(response, '01712345678')
        notification = ExamResultSMSNotification.objects.get()
        self.assertEqual((notification.rank, notification.rank_out_of), (1, 1))
        self.assertContains(response, '1/1')

    def test_long_result_sms_is_truncated_to_160_characters_and_keeps_score(self):
        self.student.name = 'শিক্ষার্থী' * 8
        self.student.save(update_fields=['name'])
        self.exam.subject = 'পদার্থবিজ্ঞান' * 5
        self.exam.chapter = 'ভেক্টর অধ্যায়' * 8
        self.exam.save(update_fields=['subject', 'chapter'])
        result = ExamResult.objects.create(
            exam=self.exam,
            student=self.student,
            marks=Decimal('16.50'),
        )
        result.refresh_from_db()
        notification = ExamResultSMSNotification(
            result=result,
            marks=Decimal('16.50'),
            recipient_phone='01712345678',
        )

        message = build_result_sms_message(notification)

        self.assertLessEqual(len(message), 160)
        self.assertIn('আপনার', message)
        self.assertIn('16.5/20', message)
        self.assertIn('Rank: 1/1', message)
        self.assertEqual(len(message), 160)
        self.assertTrue(message.endswith('-Modulus Edu'))

    def test_result_sms_requires_subject_instead_of_sending_ambiguous_paper_name(self):
        self.exam.subject = ''
        result = ExamResult.objects.create(
            exam=self.exam,
            student=self.student,
            marks=Decimal('45'),
        )
        notification = ExamResultSMSNotification(
            result=result,
            marks=Decimal('45'),
            recipient_phone='01712345678',
        )

        with self.assertRaisesRegex(SMSDeliveryError, 'বিষয় নির্ধারিত নেই'):
            build_result_sms_message(notification)

    def test_existing_exam_can_be_updated_with_subject_paper_and_chapter(self):
        self.exam.subject = ''
        self.exam.paper = '1st'
        self.exam.chapter = '1st'
        self.exam.save(update_fields=['subject', 'paper', 'chapter'])

        response = self.client.post(reverse('exam_edit', args=[self.exam.pk]), {
            'title': self.exam.title,
            'exam_date': '2026-10-10',
            'year_group': self.exam.year_group,
            'subject': 'রসায়ন',
            'paper': '১ম পত্র',
            'chapter': 'ল্যাবরেটরির নিরাপদ ব্যবহার',
            'topic': self.exam.topic,
            'total_marks': self.exam.total_marks,
        })

        self.assertRedirects(response, reverse('exam_list'))
        self.exam.refresh_from_db()
        self.assertEqual(
            (self.exam.subject, self.exam.paper, self.exam.chapter),
            ('রসায়ন', '১ম পত্র', 'ল্যাবরেটরির নিরাপদ ব্যবহার'),
        )
        result = ExamResult.objects.create(
            exam=self.exam,
            student=self.student,
            marks=Decimal('45'),
        )
        message = build_result_sms_message(ExamResultSMSNotification(
            result=result,
            marks=Decimal('45'),
            recipient_phone='01712345678',
        ))
        self.assertIn('রসায়ন ১ম Paper ল্যাবরেটরির নিরাপদ ব্যবহার Chapter', message)

    def test_marks_above_full_marks_are_rejected(self):
        response = self.client.post(reverse('exam_results', args=[self.exam.pk]), {
            f'marks_{self.student.pk}': '21',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '০ থেকে 20-এর মধ্যে')
        self.assertFalse(ExamResult.objects.exists())

    def test_results_page_is_scoped_to_exam_class(self):
        Student.objects.create(
            name='অন্য ব্যাচ',
            student_id='ST-2000',
            class_name='SSC 2026',
            year_group='second',
        )

        response = self.client.get(reverse('exam_results', args=[self.exam.pk]))

        self.assertContains(response, self.student.name)
        self.assertNotContains(response, 'অন্য ব্যাচ')

    def test_exam_form_uses_science_subject_paper_and_chapter_dropdowns(self):
        form = ExamForm(data={
            'title': 'ভেক্টর মূল্যায়ন',
            'exam_date': '2026-10-15',
            'year_group': 'second',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
            'topic': 'ডট ও ক্রস গুণন',
            'total_marks': 20,
        })

        self.assertTrue(form.is_valid(), form.errors)
        exam = form.save(commit=False)
        self.assertEqual(exam.year_group, 'second')
        self.assertEqual(exam.class_name, '২য় বর্ষ')
        self.assertEqual(exam.subject, 'পদার্থবিজ্ঞান')

    def test_exam_form_rejects_chapter_outside_selected_science_paper(self):
        form = ExamForm(data={
            'title': 'ভুল অধ্যায়',
            'exam_date': '2026-10-15',
            'year_group': 'first',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'বৃত্ত',
            'topic': 'ভুল নির্বাচন',
            'total_marks': 20,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('chapter', form.errors)
