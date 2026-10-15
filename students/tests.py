from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import Attendance
from attendance.models import Attendance
from exams.models import Exam, ExamResult
from portal.models import (
    ClassSession,
    ClassSessionProgress,
    Routine,
    SupportSessionAttendance,
    TeacherAttendance,
    UserProfile,
)
from .models import Student


class StudentAndDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='teacher', password='safe-test-password')

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, f'{reverse("login")}?next={reverse("dashboard")}')

    def test_teacher_cannot_add_student(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('student_list'), {
            'name': 'আয়েশা রহমান',
            'student_id': 'ST-1024',
            'year_group': 'first',
            'phone': '01700000000',
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(student_id='ST-1024').exists())

    def test_teacher_can_open_student_list(self):
        student = Student.objects.create(
            name='প্রোফাইল লিংক',
            student_id='ST-PROFILE-LINK',
            class_name='১ম বর্ষ',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('student_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'শিক্ষার্থীদের তথ্য দেখুন')
        self.assertNotContains(response, 'শিক্ষার্থী সংরক্ষণ করুন')
        self.assertContains(
            response,
            f'href="{reverse("student_detail", args=[student.pk])}"',
        )

    def test_student_list_shows_selected_students_attendance_calendar(self):
        admin = get_user_model().objects.create_superuser(username='calendar-admin', password='safe-admin-password')
        student = Student.objects.create(
            name='ক্যালেন্ডার শিক্ষার্থী',
            student_id='ST-CALENDAR',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        Attendance.objects.create(
            student=student,
            date=date(2026, 10, 5),
            status=Attendance.Status.ABSENT,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('student_list'), {
            'attendance_student': student.pk,
            'month': '2026-10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['attendance_calendar_student'], student)
        self.assertEqual(response.context['attendance_calendar_counts']['absent'], 1)
        self.assertContains(response, 'attendance-calendar-student')
        self.assertContains(response, 'ক্যালেন্ডার শিক্ষার্থী')

    def test_superadmin_can_add_student(self):
        admin = get_user_model().objects.create_superuser(username='admin', password='safe-admin-password')
        self.client.force_login(admin)

        response = self.client.post(reverse('student_list'), {
            'name': 'আয়েশা রহমান',
            'student_id': 'ST-1024',
            'year_group': 'first',
            'phone': '01700000000',
        })

        self.assertRedirects(response, reverse('student_list'))
        self.assertTrue(Student.objects.filter(student_id='ST-1024').exists())

    def test_student_list_is_paginated_and_search_is_preserved_across_pages(self):
        for index in range(25):
            Student.objects.create(
                name=f'Page Student {index:02d}',
                student_id=f'PAGE-{index:03d}',
                class_name='HSC 2026 · বিজ্ঞান',
            )
        admin = get_user_model().objects.create_superuser(username='admin', password='safe-admin-password')
        self.client.force_login(admin)

        first_page = self.client.get(reverse('student_list'), {'q': 'Page Student'})
        self.assertEqual(first_page.context['page_obj'].paginator.count, 25)
        page_size = first_page.context['page_obj'].paginator.per_page
        self.assertEqual(len(first_page.context['students']), page_size)
        self.assertRegex(
            first_page.content.decode(),
            r'href="\?q=Page(?:\+|%20)Student&amp;page=2"',
        )

        second_page = self.client.get(reverse('student_list'), {
            'q': 'Page Student',
            'page': 2,
        })
        self.assertEqual(second_page.context['page_obj'].number, 2)
        self.assertEqual(len(second_page.context['students']), min(page_size, 25 - page_size))
        self.assertEqual(second_page.context['query'], 'Page Student')
        self.assertContains(second_page, 'aria-current="page">2</span>')

    def test_teacher_can_view_student_attendance_exam_and_progress_details(self):
        student = Student.objects.create(
            name='অগ্রগতির শিক্ষার্থী',
            student_id='ST-DETAIL-1',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        yesterday = timezone.localdate() - timedelta(days=1)
        Attendance.objects.create(student=student, date=yesterday, status=Attendance.Status.PRESENT)
        Attendance.objects.create(
            student=student,
            date=yesterday - timedelta(days=1),
            status=Attendance.Status.ABSENT,
        )
        exam = Exam.objects.create(
            title='পদার্থবিজ্ঞান পরীক্ষা ১',
            exam_date=yesterday,
            class_name=student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=self.user,
        )
        ExamResult.objects.create(exam=exam, student=student, marks=15)
        Exam.objects.create(
            title='অনুপস্থিত পরীক্ষা',
            exam_date=yesterday,
            class_name=student.class_name,
            paper='১ম পত্র',
            chapter='গতিবিদ্যা',
            topic='গতিবিদ্যা',
            total_marks=20,
            created_by=self.user,
        )
        future_exam = Exam.objects.create(
            title='ভবিষ্যৎ পরীক্ষা',
            exam_date=timezone.localdate() + timedelta(days=1),
            class_name=student.class_name,
            paper='১ম পত্র',
            chapter='বল',
            topic='বল',
            total_marks=20,
            created_by=self.user,
        )
        ExamResult.objects.create(exam=future_exam, student=student, marks=18)
        Exam.objects.create(
            title='অন্য বর্ষের পরীক্ষা',
            exam_date=yesterday,
            class_name='২য় বর্ষ',
            year_group='second',
            paper='১ম পত্র',
            chapter='বল',
            topic='বল',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('student_detail', args=[student.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['attended_days'], 1)
        self.assertEqual(response.context['exam_count'], 2)
        self.assertEqual(response.context['exam_taken_count'], 1)
        self.assertEqual(response.context['exam_missed_count'], 1)
        self.assertEqual(len(response.context['exam_results']), 2)
        self.assertContains(response, future_exam.title)
        self.assertContains(response, '18')
        self.assertEqual(response.context['progress_groups'][0]['results'][0]['percentage'], 75)
        self.assertContains(response, 'পত্রভিত্তিক উন্নতি')
        self.assertTrue(
            response.context['attendance_calendar_previous_url'].startswith(
                reverse('student_detail', args=[student.pk]),
            )
        )

    def test_student_can_only_view_own_progress(self):
        student_user = get_user_model().objects.create_user(
            username='student-owner',
            password='safe-student-password',
        )
        own_student = Student.objects.create(
            user=student_user,
            name='নিজের প্রোফাইল',
            student_id='ST-OWN',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        other_student = Student.objects.create(
            name='অন্য প্রোফাইল',
            student_id='ST-OTHER',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
        self.client.force_login(student_user)

        own_response = self.client.get(reverse('student_own_detail'))
        other_response = self.client.get(reverse('student_detail', args=[other_student.pk]))

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response.context['student'], own_student)
        self.assertEqual(other_response.status_code, 403)

    def test_student_profile_is_not_available_to_unprivileged_roles(self):
        student = Student.objects.create(
            name='সুরক্ষিত প্রোফাইল',
            student_id='ST-PRIVATE',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.client.force_login(self.user)
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.STUDENT)

        response = self.client.get(reverse('student_detail', args=[student.pk]))

        self.assertEqual(response.status_code, 403)

    def test_teacher_can_create_login_for_an_existing_student(self):
        student = Student.objects.create(
            name='পুরোনো শিক্ষার্থী',
            student_id='ST-1025',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        admin = get_user_model().objects.create_superuser(username='admin', password='safe-admin-password')
        self.client.force_login(admin)

        response = self.client.post(reverse('student_account', args=[student.pk]), {
            'username': 'existing-student',
            'password': 'A-unique-student-Pass-917!',
        })

        self.assertRedirects(response, reverse('student_account', args=[student.pk]))
        student.refresh_from_db()
        self.assertEqual(student.user.username, 'existing-student')
        self.assertEqual(student.user.profile.role, UserProfile.Role.STUDENT)

    def test_teacher_cannot_create_student_login(self):
        student = Student.objects.create(
            name='পুরোনো শিক্ষার্থী',
            student_id='ST-1026',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse('student_account', args=[student.pk]), {
            'username': 'teacher-created-student',
            'password': 'A-unique-student-Pass-917!',
        })

        self.assertEqual(response.status_code, 403)
        student.refresh_from_db()
        self.assertIsNone(student.user)

    def test_teacher_popup_shows_routine_and_exam_on_non_dashboard_pages(self):
        now = timezone.localtime()
        tomorrow = now.date() + timedelta(days=1)
        Routine.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            weekday=tomorrow.weekday(),
            start_time=time(16),
            end_time=time(17, 30),
            subject='পদার্থবিজ্ঞান',
            year_group=Routine.YearGroup.FIRST,
        )
        exam = Exam.objects.create(
            title='আগামী সপ্তাহের পরীক্ষা',
            exam_date=tomorrow,
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('student_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="teacher-week-notice"')
        self.assertContains(response, 'পদার্থবিজ্ঞান')
        self.assertContains(response, exam.title)
        self.assertNotContains(response, 'teacher-next-class-icon')
        self.assertNotContains(response, 'teacher-week-event-tag')
        self.assertNotContains(response, 'teacher-next-class-link')
        self.assertNotContains(response, 'নিজের উপস্থিতি')
        self.assertNotContains(response, '#today-classes')
        self.assertNotContains(response, 'teacher-month-exam-reminder')
        self.assertEqual(
            {event['kind'] for event in response.context['teacher_popup_events']},
            {'class', 'exam'},
        )

    def test_teacher_popup_only_shows_owned_exams_and_the_next_owned_class(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        second_day = today + timedelta(days=2)
        first_routine = Routine.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            weekday=tomorrow.weekday(),
            start_time=time(15),
            end_time=time(16),
            subject='আমার পরবর্তী ক্লাস',
            year_group=Routine.YearGroup.FIRST,
        )
        Routine.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            weekday=second_day.weekday(),
            start_time=time(15),
            end_time=time(16),
            subject='আমার পরের ক্লাস',
            year_group=Routine.YearGroup.FIRST,
        )
        other_teacher = get_user_model().objects.create_user(
            username='another-teacher',
            password='safe-test-password',
        )
        Routine.objects.create(
            teacher=other_teacher,
            class_name='HSC 1st Year',
            weekday=tomorrow.weekday(),
            start_time=time(17),
            end_time=time(18),
            subject='অন্য শিক্ষকের ক্লাস',
            year_group=Routine.YearGroup.FIRST,
        )
        own_exam = Exam.objects.create(
            title='আমার পরীক্ষা',
            exam_date=tomorrow,
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=self.user,
        )
        other_exam = Exam.objects.create(
            title='অন্য শিক্ষকের পরীক্ষা',
            exam_date=tomorrow,
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=other_teacher,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        popup_events = response.context['teacher_popup_events']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event['title'] for event in popup_events if event['kind'] == 'class'],
            [first_routine.subject],
        )
        self.assertEqual(
            [event['title'] for event in popup_events if event['kind'] == 'exam'],
            [own_exam.title],
        )
        self.assertNotIn(other_exam.title, [event['title'] for event in popup_events])
        self.assertNotIn('অন্য শিক্ষকের ক্লাস', [event['title'] for event in popup_events])

    def test_teacher_popup_is_hidden_when_there_are_no_upcoming_events(self):
        today = timezone.localdate()
        Exam.objects.create(
            title='গত মাসের পরীক্ষা',
            exam_date=(
                today.replace(day=1) - timedelta(days=1)
            ),
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['teacher_month_exam_count'], 0)
        self.assertNotContains(response, 'id="teacher-week-notice"')

    def test_teacher_popup_hides_no_exam_reminder_after_current_month_exam(self):
        today = timezone.localdate()
        Exam.objects.create(
            title='এই মাসের পরীক্ষা',
            exam_date=today,
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=self.user,
        )
        tomorrow = today + timedelta(days=1)
        Routine.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            weekday=tomorrow.weekday(),
            start_time=time(16),
            end_time=time(17, 30),
            subject='পদার্থবিজ্ঞান',
            year_group=Routine.YearGroup.FIRST,
        )
        Exam.objects.create(
            title='সামনের পরীক্ষার ইভেন্ট',
            exam_date=tomorrow,
            class_name='HSC 1st Year',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টর',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.context['teacher_month_exam_count'], 2)
        self.assertNotContains(response, 'এই মাসে এখনো কোনো পরীক্ষা নেননি')
        self.assertEqual(
            {event['kind'] for event in response.context['teacher_popup_events']},
            {'class', 'exam'},
        )
        self.assertContains(response, 'সামনের পরীক্ষার ইভেন্ট')

    def test_teacher_dashboard_shows_todays_student_progress_and_reported_difficulties(self):
        today = timezone.localdate()
        session = ClassSession.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            year_group='first',
            date=today,
            subject='পদার্থবিজ্ঞান',
            chapter='ভেক্টর',
        )
        student_users = []
        for username, name in (('study-one', 'শিক্ষার্থী এক'), ('study-two', 'শিক্ষার্থী দুই')):
            student_user = get_user_model().objects.create_user(
                username=username,
                password='safe-student-password',
            )
            UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
            student_users.append(Student.objects.create(
                user=student_user,
                name=name,
                student_id=f'ST-{username}',
                class_name='HSC 1st Year',
                year_group='first',
            ))
        ClassSessionProgress.objects.create(
            session=session,
            student=student_users[0],
            is_completed=True,
            problem_description='ভেক্টরের মান বের করতে সমস্যা হয়েছে।',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        session_report = response.context['today_study_sessions'][0]
        self.assertEqual(session_report.completed_student_count, 1)
        self.assertEqual(session_report.not_completed_student_count, 1)
        self.assertEqual(session_report.eligible_student_count, 2)
        self.assertEqual(
            [progress.student for progress in session_report.progress_reports],
            [student_users[0]],
        )
        self.assertContains(response, 'ভেক্টরের মান বের করতে সমস্যা হয়েছে।')
        self.assertContains(response, 'শিক্ষার্থী এক')

    def test_teacher_dashboard_shows_support_session_join_days_and_today_status(self):
        today = timezone.localdate()
        SupportSessionAttendance.objects.create(
            teacher=self.user,
            date=today - timedelta(days=1),
        )
        SupportSessionAttendance.objects.create(
            teacher=self.user,
            date=today,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.context['support_session_days'], 2)
        self.assertTrue(response.context['support_session_joined_today'])
        self.assertContains(response, 'মোট যোগদানের দিন')
        self.assertContains(response, 'আবার যোগ দিন')

    def test_teacher_study_progress_filters_by_date_and_paginates_student_reports(self):
        today = timezone.localdate()
        selected_session = ClassSession.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            year_group='first',
            date=today - timedelta(days=1),
            subject='নির্বাচিত দিনের ক্লাস',
            chapter='ভেক্টর',
        )
        ClassSession.objects.create(
            teacher=self.user,
            class_name='HSC 1st Year',
            year_group='first',
            date=today,
            subject='আজকের ক্লাস',
            chapter='বলবিদ্যা',
        )
        for index in range(16):
            student_user = get_user_model().objects.create_user(
                username=f'teacher-report-{index}',
                password='safe-student-password',
            )
            UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
            student = Student.objects.create(
                user=student_user,
                name=f'রিপোর্ট শিক্ষার্থী {index:02d}',
                student_id=f'ST-REPORT-{index:03d}',
                class_name='HSC 1st Year',
                year_group='first',
            )
            ClassSessionProgress.objects.create(
                session=selected_session,
                student=student,
                is_completed=index % 2 == 0,
                problem_description=f'সমস্যা {index}' if index % 2 else '',
            )
        self.client.force_login(self.user)

        first_page = self.client.get(reverse('teacher_dashboard'), {
            'study_date': selected_session.date.isoformat(),
        })
        second_page = self.client.get(reverse('teacher_dashboard'), {
            'study_date': selected_session.date.isoformat(),
            'study_page': 2,
        })

        self.assertEqual(first_page.context['study_report_date'], selected_session.date)
        self.assertEqual(
            [session.pk for session in first_page.context['today_study_sessions']],
            [selected_session.pk],
        )
        self.assertEqual(first_page.context['study_report_page'].paginator.count, 16)
        self.assertEqual(len(first_page.context['study_report_page'].object_list), 15)
        self.assertEqual(second_page.context['study_report_page'].number, 2)
        self.assertEqual(len(second_page.context['study_report_page'].object_list), 1)
        self.assertContains(first_page, 'পৃষ্ঠা 1 / 2')
        self.assertContains(second_page, 'রিপোর্ট শিক্ষার্থী 15')
        self.assertNotContains(first_page, 'বলবিদ্যা')

    def test_superadmin_can_edit_student_and_linked_login_information(self):
        student_user = get_user_model().objects.create_user(
            username='student-old',
            password='safe-student-password',
            first_name='পুরোনো নাম',
        )
        UserProfile.objects.create(
            user=student_user,
            role=UserProfile.Role.STUDENT,
            phone='01700000000',
        )
        student = Student.objects.create(
            user=student_user,
            name='পুরোনো নাম',
            student_id='ST-1030',
            class_name='HSC 2026 · বিজ্ঞান',
            phone='01700000000',
        )
        admin = get_user_model().objects.create_superuser(username='admin', password='safe-admin-password')
        self.client.force_login(admin)
        edit_url = reverse('student_edit', args=[student.pk])

        self.assertEqual(self.client.get(edit_url).status_code, 200)
        response = self.client.post(edit_url, {
            'name': 'নতুন নাম',
            'student_id': 'ST-1031',
            'year_group': 'second',
            'phone': '01800000000',
            'username': 'student-new',
            'password': '',
        })

        self.assertRedirects(response, reverse('student_list'))
        student.refresh_from_db()
        student_user.refresh_from_db()
        student_user.profile.refresh_from_db()
        self.assertEqual(student.name, 'নতুন নাম')
        self.assertEqual(student.student_id, 'ST-1031')
        self.assertEqual(student.year_group, 'second')
        self.assertEqual(student.class_name, '২য় বর্ষ')
        self.assertEqual(student_user.first_name, 'নতুন নাম')
        self.assertEqual(student_user.username, 'student-new')
        self.assertEqual(student_user.profile.phone, '01800000000')
        self.assertTrue(student_user.check_password('safe-student-password'))

    def test_superadmin_can_delete_student_account_and_related_records(self):
        student_user = get_user_model().objects.create_user(
            username='student-to-delete',
            password='safe-student-password',
        )
        UserProfile.objects.create(user=student_user, role=UserProfile.Role.STUDENT)
        student = Student.objects.create(
            user=student_user,
            name='মুছে ফেলার শিক্ষার্থী',
            student_id='ST-1032',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        marked_by = get_user_model().objects.create_user(username='attendance-marker')
        attendance = Attendance.objects.create(
            student=student,
            date=timezone.localdate(),
            status=Attendance.Status.PRESENT,
            marked_by=marked_by,
        )
        exam = Exam.objects.create(
            title='সাপ্তাহিক পরীক্ষা',
            exam_date=timezone.localdate(),
            class_name=student.class_name,
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
        )
        result = ExamResult.objects.create(exam=exam, student=student, marks=18)
        admin = get_user_model().objects.create_superuser(username='admin', password='safe-admin-password')
        self.client.force_login(admin)
        delete_url = reverse('student_delete', args=[student.pk])

        self.assertEqual(self.client.get(delete_url).status_code, 405)
        response = self.client.post(delete_url)

        self.assertRedirects(response, reverse('student_list'))
        self.assertFalse(Student.objects.filter(pk=student.pk).exists())
        self.assertFalse(Attendance.objects.filter(pk=attendance.pk).exists())
        self.assertFalse(ExamResult.objects.filter(pk=result.pk).exists())
        self.assertFalse(get_user_model().objects.filter(pk=student_user.pk).exists())

    def test_teacher_cannot_edit_or_delete_student(self):
        student = Student.objects.create(
            name='শিক্ষার্থী',
            student_id='ST-1033',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse('student_edit', args=[student.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('student_delete', args=[student.pk])).status_code, 403)
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())

    def test_dashboard_renders_for_authenticated_teacher(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'এই মাসে আমার উপস্থিতির হার')
        self.assertContains(response, 'data-teacher-routine-version=')
        self.assertContains(response, reverse('teacher_routine_version'))
        self.assertIsNone(response.context['next_class'])
        self.assertContains(response, 'এই সপ্তাহে কোনো ক্লাস/পরীক্ষা নেই')
        self.assertContains(response, 'কোনো ইভেন্ট নেই')
        self.assertEqual(response.context['year_groups'], (('first', '১ম বর্ষ'), ('second', '২য় বর্ষ')))
        self.assertNotContains(response, 'অন্যান্য')
        self.assertNotContains(response, 'calendar-year-filter')

    def test_teacher_routine_page_checks_for_superadmin_updates(self):
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.TEACHER)
        self.client.force_login(self.user)

        response = self.client.get(reverse('class_management'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-teacher-routine-version=')
        self.assertContains(response, 'teacher-routine-update-refresh')

    def test_next_scheduled_class_appears_in_calendar_without_approved_attendance(self):
        today = timezone.localdate()
        next_day = today + timedelta(days=1)
        routine = Routine.objects.create(
            teacher=self.user,
            class_name='HSC বিজ্ঞান',
            weekday=next_day.weekday(),
            start_time=time(23),
            end_time=time(23, 30),
            subject='পদার্থবিজ্ঞান',
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('teacher_dashboard'),
            {'month': f'{next_day:%Y-%m}'},
        )

        next_class = response.context['next_class']
        self.assertEqual(next_class['routine'], routine)
        self.assertEqual(next_class['date'], next_day)
        self.assertTrue(response.context['calendar_has_events'])
        calendar_day = next(
            day for week in response.context['calendar_weeks'] for day in week
            if day['date'] == next_day
        )
        self.assertEqual(len(calendar_day['classes']), 1)
        self.assertEqual(calendar_day['classes'][0]['status'], 'upcoming')
        self.assertContains(response, 'পরবর্তী')
        self.assertContains(response, 'পদার্থবিজ্ঞান')
        self.assertNotContains(response, 'আপনার ক্লাসের রুটিন শিগগিরই আপডেট করা হবে')

    def test_calendar_marks_completed_running_and_upcoming_classes_with_statuses(self):
        today = timezone.localdate()
        running_routine = Routine.objects.create(
            teacher=self.user,
            class_name='HSC চলমান ব্যাচ',
            weekday=today.weekday(),
            start_time=time(15),
            end_time=time(16, 30),
            subject='চলমান বিষয়',
        )
        completed_routine = Routine.objects.create(
            teacher=self.user,
            class_name='HSC সম্পন্ন ব্যাচ',
            weekday=today.weekday(),
            start_time=time(13),
            end_time=time(14, 30),
            subject='সম্পন্ন বিষয়',
        )
        tomorrow = today + timedelta(days=1)
        upcoming_routine = Routine.objects.create(
            teacher=self.user,
            class_name='HSC পরবর্তী ব্যাচ',
            weekday=tomorrow.weekday(),
            start_time=time(17),
            end_time=time(18, 30),
            subject='পরবর্তী বিষয়',
        )
        TeacherAttendance.objects.create(
            teacher=self.user,
            routine=completed_routine,
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        fixed_now = timezone.make_aware(datetime.combine(today, time(15, 30)))
        self.client.force_login(self.user)

        with patch('students.views.timezone.localtime', return_value=fixed_now):
            response = self.client.get(reverse('teacher_dashboard'))

        calendar_events = {
            event['routine_id']: event
            for week in response.context['calendar_weeks']
            for day in week
            for event in day['classes']
            if event['event_type'] == 'class'
        }
        self.assertEqual(calendar_events[completed_routine.pk]['status'], 'completed')
        self.assertEqual(calendar_events[running_routine.pk]['status'], 'running')
        self.assertEqual(calendar_events[upcoming_routine.pk]['status'], 'upcoming')
        self.assertContains(response, 'সম্পন্ন')
        self.assertContains(response, 'চলমান')
        self.assertContains(response, 'পরবর্তী')

    def test_teacher_exams_are_shown_as_distinct_calendar_events(self):
        today = timezone.localdate()
        exam = Exam.objects.create(
            title='মাসিক পরীক্ষা',
            exam_date=today,
            class_name='HSC বিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ডট গুণন',
            total_marks=20,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        today_in_calendar = next(
            day for week in response.context['calendar_weeks'] for day in week
            if day['date'] == today
        )
        exam_events = [event for event in today_in_calendar['classes'] if event['event_type'] == 'exam']
        self.assertEqual(len(exam_events), 1)
        self.assertEqual(exam_events[0]['title'], exam.title)
        self.assertContains(response, 'calendar-exam')
        self.assertContains(response, 'পরীক্ষা')

    def test_teacher_dashboard_calendar_shows_only_superadmin_approved_attendance_dates(self):
        today = timezone.localdate()
        Routine.objects.create(
            teacher=self.user,
            class_name='HSC বিজ্ঞান',
            weekday=today.weekday(),
            start_time=time(9),
            end_time=time(10, 30),
            subject='পদার্থবিজ্ঞান',
        )
        other_teacher = get_user_model().objects.create_user(username='another-teacher')
        Routine.objects.create(
            teacher=other_teacher,
            class_name='অন্য ব্যাচ',
            weekday=today.weekday(),
            start_time=time(11),
            end_time=time(12),
            subject='রসায়ন',
        )
        own_routine = Routine.objects.get(teacher=self.user)
        TeacherAttendance.objects.create(
            teacher=self.user,
            routine=own_routine,
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        TeacherAttendance.objects.create(
            teacher=self.user,
            routine=own_routine,
            date=today - timedelta(days=1),
            status=TeacherAttendance.Status.PENDING,
        )
        TeacherAttendance.objects.create(
            teacher=other_teacher,
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ক্লাস ক্যালেন্ডার')
        self.assertContains(response, '১ম বর্ষ')
        self.assertNotContains(response, 'অন্য ব্যাচ')
        self.assertContains(response, 'সুপার অ্যাডমিন অনুমোদিত উপস্থিতি')
        scheduled_days = [
            day for week in response.context['calendar_weeks'] for day in week
            if day['classes']
        ]
        self.assertIn(today, [day['date'] for day in scheduled_days])
        today_in_calendar = next(day for day in scheduled_days if day['date'] == today)
        self.assertEqual(today_in_calendar['classes'][0]['class_name'], '১ম বর্ষ')

    def test_teacher_can_navigate_calendar_months(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'), {'month': '2026-01'})

        self.assertEqual(response.context['calendar_month_value'], '2026-01')
        self.assertEqual(response.context['previous_calendar_month'], '2025-12')
        self.assertEqual(response.context['next_calendar_month'], '2026-02')

    def test_three_daily_class_slots_are_shown_and_completed_sessions_are_counted_individually(self):
        today = timezone.localdate()
        class_times = [(time(9), time(10, 30)), (time(11), time(12, 30)), (time(14), time(15, 30))]
        routines = []
        for index, (start_time, end_time) in enumerate(class_times, start=1):
            routines.append(Routine.objects.create(
                teacher=self.user,
                class_name=f'HSC ব্যাচ {index}',
                weekday=today.weekday(),
                start_time=start_time,
                end_time=end_time,
                subject=f'বিষয় {index}',
            ))
            ClassSession.objects.create(
                teacher=self.user,
                class_name=f'HSC ব্যাচ {index}',
                date=today,
                start_time=start_time,
                end_time=end_time,
                subject=f'বিষয় {index}',
                chapter=f'অধ্যায় {index}',
            )
        TeacherAttendance.objects.create(
            teacher=self.user,
            routine=routines[0],
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.context['today_completed_classes'], 3)
        self.assertEqual(response.context['monthly_classes'], 3)
        self.assertIn(response.context['next_class']['routine'], routines)
        today_in_calendar = next(
            day for week in response.context['calendar_weeks'] for day in week
            if day['date'] == today
        )
        self.assertIn(
            routines[0].pk,
            [item['routine_id'] for item in today_in_calendar['classes']],
        )
        self.assertContains(response, 'এই সপ্তাহের ক্লাস ও পরীক্ষা')

    def test_teacher_attendance_chart_uses_only_current_teachers_verified_records(self):
        today = timezone.localdate()
        absent_day = today.replace(day=2) if today.day == 1 else today.replace(day=1)
        student = Student.objects.create(
            name='শিক্ষার্থী',
            student_id='ST-3000',
            class_name='HSC 2026 · বিজ্ঞান',
        )
        Attendance.objects.create(
            student=student,
            date=today,
            status=Attendance.Status.ABSENT,
        )
        TeacherAttendance.objects.create(
            teacher=self.user,
            date=today,
            status=TeacherAttendance.Status.APPROVED,
        )
        TeacherAttendance.objects.create(
            teacher=self.user,
            date=absent_day,
            status=TeacherAttendance.Status.ABSENT,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.context['attendance_rate'], 50)
        self.assertEqual(response.context['month_present'], 1)
        self.assertEqual(response.context['month_absent'], 1)
        self.assertEqual(response.context['chart'][today.day - 1]['present'], 1)
        self.assertEqual(response.context['chart'][today.day - 1]['absent'], 0)
        self.assertContains(response, 'শুধু আপনার যাচাইকৃত উপস্থিতি ও অনুপস্থিতি')
