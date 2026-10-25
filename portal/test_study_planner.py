import json
import os
from datetime import time, timedelta
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .curriculum import CURRICULUM
from .models import (
    Routine,
    StudentChapterProgress,
    StudentScheduleInterval,
    StudentStudyPreference,
    StudyPlanTask,
    TeacherAssignmentProgress,
    TeacherStudyAssignment,
    UserProfile,
    WeeklyStudyPlan,
)
from .study_planner import (
    _limit_daily_intervals,
    _study_candidates,
    generate_weekly_plan,
    reschedule_ai_task,
    week_start_for,
)
from .study_planner_forms import StudentScheduleIntervalForm
from students.models import Student


class StudyPlannerTests(TestCase):
    def setUp(self):
        api_key_patcher = patch.dict(os.environ, {'OPENAI_API_KEY': ''})
        api_key_patcher.start()
        self.addCleanup(api_key_patcher.stop)
        user_model = get_user_model()
        self.teacher = user_model.objects.create_user(
            username='planner-teacher',
            password='test-password',
            first_name='Teacher',
        )
        UserProfile.objects.create(user=self.teacher, role=UserProfile.Role.TEACHER)
        self.student_user = user_model.objects.create_user(
            username='planner-student',
            password='test-password',
        )
        UserProfile.objects.create(user=self.student_user, role=UserProfile.Role.STUDENT)
        self.student = Student.objects.create(
            user=self.student_user,
            name='Planner Student',
            student_id='PL-1001',
            class_name='HSC 2027 Science',
            year_group='first',
        )
        self.other_student = Student.objects.create(
            name='Other Student',
            student_id='PL-1002',
            class_name='HSC 2027 Science',
            year_group='first',
        )
        self.week_start = week_start_for(timezone.localdate())
        self.week_end = self.week_start + timedelta(days=6)
        self.preference = StudentStudyPreference.objects.create(
            student=self.student,
            subjects=['পদার্থবিজ্ঞান'],
            exam_date=self.week_start + timedelta(days=35),
            preferred_study_hours=3,
            session_duration_minutes=60,
            break_duration_minutes=15,
            weekly_target_hours=4,
            rest_days=[6],
        )
        self.physics_paper, chapters = next(iter(CURRICULUM['পদার্থবিজ্ঞান'].items()))
        self.chapter = chapters[0]
        self.next_chapter = chapters[1]
        self.progress = StudentChapterProgress.objects.create(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper=self.physics_paper,
            chapter=self.chapter,
            status=StudentChapterProgress.Status.IN_PROGRESS,
            is_difficult=True,
        )
        self.availability = StudentScheduleInterval.objects.create(
            student=self.student,
            weekday=self.week_start.weekday(),
            kind=StudentScheduleInterval.Kind.AVAILABLE,
            start_time=time(9),
            end_time=time(12),
        )
        StudentScheduleInterval.objects.create(
            student=self.student,
            weekday=self.week_start.weekday(),
            kind=StudentScheduleInterval.Kind.AVAILABLE,
            start_time=time(10),
            end_time=time(13),
        )

    def create_assignment(self, **kwargs):
        values = {
            'teacher': self.teacher,
            'student': self.student,
            'subject': 'পদার্থবিজ্ঞান',
            'paper': self.physics_paper,
            'chapter': self.chapter,
            'task_type': TeacherStudyAssignment.TaskType.HOMEWORK,
            'description': 'ভেক্টর অনুশীলনী',
            'assigned_date': self.week_start,
            'deadline': self.week_end,
            'estimated_duration_minutes': 90,
            'priority': TeacherStudyAssignment.Priority.MANDATORY,
        }
        values.update(kwargs)
        return TeacherStudyAssignment.objects.create(**values)

    def test_schedule_interval_rejects_end_before_start(self):
        form = StudentScheduleIntervalForm({
            'weekday': self.week_start.weekday(),
            'kind': StudentScheduleInterval.Kind.AVAILABLE,
            'start_time': '17:00',
            'end_time': '16:00',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('end_time', form.errors)

    def test_only_selected_unfinished_chapters_are_planned(self):
        candidates = _study_candidates(self.student, ['পদার্থবিজ্ঞান'])
        self.assertEqual(candidates[0]['chapter'], self.chapter)
        self.assertNotIn(self.next_chapter, [candidate['chapter'] for candidate in candidates])
        self.progress.status = StudentChapterProgress.Status.COMPLETED
        self.progress.save(update_fields=['status'])
        candidates = _study_candidates(self.student, ['পদার্থবিজ্ঞান'])
        self.assertNotIn(self.chapter, [candidate['chapter'] for candidate in candidates])
        self.assertEqual(candidates, [])
        StudentChapterProgress.objects.create(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper=self.physics_paper,
            chapter=self.next_chapter,
        )
        candidates = _study_candidates(self.student, ['পদার্থবিজ্ঞান'])
        self.assertEqual([candidate['chapter'] for candidate in candidates], [self.next_chapter])

    def test_daily_study_windows_prioritize_evening_after_seven(self):
        self.assertEqual(
            _limit_daily_intervals([(17 * 60, 22 * 60)], 3 * 60),
            [(19 * 60, 22 * 60)],
        )
        self.assertEqual(
            _limit_daily_intervals(
                [(17 * 60, 19 * 60), (19 * 60, 22 * 60)],
                3 * 60,
                15,
                60,
            ),
            [(19 * 60, 21 * 60 + 15), (17 * 60, 18 * 60)],
        )

    @patch.dict(os.environ, {'AI_PLANNER_ENDPOINT': ''})
    def test_three_daily_hours_are_scheduled_every_day_from_selected_chapters(self):
        StudentScheduleInterval.objects.filter(student=self.student).delete()

        plan, _, generated = generate_weekly_plan(
            self.student,
            self.preference,
            self.week_start,
        )

        self.assertTrue(generated)
        tasks_by_day = {
            day: list(plan.tasks.filter(scheduled_date=day))
            for day in (self.week_start + timedelta(days=offset) for offset in range(7))
        }
        self.assertTrue(all(len(tasks) == 3 for tasks in tasks_by_day.values()))
        self.assertTrue(all(
            sum(task.duration_minutes for task in tasks) == 180
            for tasks in tasks_by_day.values()
        ))
        self.assertEqual(
            {task.chapter for task in plan.tasks.filter(source=StudyPlanTask.Source.AI)},
            {self.chapter},
        )

    def test_setup_updates_saved_availability_and_chapter_progress(self):
        second_interval = StudentScheduleInterval.objects.filter(
            student=self.student,
        ).exclude(pk=self.availability.pk).first()
        self.client.force_login(self.student_user)
        response = self.client.post(reverse('save_study_planner_setup'), {
            'subjects': ['পদার্থবিজ্ঞান'],
            'exam_date': (self.week_start + timedelta(days=40)).isoformat(),
            'preferred_study_hours': '5',
            'intervals-TOTAL_FORMS': '3',
            'intervals-INITIAL_FORMS': '2',
            'intervals-MIN_NUM_FORMS': '0',
            'intervals-MAX_NUM_FORMS': '42',
            'intervals-0-id': str(self.availability.pk),
            'intervals-0-weekday': str(self.week_start.weekday()),
            'intervals-0-kind': 'available',
            'intervals-0-start_time': '09:30',
            'intervals-0-end_time': '12:30',
            'intervals-1-id': str(second_interval.pk),
            'intervals-1-weekday': str(self.week_start.weekday()),
            'intervals-1-kind': 'coaching',
            'intervals-1-start_time': '16:00',
            'intervals-1-end_time': '18:00',
            'intervals-2-weekday': '',
            'intervals-2-kind': 'available',
            'intervals-2-start_time': '',
            'intervals-2-end_time': '',
            'chapters-TOTAL_FORMS': '2',
            'chapters-INITIAL_FORMS': '1',
            'chapters-MIN_NUM_FORMS': '0',
            'chapters-MAX_NUM_FORMS': '100',
            'chapters-0-id': str(self.progress.pk),
            'chapters-0-subject': 'পদার্থবিজ্ঞান',
            'chapters-0-paper': self.physics_paper,
            'chapters-0-chapter': self.chapter,
            'chapters-0-topic': 'ভেক্টরের যোগ',
            'chapters-0-status': 'in_progress',
            'chapters-0-is_difficult': 'on',
            'chapters-0-needs_revision': 'on',
            'chapters-1-subject': '',
            'chapters-1-paper': '',
            'chapters-1-chapter': '',
            'chapters-1-topic': '',
            'chapters-1-status': '',
        })

        self.assertRedirects(response, f"{reverse('legacy_student_study_planner')}?tab=plan")
        saved_intervals = list(
            StudentScheduleInterval.objects.filter(student=self.student).values_list(
                'weekday', 'kind', 'start_time', 'end_time',
            )
        )
        self.assertEqual(len(saved_intervals), 2, saved_intervals)
        self.availability.refresh_from_db()
        self.assertEqual(self.availability.start_time, time(9, 30))
        second_interval.refresh_from_db()
        self.assertEqual(second_interval.kind, StudentScheduleInterval.Kind.COACHING)
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.topic, 'ভেক্টরের যোগ')
        self.assertEqual(
            StudentChapterProgress.objects.filter(student=self.student).count(),
            1,
        )
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.exam_date, self.week_start + timedelta(days=40))
        self.assertEqual(self.preference.preferred_study_hours, 5)

    def test_setup_page_only_asks_for_schedule_subjects_chapters_and_exam(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('legacy_student_study_planner'), {'tab': 'setup'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'প্রতিদিন কত ঘণ্টা পড়তে পারবে?')
        self.assertContains(response, 'পরের পরীক্ষার তারিখ')
        self.assertContains(response, 'প্রতিদিনের রুটিন ও পড়ার সময়')
        self.assertContains(response, '19:00')
        self.assertContains(response, 'যে chapter পড়বে')
        self.assertNotContains(response, 'বিশ্রামের দিন')

    def test_planner_lists_completed_in_progress_and_unstarted_chapters(self):
        self.progress.status = StudentChapterProgress.Status.COMPLETED
        self.progress.save(update_fields=['status'])
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('legacy_student_study_planner'), {
            'tab': 'plan',
        })

        subject_summary = response.context['chapter_progress_summary'][0]
        self.assertIn(self.chapter, [row['chapter'] for row in subject_summary['completed']])
        self.assertNotIn(self.next_chapter, [row['chapter'] for row in subject_summary['not_started']])
        self.assertContains(response, 'কোন chapter পড়া হয়েছে, কোনটা বাকি')

    def test_planner_ajax_navigation_response_contains_planner_root(self):
        self.client.force_login(self.student_user)

        response = self.client.get(
            reverse('legacy_student_study_planner'),
            {'tab': 'setup'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-planner-root')

    def test_study_hours_save_over_ajax_and_remain_prefilled_after_tab_change(self):
        StudentScheduleInterval.objects.filter(student=self.student).delete()
        StudentChapterProgress.objects.filter(student=self.student).delete()
        self.client.force_login(self.student_user)
        form_data = {
            'preferred_study_hours': '6',
            'subjects': ['পদার্থবিজ্ঞান'],
            'exam_date': (self.week_start + timedelta(days=40)).isoformat(),
            'intervals-TOTAL_FORMS': '7',
            'intervals-INITIAL_FORMS': '0',
            'intervals-MIN_NUM_FORMS': '0',
            'intervals-MAX_NUM_FORMS': '42',
            'chapters-TOTAL_FORMS': '1',
            'chapters-INITIAL_FORMS': '0',
            'chapters-MIN_NUM_FORMS': '0',
            'chapters-MAX_NUM_FORMS': '100',
            'chapters-0-subject': '',
            'chapters-0-paper': '',
            'chapters-0-chapter': '',
            'chapters-0-topic': '',
            'chapters-0-status': '',
        }
        for weekday in range(7):
            form_data.update({
                f'intervals-{weekday}-weekday': str(weekday),
                f'intervals-{weekday}-kind': StudentScheduleInterval.Kind.AVAILABLE,
                f'intervals-{weekday}-start_time': '19:00',
                f'intervals-{weekday}-end_time': '23:00',
            })
        response = self.client.post(
            reverse('save_study_planner_setup'),
            form_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['success'])
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.preferred_study_hours, 6)
        setup_page = self.client.get(reverse('legacy_student_study_planner'), {'tab': 'setup'})
        self.assertEqual(setup_page.context['preference_form'].instance.preferred_study_hours, 6)
        saved_evening = StudentScheduleInterval.objects.filter(
            student=self.student,
            kind=StudentScheduleInterval.Kind.AVAILABLE,
            start_time=time(19),
            end_time=time(23),
        )
        self.assertEqual(saved_evening.count(), 7)

    @patch.dict(os.environ, {'AI_PLANNER_ENDPOINT': ''})
    def test_daily_hours_create_a_plan_without_manual_time_windows(self):
        StudentScheduleInterval.objects.filter(student=self.student).delete()
        self.preference.preferred_study_hours = 5
        self.preference.save(update_fields=['preferred_study_hours'])
        self.create_assignment(estimated_duration_minutes=120)

        plan, conflicts, generated = generate_weekly_plan(
            self.student,
            self.preference,
            self.week_start,
        )

        self.assertTrue(generated)
        self.assertTrue(plan.tasks.filter(scheduled_date__isnull=False).exists())
        self.assertLessEqual(
            max(
                sum(task.duration_minutes for task in tasks)
                for tasks in (
                    list(plan.tasks.filter(scheduled_date=day))
                    for day in plan.tasks.values_list('scheduled_date', flat=True).distinct()
                )
            ),
            5 * 60,
        )
        self.assertEqual(conflicts, [])
        self.assertTrue(all(
            task.start_time >= time(19)
            for task in plan.tasks.filter(scheduled_date__isnull=False)
        ))

    def test_calendar_day_filter_shows_only_selected_date(self):
        plan = WeeklyStudyPlan.objects.create(student=self.student, week_start=self.week_start)
        StudyPlanTask.objects.create(
            plan=plan,
            source=StudyPlanTask.Source.AI,
            task_type=TeacherStudyAssignment.TaskType.LEARN,
            subject='পদার্থবিজ্ঞান',
            chapter=self.chapter,
            description='Selected day task',
            scheduled_date=self.week_start,
            duration_minutes=60,
            priority=TeacherStudyAssignment.Priority.NORMAL,
        )
        StudyPlanTask.objects.create(
            plan=plan,
            source=StudyPlanTask.Source.AI,
            task_type=TeacherStudyAssignment.TaskType.LEARN,
            subject='পদার্থবিজ্ঞান',
            chapter=self.chapter,
            description='Other day task',
            scheduled_date=self.week_start + timedelta(days=1),
            duration_minutes=60,
            priority=TeacherStudyAssignment.Priority.NORMAL,
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('legacy_student_study_planner'), {
            'week': self.week_start.isoformat(),
            'tab': 'plan',
            'day': self.week_start.isoformat(),
        })

        self.assertContains(response, 'Selected day task')
        self.assertNotContains(response, 'Other day task')

    def test_completed_task_is_saved_through_ajax(self):
        plan = WeeklyStudyPlan.objects.create(
            student=self.student,
            week_start=self.week_start,
        )
        task = StudyPlanTask.objects.create(
            plan=plan,
            source=StudyPlanTask.Source.AI,
            task_type=TeacherStudyAssignment.TaskType.LEARN,
            subject='পদার্থবিজ্ঞান',
            chapter=self.chapter,
            description='Complete this session',
            scheduled_date=self.week_start,
            start_time=time(19),
            end_time=time(20),
            duration_minutes=60,
            priority=TeacherStudyAssignment.Priority.NORMAL,
        )
        self.client.force_login(self.student_user)

        planner_page = self.client.get(reverse('legacy_student_study_planner'), {
            'week': self.week_start.isoformat(),
        })
        self.assertContains(planner_page, 'name="task_action" value="complete"')

        response = self.client.post(
            reverse('legacy_student_study_planner'),
            {'task_id': str(task.pk), 'task_action': 'complete'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['summary']['completed_count'], 1)
        self.assertEqual(response_data['day']['completed'], 1)
        task.refresh_from_db()
        self.assertEqual(task.status, StudyPlanTask.Status.COMPLETED)
        legacy_response = self.client.post(
            reverse('legacy_student_study_planner'),
            {'task_id': str(task.pk), 'action': 'complete'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(legacy_response.status_code, 409)
        planner_response = self.client.get(reverse('legacy_student_study_planner'), {
            'week': self.week_start.isoformat(),
            'tab': 'plan',
            'day': self.week_start.isoformat(),
        })
        self.assertEqual(planner_response.status_code, 200)

    def test_topic_progress_completes_after_learn_mcq_and_cq_sessions(self):
        plan = WeeklyStudyPlan.objects.create(
            student=self.student,
            week_start=self.week_start,
        )
        tasks = [
            StudyPlanTask.objects.create(
                plan=plan,
                source=StudyPlanTask.Source.AI,
                task_type=task_type,
                subject='পদার্থবিজ্ঞান',
                paper=self.physics_paper,
                chapter=self.chapter,
                topic='ভেক্টরের যোগ',
                description='Topic practice',
                scheduled_date=self.week_start,
                start_time=time(19 + index, 0),
                end_time=time(20 + index, 0),
                duration_minutes=60,
                priority=TeacherStudyAssignment.Priority.NORMAL,
            )
            for index, task_type in enumerate((
                TeacherStudyAssignment.TaskType.LEARN,
                TeacherStudyAssignment.TaskType.MCQ,
                TeacherStudyAssignment.TaskType.CQ,
            ))
        ]
        self.client.force_login(self.student_user)

        for index, task in enumerate(tasks):
            response = self.client.post(
                reverse('legacy_student_study_planner'),
                {'task_id': str(task.pk), 'task_action': 'complete'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
            self.assertEqual(response.status_code, 200)
            progress = StudentChapterProgress.objects.get(
                student=self.student,
                subject='পদার্থবিজ্ঞান',
                paper=self.physics_paper,
                chapter=self.chapter,
                topic='ভেক্টরের যোগ',
            )
            expected_status = (
                StudentChapterProgress.Status.COMPLETED
                if index == len(tasks) - 1
                else StudentChapterProgress.Status.IN_PROGRESS
            )
            self.assertEqual(progress.status, expected_status)

    def test_topic_question_bank_is_paginated(self):
        plan = WeeklyStudyPlan.objects.create(
            student=self.student,
            week_start=self.week_start,
            question_bank=[
                {
                    'subject': 'পদার্থবিজ্ঞান',
                    'paper': self.physics_paper,
                    'chapter': self.chapter,
                    'topic': f'Topic {index}',
                    'questions': [f'Question {index}.{question}' for question in range(5)],
                }
                for index in range(2)
            ],
        )
        self.client.force_login(self.student_user)

        response = self.client.get(reverse('legacy_student_study_planner'), {
            'week': self.week_start.isoformat(),
            'tab': 'questions',
        })

        self.assertContains(response, 'Topic 0')
        self.assertNotContains(response, 'Topic 1')
        self.assertContains(response, 'পরের topic')
        self.assertEqual(response.context['question_page'].paginator.num_pages, 2)

    @patch.dict(os.environ, {'AI_PLANNER_ENDPOINT': ''})
    def test_plan_integrates_assignments_and_schedules_without_overlap(self):
        assignment = self.create_assignment()

        plan, conflicts, generated = generate_weekly_plan(
            self.student,
            self.preference,
            self.week_start,
        )

        tasks = list(plan.tasks.order_by('scheduled_date', 'start_time'))
        self.assertTrue(generated)
        self.assertEqual(conflicts, [])
        teacher_task = next(task for task in tasks if task.source == StudyPlanTask.Source.TEACHER)
        self.assertEqual(teacher_task.assignment, assignment)
        self.assertEqual(teacher_task.priority, TeacherStudyAssignment.Priority.MANDATORY)
        self.assertTrue(any(task.source == StudyPlanTask.Source.AI for task in tasks))
        for task in tasks:
            self.assertIsNotNone(task.scheduled_date)
            self.assertGreater(task.end_time, task.start_time)
            day_start = self.week_start + timedelta(days=task.scheduled_date.weekday())
            self.assertEqual(task.scheduled_date, day_start)
            for other in tasks:
                if task.pk >= other.pk or task.scheduled_date != other.scheduled_date:
                    continue
                self.assertTrue(
                    task.end_time <= other.start_time or other.end_time <= task.start_time,
                )
        self.assertIn('নিয়মভিত্তিক পরিকল্পনা', plan.generation_note)

    def test_batch_assignment_is_independently_planned_for_each_student(self):
        assignment = self.create_assignment(student=None, class_name=self.student.class_name, year_group='first')
        StudentStudyPreference.objects.create(
            student=self.other_student,
            subjects=[],
            preferred_study_hours=2,
            session_duration_minutes=60,
            break_duration_minutes=15,
            weekly_target_hours=4,
            rest_days=[],
        )
        StudentScheduleInterval.objects.create(
            student=self.other_student,
            weekday=self.week_start.weekday(),
            kind=StudentScheduleInterval.Kind.AVAILABLE,
            start_time=time(14),
            end_time=time(17),
        )

        first_plan, _, _ = generate_weekly_plan(self.student, self.preference, self.week_start)
        second_plan, _, _ = generate_weekly_plan(
            self.other_student,
            self.other_student.study_preference,
            self.week_start,
        )

        self.assertTrue(first_plan.tasks.filter(assignment=assignment).exists())
        self.assertTrue(second_plan.tasks.filter(assignment=assignment).exists())

    def test_busy_periods_are_excluded_and_overloaded_assignment_reports_conflict(self):
        self.preference.weekly_target_hours = 2
        self.preference.save(update_fields=['weekly_target_hours'])
        self.student.study_schedule_intervals.create(
            weekday=self.week_start.weekday(),
            kind=StudentScheduleInterval.Kind.COLLEGE,
            start_time=time(9, 30),
            end_time=time(11),
        )
        self.create_assignment(estimated_duration_minutes=150)
        Routine.objects.create(
            teacher=self.teacher,
            class_name='HSC',
            year_group='first',
            weekday=self.week_start.weekday(),
            start_time=time(12),
            end_time=time(13),
            subject='পদার্থবিজ্ঞান',
        )
        for weekday in range(7):
            StudentScheduleInterval.objects.create(
                student=self.student,
                weekday=weekday,
                kind=StudentScheduleInterval.Kind.COACHING,
                start_time=time(19),
                end_time=time(23),
            )

        plan, conflicts, _ = generate_weekly_plan(
            self.student,
            self.preference,
            self.week_start,
        )

        teacher_task = plan.tasks.get(source=StudyPlanTask.Source.TEACHER)
        self.assertIsNone(teacher_task.scheduled_date)
        self.assertTrue(any('বসানো যায়নি' in conflict for conflict in conflicts))
        self.assertFalse(plan.tasks.filter(source=StudyPlanTask.Source.AI, scheduled_date__isnull=False).exists())

    def test_regeneration_preserves_completed_tasks_and_teacher_times(self):
        assignment = self.create_assignment()
        plan, _, _ = generate_weekly_plan(self.student, self.preference, self.week_start)
        teacher_task = plan.tasks.get(source=StudyPlanTask.Source.TEACHER)
        original_time = (teacher_task.scheduled_date, teacher_task.start_time, teacher_task.end_time)
        completed_ai_task = plan.tasks.filter(source=StudyPlanTask.Source.AI).first()
        completed_ai_task.status = StudyPlanTask.Status.COMPLETED
        completed_ai_task.save(update_fields=['status'])

        regenerated_plan, _, generated = generate_weekly_plan(
            self.student,
            self.preference,
            self.week_start,
            replace_pending=True,
        )

        self.assertTrue(generated)
        self.assertEqual(regenerated_plan.pk, plan.pk)
        self.assertTrue(regenerated_plan.tasks.filter(pk=completed_ai_task.pk).exists())
        self.assertEqual(
            tuple(getattr(regenerated_plan.tasks.get(assignment=assignment), field) for field in (
                'scheduled_date', 'start_time', 'end_time',
            )),
            original_time,
        )

    @patch.dict(os.environ, {'AI_PLANNER_ENDPOINT': 'https://planner.invalid/recommend'})
    @patch('portal.study_planner.urllib.request.urlopen', side_effect=URLError('provider unavailable'))
    def test_unavailable_ai_provider_uses_logged_rule_based_fallback(self, _urlopen):
        plan, _, _ = generate_weekly_plan(self.student, self.preference, self.week_start)

        self.assertIn('AI সেবা এই মুহূর্তে পাওয়া যাচ্ছে না', plan.generation_note)
        self.assertTrue(plan.tasks.filter(source=StudyPlanTask.Source.AI).exists())

    def test_configured_ai_provider_recommendations_are_applied(self):
        response = MagicMock()
        recommendations = [
            {
                'task_type': 'revise',
                'priority': 'high',
                'description': f'Personalized review {index}',
                'expected_outcome': 'Recall the selected chapter',
                'reason': 'This syllabus chapter is still in progress',
            }
            for index in range(1)
        ]
        response.__enter__.return_value.read.return_value = json.dumps({
            'recommendations': recommendations,
        }).encode('utf-8')
        with (
            patch.dict(os.environ, {
                'AI_PLANNER_ENDPOINT': 'https://planner.example/recommend',
                'AI_PLANNER_API_KEY': 'test-provider-key',
            }),
            patch(
                'portal.study_planner.urllib.request.urlopen',
                return_value=response,
            ) as urlopen,
        ):
            plan, _, _ = generate_weekly_plan(
                self.student,
                self.preference,
                self.week_start,
            )

        self.assertIn('AI-এর পরামর্শ', plan.generation_note)
        self.assertEqual(
            plan.tasks.filter(source=StudyPlanTask.Source.AI).first().description,
            recommendations[0]['description'],
        )
        provider_request = urlopen.call_args.args[0]
        self.assertEqual(provider_request.get_header('Authorization'), 'Bearer test-provider-key')

    def test_openai_key_creates_week_plan_and_five_questions_per_topic(self):
        questions = [f'সৃজনশীল প্রশ্ন {index}' for index in range(1, 6)]
        ai_response = {
            'recommendations': [{
                'task_type': 'revise',
                'priority': 'high',
                'description': 'ভেক্টরের যোগ অনুশীলন',
                'expected_outcome': 'যোগের নিয়ম প্রয়োগ',
                'reason': 'পরীক্ষার প্রস্তুতি',
            }],
            'topics': [{
                'subject': 'পদার্থবিজ্ঞান',
                'paper': self.physics_paper,
                'chapter': self.chapter,
                'items': [{'topic': 'ভেক্টরের যোগ', 'questions': questions}],
            }],
            'plan_note': 'পরীক্ষার আগে ছোট session-এ প্রস্তুতি নাও।',
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            'choices': [{
                'message': {'content': json.dumps(ai_response, ensure_ascii=False)},
            }],
        }, ensure_ascii=False).encode('utf-8')
        with (
            patch.dict(os.environ, {
                'OPENAI_API_KEY': 'test-openai-key',
                'AI_PLANNER_ENDPOINT': '',
            }),
            patch('portal.study_planner.urllib.request.urlopen', return_value=response) as urlopen,
        ):
            plan, _, _ = generate_weekly_plan(
                self.student,
                self.preference,
                self.week_start,
            )

        self.assertIn('পরীক্ষার আগে', plan.generation_note)
        self.assertEqual(len(plan.question_bank), 1)
        self.assertEqual(plan.question_bank[0]['questions'], questions)
        topic_progress = StudentChapterProgress.objects.get(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper=self.physics_paper,
            chapter=self.chapter,
            topic='ভেক্টরের যোগ',
        )
        self.assertEqual(topic_progress.status, StudentChapterProgress.Status.NOT_STARTED)
        topic_task_types = set(plan.tasks.filter(
            topic='ভেক্টরের যোগ',
        ).values_list('task_type', flat=True))
        self.assertTrue({
            TeacherStudyAssignment.TaskType.LEARN,
            TeacherStudyAssignment.TaskType.MCQ,
            TeacherStudyAssignment.TaskType.CQ,
        }.issubset(topic_task_types))
        provider_request = urlopen.call_args.args[0]
        self.assertEqual(provider_request.full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(provider_request.get_header('Authorization'), 'Bearer test-openai-key')

    def test_ai_task_rescheduling_uses_a_new_non_overlapping_slot(self):
        self.preference.preferred_study_hours = 1
        self.preference.save(update_fields=['preferred_study_hours'])
        plan = WeeklyStudyPlan.objects.create(
            student=self.student,
            week_start=self.week_start,
        )
        task = StudyPlanTask.objects.create(
            plan=plan,
            source=StudyPlanTask.Source.AI,
            task_type=TeacherStudyAssignment.TaskType.LEARN,
            subject='পদার্থবিজ্ঞান',
            chapter=self.chapter,
            description='Reschedule this session',
            scheduled_date=self.week_start,
            start_time=time(19),
            end_time=time(20),
            duration_minutes=60,
            priority=TeacherStudyAssignment.Priority.NORMAL,
        )
        original_date = task.scheduled_date
        original_end = task.end_time

        self.assertTrue(reschedule_ai_task(task))

        task.refresh_from_db()
        self.assertEqual(task.status, StudyPlanTask.Status.RESCHEDULED)
        self.assertTrue(
            task.scheduled_date > original_date
            or (task.scheduled_date == original_date and task.start_time > original_end)
        )

    def test_teacher_assignment_reschedule_is_a_request_not_a_moved_task(self):
        assignment = self.create_assignment()
        plan, _, _ = generate_weekly_plan(self.student, self.preference, self.week_start)
        task = plan.tasks.get(assignment=assignment)
        original_slot = (task.scheduled_date, task.start_time, task.end_time)
        self.client.force_login(self.student_user)

        response = self.client.post(
            reverse('update_study_plan_task', args=[task.pk]),
            {'action': 'reschedule'},
        )

        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(
            (task.scheduled_date, task.start_time, task.end_time),
            original_slot,
        )
        self.assertTrue(TeacherAssignmentProgress.objects.get(
            assignment=assignment,
            student=self.student,
        ).reschedule_requested)

    @patch.dict(os.environ, {'AI_PLANNER_ENDPOINT': ''})
    def test_plan_generation_is_simple_and_pending_replacement_requires_confirmation(self):
        self.client.force_login(self.student_user)
        url = reverse('generate_student_study_plan')
        first_response = self.client.post(url, {'week': self.week_start.isoformat()})
        self.assertEqual(first_response.status_code, 302)
        plan = WeeklyStudyPlan.objects.get(student=self.student)
        original_task_ids = list(plan.tasks.values_list('pk', flat=True))
        self.assertTrue(original_task_ids)

        unconfirmed_response = self.client.post(url, {
            'week': self.week_start.isoformat(),
        })
        self.assertEqual(
            unconfirmed_response['Location'],
            f"{reverse('legacy_student_study_planner')}?week={self.week_start.isoformat()}&confirm_replace=1",
        )
        self.assertEqual(list(plan.tasks.values_list('pk', flat=True)), original_task_ids)

        confirmed_response = self.client.post(url, {
            'week': self.week_start.isoformat(),
            'confirm_replace': 'on',
        })
        self.assertEqual(confirmed_response.status_code, 302)
        plan.refresh_from_db()
        self.assertTrue(plan.tasks.exists())

    def test_student_plan_task_completion_persists_without_completing_chapter(self):
        self.create_assignment()
        plan, _, _ = generate_weekly_plan(self.student, self.preference, self.week_start)
        teacher_task = plan.tasks.get(source=StudyPlanTask.Source.TEACHER)
        self.client.force_login(self.student_user)

        response = self.client.post(
            reverse('update_study_plan_task', args=[teacher_task.pk]),
            {'action': 'complete'},
        )

        self.assertEqual(response.status_code, 302)
        teacher_task.refresh_from_db()
        self.progress.refresh_from_db()
        self.assertEqual(teacher_task.status, StudyPlanTask.Status.COMPLETED)
        self.assertFalse(self.progress.status == StudentChapterProgress.Status.COMPLETED)
        self.assertTrue(TeacherAssignmentProgress.objects.get(
            assignment=teacher_task.assignment,
            student=self.student,
        ).is_completed)
        self.assertEqual(
            self.client.get(reverse('legacy_student_study_planner')).status_code,
            200,
        )
        self.client.force_login(self.teacher)
        teacher_response = self.client.get(reverse('teacher_study_assignments'))
        self.assertContains(teacher_response, 'Completed')

    def test_students_cannot_update_another_students_plan_task(self):
        other_plan = WeeklyStudyPlan.objects.create(
            student=self.other_student,
            week_start=self.week_start,
        )
        task = StudyPlanTask.objects.create(
            plan=other_plan,
            source=StudyPlanTask.Source.AI,
            task_type=TeacherStudyAssignment.TaskType.LEARN,
            subject='পদার্থবিজ্ঞান',
            description='Private task',
            duration_minutes=60,
            priority=TeacherStudyAssignment.Priority.NORMAL,
        )
        self.client.force_login(self.student_user)

        response = self.client.post(
            reverse('update_study_plan_task', args=[task.pk]),
            {'action': 'complete'},
        )

        self.assertEqual(response.status_code, 404)
        task.refresh_from_db()
        self.assertEqual(task.status, StudyPlanTask.Status.NOT_STARTED)

    def test_teacher_can_assign_task_and_review_student_completion(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('teacher_study_assignments'), {
            'target': 'student',
            'student': self.student.pk,
            'subject': 'পদার্থবিজ্ঞান',
            'paper': self.physics_paper,
            'chapter': self.chapter,
            'topic': '',
            'task_type': TeacherStudyAssignment.TaskType.CQ,
            'description': 'CQ practice',
            'instructions': 'Complete questions 1-3.',
            'assigned_date': self.week_start.isoformat(),
            'deadline': self.week_end.isoformat(),
            'estimated_duration_minutes': 45,
            'priority': TeacherStudyAssignment.Priority.HIGH,
        })

        self.assertRedirects(response, reverse('teacher_study_assignments'))
        assignment = TeacherStudyAssignment.objects.get(description='CQ practice')
        self.assertEqual(assignment.teacher, self.teacher)
        self.assertEqual(assignment.student, self.student)
        self.assertEqual(self.client.get(reverse('teacher_study_assignments')).status_code, 200)

    def test_teacher_can_assign_to_a_batch_and_see_each_student_status(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('teacher_study_assignments'), {
            'target': 'batch',
            'year_group': self.student.year_group,
            'class_name': self.student.class_name,
            'subject': 'পদার্থবিজ্ঞান',
            'paper': self.physics_paper,
            'chapter': self.chapter,
            'topic': '',
            'task_type': TeacherStudyAssignment.TaskType.HOMEWORK,
            'description': 'Batch homework',
            'instructions': '',
            'assigned_date': self.week_start.isoformat(),
            'deadline': self.week_end.isoformat(),
            'estimated_duration_minutes': 60,
            'priority': TeacherStudyAssignment.Priority.NORMAL,
        })

        self.assertRedirects(response, reverse('teacher_study_assignments'))
        assignment = TeacherStudyAssignment.objects.get(description='Batch homework')
        self.assertIsNone(assignment.student)
        self.assertEqual(assignment.year_group, self.student.year_group)
        teacher_response = self.client.get(reverse('teacher_study_assignments'))
        listed_assignment = next(
            row for row in teacher_response.context['assignments']
            if row.pk == assignment.pk
        )
        self.assertEqual(
            {row['student'].pk for row in listed_assignment.completion_rows},
            {self.student.pk, self.other_student.pk},
        )

    def test_setup_and_teacher_assignment_pages_require_correct_role(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(reverse('legacy_student_study_planner') + '?tab=setup').status_code, 200)
        self.assertEqual(self.client.get(reverse('teacher_study_assignments')).status_code, 403)
