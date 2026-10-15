import tempfile
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from exams.models import Exam, ExamResult
from .forms import ClassSessionForm, LearningMaterialForm, RoutineForm
from students.models import Student
from attendance.models import Attendance
from .models import (
    ClassSession,
    ClassSessionProgress,
    LearningMaterial,
    Routine,
    StudentFeeRecord,
    StudentFeedback,
    SupportSessionAttendance,
    UserProfile,
)
from .models import TeacherAttendance
from .year_groups import academic_year_key


class StudentPortalTests(TestCase):
    def setUp(self):
        self.teacher = get_user_model().objects.create_user(
            username='teacher',
            password='safe-test-password',
            first_name='রহিম',
            last_name='স্যার',
        )
        UserProfile.objects.create(user=self.teacher, role=UserProfile.Role.TEACHER, phone='01700000000')
        self.student_user = get_user_model().objects.create_user(
            username='student',
            password='safe-test-password',
            first_name='আয়েশা',
        )
        UserProfile.objects.create(user=self.student_user, role=UserProfile.Role.STUDENT)
        self.student = Student.objects.create(
            user=self.student_user,
            name='আয়েশা রহমান',
            student_id='ST-1024',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.other_student = Student.objects.create(
            name='অন্য ব্যাচের শিক্ষার্থী',
            student_id='ST-2000',
            class_name='SSC 2026',
            year_group='second',
        )

    def test_teacher_routine_version_changes_when_superadmin_updates_routine(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name='HSC 2026 · বিজ্ঞান',
            weekday=Routine.Weekday.MONDAY,
            start_time=time(15),
            end_time=time(16, 30),
            subject='পুরোনো বিষয়',
            year_group=Routine.YearGroup.FIRST,
        )
        self.client.force_login(self.teacher)

        original_response = self.client.get(reverse('teacher_routine_version'))
        routine.subject = 'নতুন বিষয়'
        routine.save(update_fields=['subject'])
        updated_response = self.client.get(reverse('teacher_routine_version'))

        self.assertEqual(original_response.status_code, 200)
        self.assertEqual(updated_response.status_code, 200)
        self.assertEqual(original_response['Cache-Control'], 'max-age=0, no-cache, no-store, must-revalidate, private')
        self.assertNotEqual(
            original_response.json()['version'],
            updated_response.json()['version'],
        )

    def test_student_home_redirects_to_student_dashboard(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('student_dashboard'))

    def test_install_app_page_requires_authentication(self):
        response = self.client.get(reverse('install_app'))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("install_app")}',
        )

    def test_install_app_page_shows_platform_guides_and_is_navigation_linked(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('install_app'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Install on Android')
        self.assertContains(response, 'Install on iPhone')
        self.assertContains(response, 'Add to Home Screen')
        self.assertContains(response, 'manifest.webmanifest')
        self.assertContains(response, 'install-app.js')
        self.assertContains(response, 'images/dark_logo.png')
        self.assertEqual(response.content.decode().count('class="brand-logo"'), 1)
        self.assertEqual(response.content.decode().count('class="topbar-mobile-logo"'), 1)
        self.assertContains(response, 'href="/install-app/"')
        self.assertEqual(response.content.decode().count('href="/install-app/"'), 1)

    def test_student_dashboard_shows_student_portal_and_class_content(self):
        Attendance.objects.create(
            student=self.student,
            date=date(2026, 10, 5),
            status=Attendance.Status.ABSENT,
        )
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=(timezone.localdate().weekday() + 1) % 7,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'আগামীকালের প্রস্তুতি')
        self.assertNotContains(response, 'এই মাসে উপস্থিতি')
        self.assertContains(response, 'পদার্থবিজ্ঞান')
        self.assertContains(response, 'উপস্থিতির ক্যালেন্ডার')
        self.assertEqual(response.context['attendance_calendar_counts']['absent'], 1)
        page = response.content.decode()
        self.assertLess(
            page.index('tomorrow-classes-title'),
            page.index('attendance-calendar-title'),
        )
        self.assertTrue(
            response.context['attendance_calendar_previous_url'].startswith(
                reverse('student_dashboard'),
            )
        )

    def test_student_books_page_lists_subject_sections_and_pdf_links(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_books'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [
            (f"{reverse('student_materials')}?kind=pdf", 302),
        ])
        self.assertEqual(response.context['book_count'], 55)
        self.assertContains(response, 'স্টাডি রিসোর্স')
        self.assertContains(response, 'টি PDF অধ্যায়')
        self.assertContains(response, 'কোষ ও এর গঠন')
        self.assertContains(response, 'প্রাণীর বিভিন্নতা ও শ্রেণিবিন্যাস')
        self.assertContains(response, 'আদর্শ গ্যাস ও গ্যাসের গতিতত্ত্ব')
        self.assertContains(response, 'অর্থনৈতিক রসায়ন')
        self.assertContains(response, 'student-resource-tabs')
        self.assertContains(response, 'Book PDF</button>')
        self.assertContains(response, 'data-resource-tab="sheet"')
        self.assertContains(response, 'data-resource-tab="book"')
        self.assertContains(response, 'data-resource-tab="important"')
        self.assertContains(response, 'data-resource-tab="pdf"')
        self.assertContains(response, 'data-resource-panel="sheet" hidden')
        self.assertContains(response, 'data-resource-panel="pdf"')
        self.assertTemplateUsed(response, 'portal/student_materials.html')
        self.assertContains(
            response,
            'https://drive.google.com/file/d/1vR3JzTvJAvj7rwSiqzmPQEpUHxsqfeel/view',
        )
        self.assertContains(response, 'PDF লিংক শিগগিরই যোগ হবে')

    def test_books_library_is_not_visible_to_teacher_or_superadmin(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('student_books')).status_code, 403)

        superadmin = get_user_model().objects.create_superuser(
            username='books-admin',
            password='safe-admin-password',
        )
        self.client.force_login(superadmin)
        self.assertEqual(self.client.get(reverse('student_books')).status_code, 403)

    def test_student_own_profile_shows_attendance_calendar_with_statuses(self):
        Attendance.objects.create(
            student=self.student,
            date=date(2026, 9, 5),
            status=Attendance.Status.ABSENT,
        )
        Attendance.objects.create(
            student=self.student,
            date=date(2026, 9, 6),
            status=Attendance.Status.PRESENT,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_own_detail'), {'month': '2026-09'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['attendance_calendar_counts']['absent'], 1)
        self.assertEqual(response.context['attendance_calendar_counts']['present'], 1)
        self.assertContains(response, 'উপস্থিতির ক্যালেন্ডার')
        self.assertContains(response, 'attendance-calendar-day is-absent')

    def test_attendance_statistics_remain_available_in_their_own_section(self):
        today = timezone.localdate()
        Attendance.objects.create(
            student=self.student,
            date=today - timedelta(days=1),
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            student=self.student,
            date=today,
            status=Attendance.Status.LATE,
        )
        self.client.force_login(self.student_user)

        statistics_response = self.client.get(reverse('student_statistics'))

        self.assertEqual(statistics_response.context['attendance_rate'], 100)
        self.assertEqual(statistics_response.context['class_days'], 2)

    def test_student_dashboard_shows_only_exams_remaining_this_week(self):
        today = timezone.localdate()
        exam_day = today if today.weekday() == 6 else today + timedelta(days=1)
        this_week_exam = Exam.objects.create(
            title='সামনের সাপ্তাহিক পরীক্ষা',
            exam_date=exam_day,
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='পর্যায় সারণি',
            topic='মৌল পরিচিতি',
            total_marks=20,
            created_by=self.teacher,
        )
        Exam.objects.create(
            title='পরের সপ্তাহের পরীক্ষা',
            exam_date=today + timedelta(days=8),
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='জৈব রসায়ন',
            total_marks=20,
            created_by=self.teacher,
        )
        Exam.objects.create(
            title='অন্য ব্যাচের পরীক্ষা',
            exam_date=exam_day,
            class_name=self.other_student.class_name,
            year_group=self.other_student.year_group,
            paper='১ম পত্র',
            chapter='বীজগণিত',
            total_marks=20,
            created_by=self.teacher,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(response.context['weekly_exams'].count(), 1)
        self.assertEqual(response.context['weekly_exams'][0], this_week_exam)
        self.assertEqual(response.context['next_exam'], this_week_exam)
        self.assertContains(response, this_week_exam.title)
        self.assertContains(response, 'পরবর্তী পরীক্ষা')
        self.assertContains(response, 'student-next-events')
        self.assertNotContains(response, 'পরের সপ্তাহের পরীক্ষা')
        self.assertNotContains(response, 'অন্য ব্যাচের পরীক্ষা')
        self.assertNotContains(response, 'এই মাসে উপস্থিতি')

    def test_student_dashboard_shows_all_tomorrow_classes_with_teacher_time_and_chapter(self):
        tomorrow_weekday = (timezone.localdate().weekday() + 1) % 7
        second_teacher = get_user_model().objects.create_user(
            username='tomorrow-teacher',
            first_name='করিম',
            last_name='স্যার',
        )
        first_class = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=tomorrow_weekday,
            start_time=time(9),
            end_time=time(10, 30),
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
        )
        second_class = Routine.objects.create(
            teacher=second_teacher,
            class_name=self.student.class_name,
            weekday=tomorrow_weekday,
            start_time=time(11),
            end_time=time(12, 30),
            subject='রসায়ন',
            paper='২য় পত্র',
            chapter='জৈব রসায়ন',
        )
        Routine.objects.create(
            teacher=second_teacher,
            class_name=self.other_student.class_name,
            weekday=tomorrow_weekday,
            start_time=time(13),
            end_time=time(14),
            subject='অন্য ব্যাচের গণিত',
            year_group=self.other_student.year_group,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(list(response.context['tomorrow_classes']), [first_class, second_class])
        for detail in (
            'আগামীকালের প্রস্তুতি',
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            '9:00 পূর্বাহ্ন',
            'রহিম স্যার',
            'রসায়ন',
            '২য় পত্র',
            'জৈব রসায়ন',
            '11:00 পূর্বাহ্ন',
            'করিম স্যার',
        ):
            self.assertContains(response, detail)
        self.assertNotContains(response, 'অন্য ব্যাচের গণিত')
        self.assertContains(response, 'student-tomorrow-notice')
        self.assertContains(response, 'student-tomorrow-float-class')
        self.assertContains(response, 'আগামীকালের ক্লাস')

    def test_student_dashboard_top_panel_shows_next_class_details_and_time(self):
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=(timezone.localdate().weekday() + 1) % 7,
            start_time=time(15, 30),
            end_time=time(17, 30),
            subject='রসায়ন',
            paper='১ম পত্র',
            chapter='পর্যায় সারণি',
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertContains(response, 'student-next-event')
        self.assertContains(response, 'পরবর্তী ক্লাস')
        self.assertContains(response, 'রসায়ন · ১ম পত্র')
        self.assertContains(response, 'অধ্যায়: পর্যায় সারণি')
        self.assertContains(response, '3:30 অপরাহ্ন–5:30 অপরাহ্ন')

    def test_student_dashboard_top_panel_shows_next_exam_even_beyond_this_week(self):
        exam = Exam.objects.create(
            title='পরের সপ্তাহের পরীক্ষা',
            exam_date=timezone.localdate() + timedelta(days=8),
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(response.context['next_exam'], exam)
        self.assertContains(response, 'পরবর্তী পরীক্ষা')
        self.assertContains(response, exam.title)
        self.assertFalse(response.context['weekly_exams'].exists())

    def test_student_dashboard_hides_next_exam_card_when_no_future_exam_exists(self):
        Exam.objects.create(
            title='পুরোনো পরীক্ষা',
            exam_date=timezone.localdate() - timedelta(days=1),
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertIsNone(response.context['next_exam'])
        self.assertNotContains(response, 'পরবর্তী পরীক্ষা')

    def test_student_dashboard_says_no_class_tomorrow_when_none_is_scheduled(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertFalse(response.context['tomorrow_classes'].exists())
        self.assertContains(response, 'কাল কোনো ক্লাস নেই')
        self.assertContains(response, 'এখনো কোনো ক্লাসের রুটিন নেই')
        self.assertContains(response, 'student-tomorrow-notice')
        self.assertContains(response, 'কাল তোমার কোনো ক্লাস নেই।')

    def test_student_dashboard_offers_the_support_meet_link(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_dashboard'))

        self.assertContains(response, 'সরাসরি শিক্ষকের সহায়তা')
        self.assertContains(response, 'https://meet.google.com/nbd-ibgk-euz')

    def test_student_cannot_record_teacher_support_session_attendance(self):
        self.client.force_login(self.student_user)

        response = self.client.post(reverse('join_support_session'))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SupportSessionAttendance.objects.exists())

    def test_student_can_update_todays_class_progress_and_report_a_problem(self):
        session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            year_group=self.student.year_group,
            date=timezone.localdate(),
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        other_year_session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.other_student.class_name,
            year_group=self.other_student.year_group,
            date=timezone.localdate(),
            subject='রসায়ন',
            chapter='জৈব রসায়ন',
        )
        self.client.force_login(self.student_user)

        response = self.client.post(
            reverse('update_class_session_progress', args=[session.pk]),
            {
                'is_completed': '',
                'problem_description': 'ক্রস গুণনের ধাপটি বুঝতে সমস্যা হয়েছে।',
            },
        )

        self.assertRedirects(response, reverse('student_dashboard'))
        progress = ClassSessionProgress.objects.get(session=session, student=self.student)
        self.assertFalse(progress.is_completed)
        self.assertEqual(progress.problem_description, 'ক্রস গুণনের ধাপটি বুঝতে সমস্যা হয়েছে।')
        denied_response = self.client.post(
            reverse('update_class_session_progress', args=[other_year_session.pk]),
            {'is_completed': 'on', 'problem_description': ''},
        )
        self.assertEqual(denied_response.status_code, 404)
        self.assertFalse(ClassSessionProgress.objects.filter(session=other_year_session).exists())

        dashboard = self.client.get(reverse('student_dashboard'))

        self.assertEqual(
            [item['session'] for item in dashboard.context['today_study_sessions']],
            [session],
        )
        self.assertContains(dashboard, 'অগ্রগতি সংরক্ষণ')
        self.assertContains(dashboard, 'ক্রস গুণনের ধাপটি বুঝতে সমস্যা হয়েছে।')

        self.client.post(
            reverse('update_class_session_progress', args=[session.pk]),
            {'is_completed': 'on', 'problem_description': 'ক্রস গুণনের ধাপটি বুঝতে সমস্যা হয়েছে।'},
        )
        progress.refresh_from_db()
        self.assertTrue(progress.is_completed)

    def test_student_can_submit_private_feedback(self):
        self.client.force_login(self.student_user)

        response = self.client.post(reverse('student_feedback'), {
            'category': StudentFeedback.Category.TOPIC_HELP,
            'message': 'ভেক্টর অধ্যায়ের ডট গুণন বুঝতে সমস্যা হচ্ছে।',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'তোমার মতামতটি সুপার অ্যাডমিনের কাছে পাঠানো হয়েছে')
        feedback = StudentFeedback.objects.get()
        self.assertEqual(feedback.student, self.student)
        self.assertEqual(feedback.category, StudentFeedback.Category.TOPIC_HELP)
        self.assertEqual(feedback.message, 'ভেক্টর অধ্যায়ের ডট গুণন বুঝতে সমস্যা হচ্ছে।')

    def test_student_feedback_requires_valid_category_and_message(self):
        self.client.force_login(self.student_user)

        response = self.client.post(reverse('student_feedback'), {
            'category': 'invalid-category',
            'message': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StudentFeedback.objects.exists())
        self.assertContains(response, 'মতামতের ধরন')

    def test_student_sees_only_own_results_and_batch_exams(self):
        today = timezone.localdate()
        own_exam = Exam.objects.create(
            title='বিজ্ঞান পরীক্ষা',
            exam_date=today,
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        earlier_exam = Exam.objects.create(
            title='আগের পরীক্ষা',
            exam_date=today - timedelta(days=2),
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        later_exam = Exam.objects.create(
            title='পরের পরীক্ষা',
            exam_date=today + timedelta(days=2),
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        other_exam = Exam.objects.create(
            title='অন্য ব্যাচের পরীক্ষা',
            exam_date=timezone.localdate(),
            class_name=self.other_student.class_name,
            year_group=self.other_student.year_group,
            paper='১ম পত্র',
            chapter='বীজগণিত',
            topic='সমীকরণ',
            total_marks=20,
            created_by=self.teacher,
        )
        ExamResult.objects.create(exam=own_exam, student=self.student, marks=16)
        ExamResult.objects.create(exam=other_exam, student=self.other_student, marks=18)

        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_exams'))
        results_response = self.client.get(reverse('student_results'))

        self.assertContains(response, own_exam.title)
        self.assertNotContains(response, other_exam.title)
        self.assertEqual(
            list(response.context['exams']),
            [earlier_exam, own_exam, later_exam],
        )
        self.assertContains(results_response, own_exam.title)
        self.assertNotContains(results_response, other_exam.title)

    def test_student_routine_materials_statistics_and_results_pages_render(self):
        today = timezone.localdate()
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        exam = Exam.objects.create(
            title='সাপ্তাহিক পরীক্ষা',
            exam_date=today,
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        ExamResult.objects.create(exam=exam, student=self.student, marks=17)
        LearningMaterial.objects.create(
            title='ভেক্টর অধ্যায়ের বই',
            kind=LearningMaterial.Kind.BOOK,
            class_name=self.student.class_name,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            uploaded_by=self.teacher,
            external_url='https://example.com/book',
        )
        ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            date=today,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        self.client.force_login(self.student_user)

        for page_name in (
            'student_routine',
            'student_statistics',
            'student_results',
        ):
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(reverse(page_name)).status_code, 200)

        books_page = self.client.get(reverse('student_materials'), {'kind': LearningMaterial.Kind.BOOK})
        self.assertContains(books_page, 'ভেক্টর অধ্যায়ের বই')
        self.assertContains(books_page, 'পদার্থবিজ্ঞান')

    def test_student_sees_full_routine_for_own_batch_only(self):
        second_teacher = get_user_model().objects.create_user(username='second-teacher')
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
        )
        Routine.objects.create(
            teacher=second_teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.MONDAY,
            start_time=time(11),
            end_time=time(12),
            subject='রসায়ন',
        )
        Routine.objects.create(
            teacher=second_teacher,
            class_name=self.other_student.class_name,
            weekday=Routine.Weekday.TUESDAY,
            start_time=time(13),
            end_time=time(14),
            subject='গণিত',
            year_group=self.other_student.year_group,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_routine'))

        self.assertEqual(len(response.context['routines']), 2)
        self.assertContains(response, 'পদার্থবিজ্ঞান')
        self.assertContains(response, 'রসায়ন')
        self.assertNotContains(response, 'গণিত')

    def test_student_weekly_routine_shows_two_classes_in_separate_columns(self):
        weekday = (timezone.localdate().weekday() + 1) % 7
        first_class = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=weekday,
            start_time=time(15),
            end_time=time(16, 30),
            subject='রসায়ন',
            paper='১ম পত্র',
            chapter='পর্যায় সারণি',
        )
        second_class = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=weekday,
            start_time=time(16, 30),
            end_time=time(18),
            subject='পদার্থবিজ্ঞান',
            paper='২য় পত্র',
            chapter='তড়িৎ',
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_routine'))
        day = next(row for row in response.context['weekday_rows'] if row['weekday'] == weekday)

        self.assertEqual(day['first_class'], first_class)
        self.assertEqual(day['later_classes'], [second_class])
        self.assertContains(response, '১ম ক্লাস')
        self.assertContains(response, '২য় ক্লাস')
        self.assertContains(response, '3:00 অপরাহ্ন–4:30 অপরাহ্ন')
        self.assertContains(response, '4:30 অপরাহ্ন–6:00 অপরাহ্ন')

    def test_student_is_denied_teacher_and_admin_pages(self):
        self.client.force_login(self.student_user)

        self.assertEqual(self.client.get(reverse('exam_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_teachers')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_student_feedback')).status_code, 403)

    def test_student_cannot_download_another_batch_material(self):
        material = LearningMaterial.objects.create(
            title='অন্য ব্যাচের শিট',
            kind=LearningMaterial.Kind.SHEET,
            class_name=self.other_student.class_name,
            year_group=self.other_student.year_group,
            subject='গণিত',
            uploaded_by=self.teacher,
            external_url='https://example.com/sheet',
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('download_material', args=[material.pk]))

        self.assertEqual(response.status_code, 403)

    def test_student_can_open_their_batch_materials(self):
        material = LearningMaterial.objects.create(
            title='ভেক্টর ক্লাস শিট',
            kind=LearningMaterial.Kind.BOOK,
            class_name=self.student.class_name,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            uploaded_by=self.teacher,
            external_url='https://example.com/vector',
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('student_materials'), {'kind': LearningMaterial.Kind.BOOK})

        self.assertContains(response, material.title)
        self.assertContains(response, 'পদার্থবিজ্ঞান')
        self.assertContains(response, 'book-material-card')
        self.assertContains(response, 'target="_blank" rel="noopener noreferrer"')
        self.assertContains(response, 'student-resource-tabs')
        self.assertContains(response, 'আপলোড করা বই</button>')


class TeacherAndSuperAdminPortalTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.temp_media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.teacher = get_user_model().objects.create_user(
            username='teacher',
            password='safe-test-password',
            first_name='রহিম',
            last_name='স্যার',
        )
        UserProfile.objects.create(user=self.teacher, role=UserProfile.Role.TEACHER, phone='01700000000')
        self.superadmin = get_user_model().objects.create_superuser(
            username='admin',
            password='safe-admin-password',
        )
        self.student = Student.objects.create(
            name='আয়েশা রহমান',
            student_id='ST-1024',
            class_name='HSC 2026 · বিজ্ঞান',
        )

    def test_admin_dashboard_shows_only_aggregate_fee_numbers(self):
        StudentFeeRecord.objects.create(
            student=self.student,
            month='2026-09',
            monthly_fee=1000,
            amount_paid=1000,
        )
        owing_student = Student.objects.create(
            name='বকেয়া শিক্ষার্থী',
            student_id='ST-1025',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        StudentFeeRecord.objects.create(
            student=owing_student,
            month='2026-09',
            monthly_fee=5000,
            amount_paid=2000,
        )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fee_paid_students'], 1)
        self.assertEqual(response.context['fee_unpaid_students'], 1)
        self.assertEqual(response.context['fee_total_earned'], 6000)
        self.assertEqual(response.context['fee_total_collected'], 3000)
        self.assertEqual(response.context['fee_total_due'], 3000)
        self.assertContains(response, 'মোট আদায়')
        self.assertContains(response, reverse('admin_student_accounts'))
        self.assertNotContains(response, 'student_fee_submit')
        self.assertNotContains(response, 'এক নজরে পুরো কোচিং')
        self.assertNotContains(response, 'শিক্ষক, শিক্ষার্থী ও ক্লাসের খবর রাখুন।')

    def test_student_accounts_page_is_superadmin_only_and_records_fee(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('admin_student_accounts')).status_code, 403)

        self.client.force_login(self.superadmin)
        response = self.client.get(reverse('admin_student_accounts'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'শিক্ষার্থী অ্যাকাউন্ট')
        self.assertContains(response, self.student.name)

        response = self.client.post(reverse('admin_student_accounts'), {
            'student_fee_submit': '1',
            'student': self.student.pk,
            'month': '2026-10',
            'monthly_fee': '3500',
            'amount_paid': '2000',
            'note': 'আংশিক পরিশোধ',
        })

        self.assertRedirects(response, reverse('admin_student_accounts'))
        fee_record = StudentFeeRecord.objects.get(student=self.student, month='2026-10')
        self.assertEqual(fee_record.due_amount, 1500)
        self.assertEqual(fee_record.recorded_by, self.superadmin)

    def test_current_month_fee_can_be_set_inline_and_is_shown_to_student(self):
        current_month = timezone.localdate().strftime('%Y-%m')
        existing_record = StudentFeeRecord.objects.create(
            student=self.student,
            month=current_month,
            monthly_fee=2500,
            amount_paid=400,
        )
        self.client.force_login(self.superadmin)

        response = self.client.post(reverse('admin_student_accounts'), {
            'student_monthly_fee_submit': '1',
            'student_id': self.student.pk,
            f'monthly_fee_{self.student.pk}-monthly_fee': '3500',
        })

        self.assertRedirects(response, reverse('admin_student_accounts'))
        existing_record.refresh_from_db()
        self.assertEqual(existing_record.monthly_fee, 3500)
        self.assertEqual(existing_record.amount_paid, 400)

        account_page = self.client.get(reverse('admin_student_accounts'))
        self.assertEqual(account_page.context['current_month_estimate'], 3500)
        self.assertEqual(account_page.context['current_month_due_estimate'], 3100)
        self.assertContains(account_page, 'মোট ধার্য')

        student_user = get_user_model().objects.create_user(
            username='fee-student',
            password='safe-test-password',
        )
        UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
        self.student.user = student_user
        self.student.save(update_fields=['user'])
        self.client.force_login(student_user)
        dashboard = self.client.get(reverse('student_dashboard'))

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(
            dashboard.context['student_fee_current_record'].monthly_fee,
            existing_record.monthly_fee,
        )
        self.assertContains(dashboard, 'এই মাসের নির্ধারিত বেতন')

        self.client.force_login(self.teacher)
        teacher_student_detail = self.client.get(
            reverse('student_detail', args=[self.student.pk])
        )
        self.assertEqual(teacher_student_detail.status_code, 200)
        self.assertNotContains(teacher_student_detail, 'বেতন সংক্ষিপ্তসার')

    def test_teacher_can_upload_file_for_students(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('teacher_materials'), {
            'title': 'ভেক্টর ক্লাস শিট',
            'kind': LearningMaterial.Kind.SHEET,
            'year_group': self.student.year_group,
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
            'description': 'আজকের ক্লাসের শিট',
            'file': SimpleUploadedFile('vector.pdf', b'%PDF-1.4 test content', content_type='application/pdf'),
            'external_url': '',
        })

        self.assertRedirects(response, reverse('teacher_materials'))
        material = LearningMaterial.objects.get()
        self.assertTrue(material.file.storage.exists(material.file.name))
        student_user = get_user_model().objects.create_user(username='learner', password='safe-test-password')
        UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
        self.student.user = student_user
        self.student.save(update_fields=['user'])
        self.client.force_login(student_user)
        download = self.client.get(reverse('download_material', args=[material.pk]))

        self.assertEqual(download.status_code, 200)
        self.assertTrue(download['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(b''.join(download.streaming_content), b'%PDF-1.4 test content')

    def test_teacher_materials_page_and_download_are_limited_to_own_uploads(self):
        other_teacher = get_user_model().objects.create_user(
            username='another-teacher',
            password='safe-test-password',
        )
        own_material = LearningMaterial.objects.create(
            title='আমার শিট',
            kind=LearningMaterial.Kind.SHEET,
            subject='পদার্থবিজ্ঞান',
            uploaded_by=self.teacher,
            external_url='https://example.com/own',
        )
        other_material = LearningMaterial.objects.create(
            title='অন্য শিক্ষকের শিট',
            kind=LearningMaterial.Kind.SHEET,
            subject='রসায়ন',
            uploaded_by=other_teacher,
            external_url='https://example.com/other',
        )
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('teacher_materials'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_material.title)
        self.assertNotContains(response, other_material.title)
        self.assertEqual(
            self.client.get(reverse('download_material', args=[own_material.pk])).status_code,
            302,
        )
        self.assertEqual(
            self.client.get(reverse('download_material', args=[other_material.pk])).status_code,
            403,
        )

    def test_teacher_can_record_a_completed_class(self):
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=timezone.localdate().weekday(),
            start_time=time(15),
            end_time=time(16, 30),
            subject='পদার্থবিজ্ঞান',
        )
        self.client.force_login(self.teacher)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'session',
            'session-year_group': self.student.year_group,
            'session-date': timezone.localdate().isoformat(),
            'session-subject': 'পদার্থবিজ্ঞান',
            'session-paper': '১ম পত্র',
            'session-chapter': 'ভেক্টর',
            'session-topic': 'ডট গুণন',
        })

        self.assertRedirects(response, reverse('class_management'))
        session = ClassSession.objects.get()
        self.assertEqual(session.teacher, self.teacher)
        self.assertIsNone(session.start_time)
        self.assertIsNone(session.end_time)
        page = self.client.get(reverse('class_management'))
        self.assertEqual(page.context['monthly_sessions'], 1)
        self.assertNotContains(page, 'session-start_time')
        self.assertNotContains(page, 'session-end_time')

    def test_teacher_cannot_record_a_class_on_a_day_without_a_routine(self):
        today = timezone.localdate()
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=(today.weekday() + 1) % 7,
            start_time=time(15),
            end_time=time(16, 30),
            subject='পদার্থবিজ্ঞান',
        )
        self.client.force_login(self.teacher)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'session',
            'session-year_group': self.student.year_group,
            'session-date': today.isoformat(),
            'session-subject': 'পদার্থবিজ্ঞান',
            'session-paper': '১ম পত্র',
            'session-chapter': 'ভেক্টর',
            'session-topic': 'ডট গুণন',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassSession.objects.exists())
        self.assertContains(response, 'আজকে আপনার কোনো ক্লাস ছিল না।')

    def test_teacher_weekly_routine_shows_only_own_classes_and_empty_weekdays(self):
        own_routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=timezone.localdate().weekday(),
            start_time=time(15),
            end_time=time(16, 30),
            subject='নিজের রসায়ন ক্লাস',
        )
        other_teacher = get_user_model().objects.create_user(username='other-routine-teacher')
        Routine.objects.create(
            teacher=other_teacher,
            class_name='অন্য ব্যাচ',
            weekday=timezone.localdate().weekday(),
            start_time=time(16, 30),
            end_time=time(18),
            subject='অন্য শিক্ষকের ক্লাস',
        )
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('class_management'))

        self.assertContains(response, '১ম ক্লাস')
        self.assertContains(response, '২য় ক্লাস')
        self.assertContains(response, 'নিজের রসায়ন ক্লাস')
        self.assertNotContains(response, 'অন্য শিক্ষকের ক্লাস')
        own_day = next(
            row for row in response.context['weekday_rows']
            if row['weekday'] == own_routine.weekday
        )
        self.assertEqual(own_day['first_class'], own_routine)
        self.assertTrue(all(
            row['first_class'] is None and not row['later_classes']
            for row in response.context['weekday_rows']
            if row['weekday'] != own_routine.weekday
        ))

    def test_superadmin_can_edit_and_delete_routine(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(15),
            end_time=time(16, 30),
            subject='পুরোনো বিষয়',
        )
        self.client.force_login(self.superadmin)

        edit_page = self.client.get(f'{reverse("class_management")}?edit_routine={routine.pk}')
        self.assertEqual(edit_page.status_code, 200)
        self.assertEqual(edit_page.context['editing_routine'], routine)
        update_response = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine_id': routine.pk,
            'routine-teacher': self.teacher.pk,
            'routine-year_group': Routine.YearGroup.SECOND,
            'routine-class_name': self.student.class_name,
            'routine-weekday': Routine.Weekday.SUNDAY,
            'routine-start_time': '15:30',
            'routine-end_time': '17:00',
            'routine-subject': 'পদার্থবিজ্ঞান',
            'routine-paper': '১ম পত্র',
            'routine-chapter': 'ভেক্টর',
            'routine-is_revision': '',
        })
        self.assertRedirects(update_response, reverse('class_management'))
        routine.refresh_from_db()
        self.assertEqual(routine.subject, 'পদার্থবিজ্ঞান')
        self.assertEqual(routine.year_group, Routine.YearGroup.SECOND)
        self.assertEqual(routine.weekday, Routine.Weekday.SUNDAY)
        self.assertEqual(routine.start_time, time(15, 30))
        delete_response = self.client.post(reverse('class_management'), {
            'action': 'delete_routine',
            'routine_id': routine.pk,
        })
        self.assertRedirects(delete_response, reverse('class_management'))
        self.assertFalse(Routine.objects.filter(pk=routine.pk).exists())

    def test_superadmin_routine_is_split_into_year_cards_with_extra_classes(self):
        for index in range(5):
            Routine.objects.create(
                teacher=self.teacher,
                class_name='HSC 1st Year',
                year_group=Routine.YearGroup.FIRST,
                weekday=Routine.Weekday.MONDAY,
                start_time=time(9 + index),
                end_time=time(10 + index),
                subject=f'প্রথম বর্ষের ক্লাস {index + 1}',
            )
        for index in range(3):
            Routine.objects.create(
                teacher=self.teacher,
                class_name='HSC 2nd Year',
                year_group=Routine.YearGroup.SECOND,
                weekday=Routine.Weekday.MONDAY,
                start_time=time(14 + index),
                end_time=time(15 + index),
                subject=f'দ্বিতীয় বর্ষের ক্লাস {index + 1}',
            )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('class_management'))

        self.assertEqual(response.status_code, 200)
        year_groups = response.context['year_routine_groups']
        self.assertEqual([group['key'] for group in year_groups], ['first', 'second'])
        self.assertEqual([group['class_count'] for group in year_groups], [5, 3])
        self.assertContains(response, '১ম বর্ষ')
        self.assertContains(response, '২য় বর্ষ')
        self.assertContains(response, 'অতিরিক্ত ক্লাস')
        self.assertContains(response, '5টি ক্লাস')
        self.assertContains(response, '3টি ক্লাস')

    def test_legacy_routine_without_year_defaults_to_first_year(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name='HSC 2026 · বিজ্ঞান',
            weekday=Routine.Weekday.MONDAY,
            start_time=time(9),
            end_time=time(10),
            subject='বর্ষ এখনো নির্ধারিত নয়',
        )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('class_management'))

        self.assertEqual(response.status_code, 200)
        first_year_group = next(
            group for group in response.context['year_routine_groups']
            if group['key'] == 'first'
        )
        self.assertEqual(first_year_group['class_count'], 1)
        self.assertEqual(first_year_group['days'][2]['classes'], [routine])
        self.assertNotContains(response, 'বর্ষ নির্ধারণ বাকি')
        self.assertContains(response, 'data-routine-year="first"')
        self.assertContains(response, 'data-routine-year="second"')

    def test_teacher_cannot_edit_or_delete_routine(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(15),
            end_time=time(16, 30),
            subject='শিক্ষকের রুটিন',
        )
        self.client.force_login(self.teacher)

        self.assertEqual(
            self.client.get(f'{reverse("class_management")}?edit_routine={routine.pk}').status_code,
            200,
        )
        response = self.client.post(reverse('class_management'), {
            'action': 'delete_routine',
            'routine_id': routine.pk,
        })

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Routine.objects.filter(pk=routine.pk).exists())

    def test_teacher_can_request_own_attendance_for_today_and_admin_approves_it(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=timezone.localdate().weekday(),
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
        )
        self.client.force_login(self.teacher)

        dashboard = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'আমি উপস্থিত')
        response = self.client.post(reverse('request_teacher_attendance', args=[routine.pk]))

        self.assertRedirects(
            response,
            f"{reverse('teacher_dashboard')}?attendance=pending#today-classes",
            fetch_redirect_response=False,
        )
        record = TeacherAttendance.objects.get(teacher=self.teacher)
        self.assertEqual(record.status, TeacherAttendance.Status.PENDING)
        self.assertEqual(
            TeacherAttendance.objects.filter(
                teacher=self.teacher,
                status=TeacherAttendance.Status.APPROVED,
            ).count(),
            0,
        )

        self.client.force_login(self.superadmin)
        review = self.client.post(reverse('admin_teacher_attendance'), {
            'action': 'approve',
            'record_id': record.pk,
            'date': record.date.isoformat(),
        })

        self.assertEqual(review.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.status, TeacherAttendance.Status.APPROVED)
        self.assertEqual(record.reviewed_by, self.superadmin)
        self.assertEqual(
            TeacherAttendance.objects.filter(
                teacher=self.teacher,
                status=TeacherAttendance.Status.APPROVED,
            ).count(),
            1,
        )

    def test_teacher_cannot_request_attendance_without_own_class_or_override_existing(self):
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=timezone.localdate().weekday(),
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
        )
        other_teacher = get_user_model().objects.create_user(username='another-teacher')
        other_routine = Routine.objects.create(
            teacher=other_teacher,
            class_name=self.student.class_name,
            weekday=timezone.localdate().weekday(),
            start_time=time(11),
            end_time=time(12),
            subject='রসায়ন',
        )
        self.client.force_login(self.teacher)

        self.assertEqual(
            self.client.post(reverse('request_teacher_attendance', args=[other_routine.pk])).status_code,
            404,
        )
        final_record = TeacherAttendance.objects.create(
            teacher=self.teacher,
            routine=routine,
            date=timezone.localdate(),
            status=TeacherAttendance.Status.APPROVED,
            reviewed_by=self.superadmin,
            reviewed_at=timezone.now(),
        )
        response = self.client.post(reverse('request_teacher_attendance', args=[routine.pk]))

        self.assertEqual(response.status_code, 302)
        final_record.refresh_from_db()
        self.assertEqual(final_record.status, TeacherAttendance.Status.APPROVED)
        self.assertEqual(TeacherAttendance.objects.filter(teacher=self.teacher).count(), 1)

    def test_superadmin_can_directly_record_teacher_presence(self):
        self.client.force_login(self.superadmin)

        page = self.client.get(reverse('admin_teacher_attendance'))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'সরাসরি উপস্থিতি নথিভুক্ত করুন')
        response = self.client.post(reverse('admin_teacher_attendance'), {
            'action': 'mark',
            'teacher_id': self.teacher.pk,
            'status': 'present',
            'date': timezone.localdate().isoformat(),
        })

        self.assertEqual(response.status_code, 302)
        record = TeacherAttendance.objects.get(teacher=self.teacher)
        self.assertEqual(record.status, TeacherAttendance.Status.APPROVED)
        self.assertEqual(record.reviewed_by, self.superadmin)
        self.assertIsNone(record.routine)

    def test_teacher_cannot_add_or_change_routine_but_can_view_own(self):
        own_routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
        )
        other_teacher = get_user_model().objects.create_user(username='another-teacher')
        other_routine = Routine.objects.create(
            teacher=other_teacher,
            class_name='অন্য ব্যাচ',
            weekday=Routine.Weekday.SUNDAY,
            start_time=time(11),
            end_time=time(12),
            subject='রসায়ন',
        )
        self.client.force_login(self.teacher)

        page = self.client.get(reverse('class_management'))
        denied = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine-teacher': self.teacher.pk,
            'routine-class_name': 'HSC 2026 · বিজ্ঞান',
            'routine-weekday': Routine.Weekday.SUNDAY,
            'routine-start_time': '11:00',
            'routine-end_time': '12:00',
            'routine-subject': 'রসায়ন',
        })

        self.assertEqual(page.status_code, 200)
        self.assertEqual(list(page.context['routines']), [own_routine])
        self.assertNotContains(page, 'রুটিন সংরক্ষণ করুন')
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(Routine.objects.filter(subject='রসায়ন', teacher=self.teacher).exists())
        self.assertTrue(Routine.objects.filter(pk=other_routine.pk).exists())

    def test_superadmin_can_create_routine_for_selected_teacher(self):
        self.client.force_login(self.superadmin)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine-teacher': self.teacher.pk,
            'routine-year_group': Routine.YearGroup.FIRST,
            'routine-class_name': self.student.class_name,
            'routine-weekday': Routine.Weekday.SATURDAY,
            'routine-start_time': '15:00',
            'routine-end_time': '16:30',
            'routine-subject': 'পদার্থবিজ্ঞান',
            'routine-paper': '১ম পত্র',
            'routine-chapter': 'ভেক্টর',
            'routine-is_revision': '',
        })

        self.assertRedirects(response, reverse('class_management'))
        routine = Routine.objects.get()
        self.assertEqual(routine.teacher, self.teacher)
        self.assertEqual(routine.year_group, Routine.YearGroup.FIRST)
        self.assertFalse(routine.is_revision)
        self.assertContains(self.client.get(reverse('class_management')), 'রুটিনে ক্লাস যোগ করুন')

    def test_revision_routine_form_sets_revision_and_requires_ninety_minutes(self):
        self.client.force_login(self.superadmin)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine-teacher': self.teacher.pk,
            'routine-year_group': Routine.YearGroup.SECOND,
            'routine-class_name': self.student.class_name,
            'routine-weekday': Routine.Weekday.SATURDAY,
            'routine-start_time': '14:00',
            'routine-end_time': '15:30',
            'routine-subject': 'পদার্থবিজ্ঞান',
            'routine-paper': '১ম পত্র',
            'routine-chapter': 'ভেক্টর',
            'routine-is_revision': 'on',
        })

        self.assertRedirects(response, reverse('class_management'))
        routine = Routine.objects.get()
        self.assertTrue(routine.is_revision)
        self.assertEqual(routine.year_group, Routine.YearGroup.SECOND)

    def test_routine_form_rejects_invalid_class_time_window_and_duration(self):
        self.client.force_login(self.superadmin)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine-teacher': self.teacher.pk,
            'routine-year_group': Routine.YearGroup.FIRST,
            'routine-class_name': self.student.class_name,
            'routine-weekday': Routine.Weekday.SATURDAY,
            'routine-start_time': '14:00',
            'routine-end_time': '15:00',
            'routine-subject': 'পদার্থবিজ্ঞান',
            'routine-paper': '১ম পত্র',
            'routine-chapter': 'ভেক্টর',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('start_time', response.context['routine_form'].errors)
        self.assertIn('end_time', response.context['routine_form'].errors)
        self.assertFalse(Routine.objects.exists())

    def test_superadmin_must_select_a_year_when_creating_routine(self):
        self.client.force_login(self.superadmin)

        response = self.client.post(reverse('class_management'), {
            'form_type': 'routine',
            'routine-teacher': self.teacher.pk,
            'routine-class_name': self.student.class_name,
            'routine-weekday': Routine.Weekday.SATURDAY,
            'routine-start_time': '09:00',
            'routine-end_time': '10:00',
            'routine-subject': 'পদার্থবিজ্ঞান',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('year_group', response.context['routine_form'].errors)
        self.assertFalse(Routine.objects.exists())

    def test_routine_subject_paper_chapter_are_dependent_dropdowns(self):
        form = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.SUNDAY,
            'is_revision': '',
            'start_time': '15:00',
            'end_time': '16:30',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields['subject'].widget.__class__.__name__, 'Select')
        self.assertIn('১ম পত্র', dict(form.fields['paper'].choices))
        self.assertIn('ভেক্টর', dict(form.fields['chapter'].choices))
        self.assertNotIn('তাপগতিবিদ্যা', dict(form.fields['chapter'].choices))

    def test_routine_time_fields_use_easy_quarter_hour_dropdowns(self):
        form = RoutineForm()

        self.assertEqual(form.fields['start_time'].widget.__class__.__name__, 'Select')
        self.assertEqual(form.fields['end_time'].widget.__class__.__name__, 'Select')
        self.assertIn('14:15', dict(form.fields['start_time'].widget.choices))
        self.assertIn('17:30', dict(form.fields['start_time'].widget.choices))
        self.assertIn('16:45', dict(form.fields['end_time'].widget.choices))

    def test_friday_routine_must_fit_between_nine_and_noon(self):
        valid_form = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.FRIDAY,
            'is_revision': '',
            'start_time': '10:30',
            'end_time': '12:00',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
        })
        invalid_form = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.FRIDAY,
            'is_revision': '',
            'start_time': '10:45',
            'end_time': '12:15',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
        })

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn('start_time', invalid_form.errors)

    def test_routine_rejects_chapter_from_another_paper(self):
        form = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.SUNDAY,
            'is_revision': '',
            'start_time': '15:00',
            'end_time': '16:30',
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'তাপগতিবিদ্যা',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('chapter', form.errors)

    def test_subject_paper_chapter_dropdowns_share_choices_across_teaching_forms(self):
        forms = [
            RoutineForm(),
            ClassSessionForm(),
            LearningMaterialForm(),
        ]
        for form in forms:
            with self.subTest(form=form.__class__.__name__):
                self.assertEqual(form.fields['subject'].widget.__class__.__name__, 'Select')
                self.assertEqual(form.fields['paper'].widget.__class__.__name__, 'Select')
                self.assertEqual(form.fields['chapter'].widget.__class__.__name__, 'Select')
                self.assertIn('উচ্চতর গণিত', dict(form.fields['subject'].choices))
                self.assertIn('তথ্য ও যোগাযোগ প্রযুক্তি', dict(form.fields['subject'].choices))
                self.assertIn('ইংরেজি', dict(form.fields['subject'].choices))

        chemistry = ClassSessionForm(data={
            'subject': 'রসায়ন',
            'paper': '২য় পত্র',
            'chapter': 'জৈব রসায়ন',
        })
        self.assertEqual(
            chemistry.fields['topic'].widget.__class__.__name__,
            'Textarea',
        )
        self.assertIn('জৈব রসায়ন', dict(chemistry.fields['chapter'].choices))
        self.assertNotIn('মৌলের পর্যায়বৃত্ত ধর্ম ও রাসায়নিক বন্ধন', dict(chemistry.fields['chapter'].choices))

        ict = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.SUNDAY,
            'is_revision': '',
            'start_time': '15:00',
            'end_time': '16:30',
            'subject': 'তথ্য ও যোগাযোগ প্রযুক্তি',
            'paper': 'একাদশ-দ্বাদশ শ্রেণি',
            'chapter': 'প্রোগ্রামিং ভাষা',
        })
        english = RoutineForm(data={
            'teacher': self.teacher.pk,
            'year_group': Routine.YearGroup.FIRST,
            'weekday': Routine.Weekday.SUNDAY,
            'is_revision': '',
            'start_time': '15:00',
            'end_time': '16:30',
            'subject': 'ইংরেজি',
            'paper': '২য় পত্র',
            'chapter': 'Grammar',
        })
        self.assertTrue(ict.is_valid(), ict.errors)
        self.assertTrue(english.is_valid(), english.errors)

    def test_superadmin_can_create_teacher_and_view_monthly_activity(self):
        today = timezone.localdate()
        Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=Routine.Weekday.SATURDAY,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            date=today,
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
        )
        Exam.objects.create(
            title='সাপ্তাহিক পরীক্ষা',
            exam_date=today,
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        self.client.force_login(self.superadmin)
        month = f'{today.year:04d}-{today.month:02d}'
        response = self.client.get(f'{reverse("admin_teachers")}?month={month}')

        self.assertContains(response, 'রহিম স্যার')
        self.assertContains(response, 'ভেক্টর')
        self.assertEqual(response.context['teachers'][0]['class_count'], 1)
        self.assertEqual(response.context['teachers'][0]['exam_count'], 1)
        self.assertEqual(response.context['teachers'][0]['year_stats'][0]['class_count'], 1)
        teacher_summary = response.content.decode().split('</summary>', 1)[0]
        self.assertIn('<details class="panel teacher-report-card">', teacher_summary)
        self.assertIn('teacher-report-summary', teacher_summary)
        self.assertIn('রহিম স্যার', teacher_summary)
        self.assertIn('>1</strong>', teacher_summary)
        self.assertNotIn('teacher ·', teacher_summary)
        self.assertNotIn('অনুমোদিত উপস্থিতি', teacher_summary)
        self.assertContains(response, 'teacher · 01700000000')

        create_response = self.client.post(reverse('admin_teachers'), {
            'first_name': 'করিম',
            'last_name': 'স্যার',
            'username': 'karim',
            'email': 'karim@example.com',
            'phone': '01800000000',
            'password': 'A-valid-test-pass-123',
        })
        self.assertRedirects(create_response, reverse('admin_teachers'))
        self.assertTrue(UserProfile.objects.filter(user__username='karim', role=UserProfile.Role.TEACHER).exists())

    def test_superadmin_can_update_teacher_information_and_optional_password(self):
        self.client.force_login(self.superadmin)
        edit_url = reverse('admin_teacher_edit', args=[self.teacher.pk])

        self.assertEqual(self.client.get(edit_url).status_code, 200)
        response = self.client.post(edit_url, {
            'first_name': 'করিম',
            'last_name': 'স্যার',
            'username': 'karim-teacher',
            'email': 'karim@example.com',
            'phone': '01800000000',
            'password': '',
        })

        self.assertRedirects(response, reverse('admin_teachers'))
        self.teacher.refresh_from_db()
        self.teacher.profile.refresh_from_db()
        self.assertEqual(self.teacher.get_full_name(), 'করিম স্যার')
        self.assertEqual(self.teacher.username, 'karim-teacher')
        self.assertEqual(self.teacher.email, 'karim@example.com')
        self.assertEqual(self.teacher.profile.phone, '01800000000')
        self.assertTrue(self.teacher.check_password('safe-test-password'))

    def test_superadmin_can_delete_teacher_and_dependent_records_safely(self):
        today = timezone.localdate()
        routine = Routine.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            weekday=today.weekday(),
            start_time=time(15),
            end_time=time(16, 30),
            subject='পদার্থবিজ্ঞান',
            year_group=Routine.YearGroup.FIRST,
        )
        session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            date=today,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
        )
        TeacherAttendance.objects.create(
            teacher=self.teacher,
            routine=routine,
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        exam = Exam.objects.create(
            title='সাপ্তাহিক পরীক্ষা',
            exam_date=today,
            class_name=self.student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.teacher,
        )
        ExamResult.objects.create(exam=exam, student=self.student, marks=18)
        self.client.force_login(self.superadmin)
        delete_url = reverse('admin_teacher_delete', args=[self.teacher.pk])

        self.assertEqual(self.client.get(delete_url).status_code, 405)
        response = self.client.post(delete_url)

        self.assertRedirects(response, reverse('admin_teachers'))
        self.assertFalse(get_user_model().objects.filter(pk=self.teacher.pk).exists())
        self.assertFalse(Routine.objects.filter(pk=routine.pk).exists())
        self.assertFalse(ClassSession.objects.filter(pk=session.pk).exists())
        self.assertFalse(TeacherAttendance.objects.filter(teacher_id=self.teacher.pk).exists())
        exam.refresh_from_db()
        self.assertIsNone(exam.created_by)
        self.assertTrue(ExamResult.objects.filter(exam=exam, student=self.student).exists())

    def test_superadmin_teacher_report_groups_class_exam_and_approved_days_by_year(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        for index, (year_name, day, year_group) in enumerate((
            ('HSC 1st Year · Science', month_start, Routine.YearGroup.FIRST),
            ('HSC 2nd Year · Science', month_start + timedelta(days=1), Routine.YearGroup.SECOND),
        ), start=1):
            routine = Routine.objects.create(
                teacher=self.teacher,
                class_name=year_name,
                year_group=year_group,
                weekday=day.weekday(),
                start_time=time(9),
                end_time=time(10),
                subject=f'বিষয় {index}',
            )
            ClassSession.objects.create(
                teacher=self.teacher,
                class_name=year_name,
                year_group=year_group,
                date=day,
                subject=f'বিষয় {index}',
                chapter=f'অধ্যায় {index}',
            )
            Exam.objects.create(
                title=f'পরীক্ষা {index}',
                exam_date=day,
                class_name=year_name,
                year_group=year_group,
                paper='১ম পত্র',
                chapter=f'অধ্যায় {index}',
                topic='টপিক',
                total_marks=20,
                created_by=self.teacher,
            )
            TeacherAttendance.objects.create(
                teacher=self.teacher,
                routine=routine,
                date=day,
                status=TeacherAttendance.Status.APPROVED,
            )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('admin_teachers'), {'month': f'{today:%Y-%m}'})

        year_stats = {
            item['key']: item
            for item in response.context['teachers'][0]['year_stats']
        }
        self.assertEqual(year_stats['first']['session_count'], 1)
        self.assertEqual(year_stats['first']['exam_count'], 1)
        self.assertEqual(year_stats['first']['attendance_count'], 1)
        self.assertEqual(year_stats['second']['session_count'], 1)
        self.assertEqual(year_stats['second']['exam_count'], 1)
        self.assertEqual(year_stats['second']['attendance_count'], 1)
        self.assertContains(response, '১ম বর্ষ')
        self.assertContains(response, '২য় বর্ষ')

    def test_superadmin_dashboard_shows_coaching_wide_totals(self):
        ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            date=timezone.localdate(),
            start_time=time(9),
            end_time=time(10),
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['teacher_count'], 1)
        self.assertEqual(response.context['class_count'], 1)
        self.assertContains(response, 'সার্বিক ড্যাশবোর্ড')

    def test_superadmin_dashboard_shows_today_study_completion_and_student_problems(self):
        today = timezone.localdate()
        session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            year_group=self.student.year_group,
            date=today,
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        progress_students = []
        for username, name in (('progress-one', 'প্রগতি এক'), ('progress-two', 'প্রগতি দুই')):
            user = get_user_model().objects.create_user(username=username, password='safe-password')
            UserProfile.objects.create(user=user, role=UserProfile.Role.STUDENT)
            progress_students.append(Student.objects.create(
                user=user,
                name=name,
                student_id=f'ST-{username}',
                class_name=self.student.class_name,
                year_group=self.student.year_group,
            ))
        ClassSessionProgress.objects.create(
            session=session,
            student=progress_students[0],
            is_completed=True,
            problem_description='ভেক্টরের দিক নির্ণয়ে সমস্যা হয়েছে।',
        )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('admin_dashboard'))

        session_report = response.context['today_study_sessions'][0]
        self.assertEqual(session_report.eligible_student_count, 2)
        self.assertEqual(session_report.completed_student_count, 1)
        self.assertEqual(session_report.not_completed_student_count, 1)
        self.assertContains(response, 'ভেক্টরের দিক নির্ণয়ে সমস্যা হয়েছে।')
        self.assertContains(response, 'জন সম্পন্ন')
        self.assertContains(response, 'জন এখনো সম্পন্ন হিসেবে চিহ্নিত নয়')
        self.assertEqual(response.context['study_report_page'].paginator.count, 1)
        self.assertEqual(response.context['study_report_date'], today)

    def test_superadmin_study_progress_date_filter_limits_class_reports_to_selected_day(self):
        today = timezone.localdate()
        today_session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            year_group=self.student.year_group,
            date=today,
            subject='আজকের পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            year_group=self.student.year_group,
            date=today - timedelta(days=1),
            subject='গতকালের রসায়ন',
            chapter='জৈব রসায়ন',
        )
        self.client.force_login(self.superadmin)

        response = self.client.get(reverse('admin_dashboard'), {
            'study_date': today.isoformat(),
        })

        self.assertEqual(
            [session.pk for session in response.context['today_study_sessions']],
            [today_session.pk],
        )
        self.assertContains(response, 'আজকের পদার্থবিজ্ঞান')
        self.assertNotContains(response, 'গতকালের রসায়ন')
        self.assertEqual(response.context['study_report_date'], today)

    def test_superadmin_study_progress_paginates_student_submissions(self):
        today = timezone.localdate()
        session = ClassSession.objects.create(
            teacher=self.teacher,
            class_name=self.student.class_name,
            year_group=self.student.year_group,
            date=today,
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        for index in range(16):
            user = get_user_model().objects.create_user(
                username=f'page-student-{index}',
                password='safe-password',
            )
            UserProfile.objects.create(user=user, role=UserProfile.Role.STUDENT)
            student = Student.objects.create(
                user=user,
                name=f'পৃষ্ঠা শিক্ষার্থী {index:02d}',
                student_id=f'ST-PAGE-{index:03d}',
                class_name=self.student.class_name,
                year_group=self.student.year_group,
            )
            ClassSessionProgress.objects.create(
                session=session,
                student=student,
                is_completed=index % 2 == 0,
                problem_description=f'সমস্যা {index}' if index % 2 else '',
            )
        self.client.force_login(self.superadmin)

        first_page = self.client.get(reverse('admin_dashboard'), {
            'study_date': today.isoformat(),
        })
        second_page = self.client.get(reverse('admin_dashboard'), {
            'study_date': today.isoformat(),
            'study_page': 2,
        })

        self.assertEqual(first_page.context['study_report_page'].paginator.count, 16)
        self.assertEqual(len(first_page.context['study_report_page'].object_list), 15)
        self.assertTrue(first_page.context['study_report_page'].has_next())
        self.assertEqual(second_page.context['study_report_page'].number, 2)
        self.assertFalse(second_page.context['study_report_page'].has_next())
        self.assertEqual(
            len(first_page.context['today_study_sessions'][0].progress_reports),
            15,
        )
        self.assertContains(first_page, 'পৃষ্ঠা 1 / 2')

    def test_teacher_can_join_support_session_and_duplicate_joins_count_once_per_day(self):
        self.client.force_login(self.teacher)

        first_response = self.client.post(reverse('join_support_session'))
        second_response = self.client.post(reverse('join_support_session'))

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(first_response['Location'], 'https://meet.google.com/nbd-ibgk-euz')
        self.assertEqual(second_response['Location'], 'https://meet.google.com/nbd-ibgk-euz')
        self.assertEqual(
            SupportSessionAttendance.objects.filter(
                teacher=self.teacher,
                date=timezone.localdate(),
            ).count(),
            1,
        )

        dashboard = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(dashboard.context['support_session_days'], 1)
        self.assertTrue(dashboard.context['support_session_joined_today'])
        self.assertContains(dashboard, 'আজ যোগ দিয়েছেন')

    def test_support_session_teacher_report_is_on_teachers_page_not_dashboard(self):
        earlier_date = timezone.localdate() - timedelta(days=1)
        SupportSessionAttendance.objects.create(
            teacher=self.teacher,
            date=earlier_date,
        )
        SupportSessionAttendance.objects.create(
            teacher=self.teacher,
            date=timezone.localdate(),
        )
        self.client.force_login(self.superadmin)

        dashboard = self.client.get(reverse('admin_dashboard'))

        self.assertNotContains(dashboard, 'সাপোর্ট সেশনে শিক্ষকদের যোগদান')
        response = self.client.get(reverse('admin_teachers'))
        teacher_report = next(
            teacher
            for teacher in response.context['support_session_teachers']
            if teacher.pk == self.teacher.pk
        )
        self.assertEqual(teacher_report.support_session_days, 2)
        self.assertEqual(teacher_report.support_session_joined_today, 1)
        self.assertEqual(response.context['support_session_today_joins'], 1)
        self.assertEqual(response.context['support_session_total_joins'], 2)
        self.assertContains(response, 'সাপোর্ট সেশনে শিক্ষকদের যোগদান')
        self.assertContains(response, 'teacher-report-list')

    def test_only_superadmin_can_view_student_feedback(self):
        feedback = StudentFeedback.objects.create(
            student=self.student,
            category=StudentFeedback.Category.BACKUP_CLASS,
            message='বৃহস্পতিবারের ক্লাসটি মিস হয়েছে, একটি ব্যাকআপ ক্লাস দরকার।',
        )
        self.client.force_login(self.teacher)

        self.assertEqual(self.client.get(reverse('admin_student_feedback')).status_code, 403)

        self.client.force_login(self.superadmin)
        response = self.client.get(reverse('admin_student_feedback'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['feedback_count'], 1)
        self.assertContains(response, feedback.student.name)
        self.assertContains(response, feedback.get_category_display())
        self.assertContains(response, feedback.message)

    def test_teacher_cannot_open_superadmin_teacher_directory(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('admin_teachers'))

        self.assertEqual(response.status_code, 403)

    def test_year_groups_are_detected_from_bengali_and_english_class_names(self):
        self.assertEqual(academic_year_key('HSC 1st Year · Science'), 'first')
        self.assertEqual(academic_year_key('এইচএসসি ২য় বর্ষ · বিজ্ঞান'), 'second')
        self.assertEqual(academic_year_key('HSC 2026 · বিজ্ঞান'), 'other')


class AccountSettingsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.teacher = user_model.objects.create_user(
            username='account-teacher',
            password='Initial-test-password-42!',
            first_name='Rahim',
            last_name='Teacher',
            email='rahim@example.com',
        )
        self.teacher_profile = UserProfile.objects.create(
            user=self.teacher,
            role=UserProfile.Role.TEACHER,
            phone='01700000000',
        )
        self.student_user = user_model.objects.create_user(
            username='account-student',
            password='Initial-test-password-42!',
            email='student@example.com',
        )
        UserProfile.objects.create(user=self.student_user, role=UserProfile.Role.STUDENT)
        self.student = Student.objects.create(
            user=self.student_user,
            name='Student Name',
            student_id='ACCOUNT-1',
            class_name='HSC 2026',
            phone='01800000000',
        )

    def test_account_menu_and_profile_are_available_to_authenticated_users(self):
        self.client.force_login(self.teacher)

        dashboard = self.client.get(reverse('teacher_dashboard'))
        profile = self.client.get(reverse('account_profile'))
        password_page = self.client.get(reverse('account_password'))

        self.assertContains(dashboard, 'account-menu-toggle')
        self.assertContains(dashboard, 'নিজের তথ্য')
        self.assertContains(dashboard, 'পাসওয়ার্ড পরিবর্তন')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(password_page.status_code, 200)
        self.assertNotContains(profile, 'name="role"')

    def test_teacher_can_update_personal_details_without_changing_role(self):
        self.client.force_login(self.teacher)

        response = self.client.post(reverse('account_profile'), {
            'first_name': 'Updated',
            'last_name': 'Teacher',
            'email': 'updated@example.com',
            'phone': '01911112222',
            'role': UserProfile.Role.STUDENT,
        })

        self.assertRedirects(response, reverse('account_profile'))
        self.teacher.refresh_from_db()
        self.teacher_profile.refresh_from_db()
        self.assertEqual(self.teacher.first_name, 'Updated')
        self.assertEqual(self.teacher.email, 'updated@example.com')
        self.assertEqual(self.teacher_profile.phone, '01911112222')
        self.assertEqual(self.teacher_profile.role, UserProfile.Role.TEACHER)

    def test_student_can_update_own_details_but_not_role_or_student_id(self):
        self.client.force_login(self.student_user)

        response = self.client.post(reverse('account_profile'), {
            'student_name': 'Updated Student',
            'email': 'updated-student@example.com',
            'phone': '01922223333',
            'role': UserProfile.Role.TEACHER,
            'student_id': 'CHANGED-ID',
        })

        self.assertRedirects(response, reverse('account_profile'))
        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.student_user.profile.refresh_from_db()
        self.assertEqual(self.student.name, 'Updated Student')
        self.assertEqual(self.student.phone, '01922223333')
        self.assertEqual(self.student.student_id, 'ACCOUNT-1')
        self.assertEqual(self.student_user.email, 'updated-student@example.com')
        self.assertEqual(self.student_user.profile.role, UserProfile.Role.STUDENT)

    def test_password_change_validates_old_password_and_keeps_session_active(self):
        self.client.force_login(self.teacher)

        invalid_response = self.client.post(reverse('account_password'), {
            'old_password': 'wrong-password',
            'new_password1': 'New-secure-password-55!',
            'new_password2': 'New-secure-password-55!',
        })
        self.assertEqual(invalid_response.status_code, 200)
        self.assertTrue(invalid_response.context['form'].errors)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password('Initial-test-password-42!'))

        valid_response = self.client.post(reverse('account_password'), {
            'old_password': 'Initial-test-password-42!',
            'new_password1': 'New-secure-password-55!',
            'new_password2': 'New-secure-password-55!',
        })

        self.assertRedirects(valid_response, reverse('account_password'))
        self.assertEqual(self.client.get(reverse('account_profile')).status_code, 200)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.check_password('Initial-test-password-42!'))
        self.assertTrue(self.teacher.check_password('New-secure-password-55!'))
