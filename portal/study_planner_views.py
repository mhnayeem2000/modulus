from datetime import date, time, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from exams.models import Exam
from students.models import Student

from .access import role_required
from .curriculum import CURRICULUM
from .models import (
    Routine,
    StudentChapterProgress,
    StudentScheduleInterval,
    StudentStudyPreference,
    StudyPlanTask,
    TeacherAssignmentProgress,
    TeacherStudyAssignment,
    WeeklyStudyPlan,
)
from .study_planner import generate_weekly_plan, plan_summary, week_start_for
from .study_planner_forms import (
    StudentChapterProgressFormSet,
    StudentScheduleIntervalFormSet,
    StudentStudyPreferenceForm,
    TeacherStudyAssignmentForm,
)


def _student_for_user(user):
    try:
        student = user.student_record
    except Student.DoesNotExist as exc:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('এই অ্যাকাউন্টের সঙ্গে কোনো শিক্ষার্থী যুক্ত নেই।') from exc
    if not student.is_active:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('এই শিক্ষার্থীর অ্যাকাউন্টটি নিষ্ক্রিয়।')
    return student


def _parse_week(raw_week, today):
    if not raw_week:
        return week_start_for(today)
    try:
        return week_start_for(date.fromisoformat(raw_week))
    except ValueError:
        return week_start_for(today)


def _student_assignments(student, week_start, week_end):
    assignments = TeacherStudyAssignment.objects.filter(
        assigned_date__lte=week_end,
    ).filter(
        Q(student=student)
        | Q(student__isnull=True, class_name=student.class_name, year_group=student.year_group)
    ).select_related('teacher').order_by('deadline', '-priority', 'created_at')
    return assignments


def _default_evening_intervals(student):
    available_days = set(
        StudentScheduleInterval.objects.filter(
            student=student,
            kind=StudentScheduleInterval.Kind.AVAILABLE,
        ).values_list('weekday', flat=True)
    )
    return [
        {
            'weekday': weekday,
            'kind': StudentScheduleInterval.Kind.AVAILABLE,
            'start_time': time(19),
            'end_time': time(23),
        }
        for weekday, _label in Routine.Weekday.choices
        if weekday not in available_days
    ]


def _chapter_progress_summary(student, subjects):
    progress_rows = list(StudentChapterProgress.objects.filter(
        student=student,
        subject__in=subjects,
    ))
    rows_by_chapter = {}
    for row in progress_rows:
        key = (row.subject, row.paper, row.chapter)
        rows_by_chapter.setdefault(key, []).append(row)

    summaries = []
    for subject in subjects:
        selected_chapters = [
            (paper, chapter)
            for selected_subject, paper, chapter in rows_by_chapter
            if selected_subject == subject
        ]
        if not selected_chapters:
            continue
        groups = {
            'subject': subject,
            'completed': [],
            'in_progress': [],
            'not_started': [],
        }
        for paper, chapter in selected_chapters:
            chapter_rows = rows_by_chapter[(subject, paper, chapter)]
            statuses = [row.status for row in chapter_rows]
            status = (
                'completed'
                if all(
                    value == StudentChapterProgress.Status.COMPLETED
                    for value in statuses
                )
                else 'in_progress'
                if any(
                    value != StudentChapterProgress.Status.NOT_STARTED
                    for value in statuses
                )
                else 'not_started'
            )
            groups[status].append({
                'paper': paper,
                'chapter': chapter,
                'topics': [
                    {
                        'topic': row.topic,
                        'status': row.status,
                        'status_label': row.get_status_display(),
                    }
                    for row in chapter_rows
                    if row.topic
                ],
            })
        summaries.append(groups)
    return summaries


def _update_topic_progress(task, student):
    if task.source != StudyPlanTask.Source.AI or not task.topic:
        return None
    progress, _ = StudentChapterProgress.objects.get_or_create(
        student=student,
        subject=task.subject,
        paper=task.paper,
        chapter=task.chapter,
        topic=task.topic,
    )
    if progress.status == StudentChapterProgress.Status.COMPLETED:
        return {
            'subject': progress.subject,
            'paper': progress.paper,
            'chapter': progress.chapter,
            'topic': progress.topic,
            'status': progress.status,
            'status_label': progress.get_status_display(),
        }
    completed_types = set(StudyPlanTask.objects.filter(
        plan__student=student,
        source=StudyPlanTask.Source.AI,
        status=StudyPlanTask.Status.COMPLETED,
        subject=task.subject,
        paper=task.paper,
        chapter=task.chapter,
        topic=task.topic,
    ).values_list('task_type', flat=True))
    required_types = {
        TeacherStudyAssignment.TaskType.LEARN,
        TeacherStudyAssignment.TaskType.MCQ,
        TeacherStudyAssignment.TaskType.CQ,
    }
    progress.status = (
        StudentChapterProgress.Status.COMPLETED
        if required_types.issubset(completed_types)
        else StudentChapterProgress.Status.IN_PROGRESS
    )
    progress.save(update_fields=['status', 'updated_at'])
    return {
        'subject': progress.subject,
        'paper': progress.paper,
        'chapter': progress.chapter,
        'topic': progress.topic,
        'status': progress.status,
        'status_label': progress.get_status_display(),
    }


@role_required('student')
def legacy_student_study_planner(request):
    student = _student_for_user(request.user)
    action = request.POST.get('task_action') or request.POST.get('action')
    if request.method == 'POST' and action in {
        'start',
        'complete',
        'skip',
        'reschedule',
    }:
        task_id = request.POST.get('task_id', '')
        if not task_id.isdecimal():
            return JsonResponse({
                'success': False,
                'error': 'পড়ার কাজটি চেনা যায়নি। Planner refresh করে আবার চেষ্টা করো।',
            }, status=400)
        return update_study_plan_task(request, int(task_id), action=action)
    today = timezone.localdate()
    week_start = _parse_week(request.GET.get('week', ''), today)
    week_end = week_start + timedelta(days=6)
    tab = request.GET.get('tab', 'plan')
    if tab not in {'plan', 'setup', 'assignments', 'history', 'questions'}:
        tab = 'plan'

    preferences = StudentStudyPreference.objects.filter(student=student).first()
    plan = WeeklyStudyPlan.objects.filter(student=student, week_start=week_start).first()
    if tab == 'setup':
        preference_form = StudentStudyPreferenceForm(
            instance=preferences or StudentStudyPreference(student=student),
        )
        intervals = StudentScheduleIntervalFormSet(
            queryset=StudentScheduleInterval.objects.filter(
                student=student,
            ),
            initial=_default_evening_intervals(student),
            prefix='intervals',
        )
        chapter_progress = StudentChapterProgressFormSet(
            queryset=StudentChapterProgress.objects.filter(student=student),
            prefix='chapters',
        )
        context = {
            'student': student,
            'tab': tab,
            'preference_form': preference_form,
            'interval_formset': intervals,
            'chapter_formset': chapter_progress,
            'week_start': week_start,
            'week_end': week_end,
            'previous_week': week_start - timedelta(days=7),
            'next_week': week_start + timedelta(days=7),
            'today': today,
            'active_setup_step': 'schedule',
            'chapter_progress_summary': _chapter_progress_summary(
                student,
                preferences.subjects if preferences else [],
            ),
        }
        return render(request, 'portal/student_study_planner.html', context)

    tasks = list(plan.tasks.select_related('assignment').all()) if plan else []
    tasks_by_day = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        daily_tasks = [task for task in tasks if task.scheduled_date == day]
        daily_tasks.sort(key=lambda task: (task.start_time or time.min, task.pk))
        tasks_by_day.append({
            'date': day,
            'tasks': daily_tasks,
            'minutes': sum(task.duration_minutes for task in daily_tasks),
            'completed': sum(task.status == StudyPlanTask.Status.COMPLETED for task in daily_tasks),
            'percent': (
                round(sum(task.status == StudyPlanTask.Status.COMPLETED for task in daily_tasks)
                      * 100 / len(daily_tasks))
                if daily_tasks else 0
            ),
        })

    assignment_rows = []
    if tab == 'assignments':
        assignments = list(_student_assignments(student, week_start, week_end))
        planned_tasks = list(
            StudyPlanTask.objects.filter(assignment__in=assignments)
            .select_related('plan')
            .order_by('-plan__week_start', '-created_at')
        )
        latest_plan_task = {}
        for task in planned_tasks:
            latest_plan_task.setdefault(task.assignment_id, task)
        progress_by_assignment = {
            item.assignment_id: item
            for item in TeacherAssignmentProgress.objects.filter(
                student=student,
                assignment__in=assignments,
            )
        }
        assignment_rows = [
            {
                'assignment': assignment,
                'progress': progress_by_assignment.get(assignment.pk),
                'planned_task': latest_plan_task.get(assignment.pk),
            }
            for assignment in assignments
        ]

    history_plans = []
    if tab == 'history':
        history_plans = list(
            WeeklyStudyPlan.objects.filter(student=student)
            .exclude(week_start=week_start)
            .prefetch_related('tasks')
            .order_by('-week_start')[:12]
        )
        for old_plan in history_plans:
            old_plan.summary = plan_summary(old_plan)
    question_page = None
    if tab == 'questions' and plan:
        question_page = Paginator(plan.question_bank, 1).get_page(request.GET.get('page'))

    upcoming_exam = Exam.objects.filter(
        year_group=student.year_group,
        exam_date__gte=today,
    ).order_by('exam_date').first()
    exam_date = (
        preferences.exam_date
        if preferences and preferences.exam_date and preferences.exam_date >= today
        else upcoming_exam.exam_date if upcoming_exam else None
    )
    selected_day = request.GET.get('day', '')
    try:
        selected_day = date.fromisoformat(selected_day)
    except (TypeError, ValueError):
        selected_day = None
    if selected_day and not week_start <= selected_day <= week_end:
        selected_day = None
    weekdays = list(Routine.Weekday.choices)
    context = {
        'student': student,
        'tab': tab,
        'week_start': week_start,
        'week_end': week_end,
        'previous_week': week_start - timedelta(days=7),
        'next_week': week_start + timedelta(days=7),
        'today': today,
        'plan': plan,
        'tasks': tasks,
        'unplaced_tasks': [
            task for task in tasks
            if task.scheduled_date is None and task.status not in (
                StudyPlanTask.Status.COMPLETED,
                StudyPlanTask.Status.SKIPPED,
            )
        ],
        'tasks_by_day': tasks_by_day,
        'summary': plan_summary(plan) if plan else None,
        'conflicts': request.session.pop('study_plan_conflicts', []),
        'generation_note': plan.generation_note if plan else '',
        'upcoming_exam': upcoming_exam,
        'exam_days_left': (exam_date - today).days if exam_date else None,
        'exam_date': exam_date,
        'exam_countdown': (exam_date - today).days if exam_date else None,
        'assignments': assignment_rows,
        'history_plans': history_plans,
        'selected_day': selected_day,
        'weekdays': weekdays,
        'selected_subjects': preferences.subjects if preferences else [],
        'daily_study_hours': preferences.preferred_study_hours if preferences else 2,
        'question_page': question_page,
        'chapter_progress_summary': _chapter_progress_summary(
            student,
            preferences.subjects if preferences else [],
        ),
    }
    return render(request, 'portal/student_study_planner.html', context)


@role_required('student')
@require_POST
def save_study_planner_setup(request):
    student = _student_for_user(request.user)
    preference, _ = StudentStudyPreference.objects.get_or_create(student=student)
    preference_form = StudentStudyPreferenceForm(request.POST, instance=preference)
    interval_formset = StudentScheduleIntervalFormSet(
        request.POST,
        queryset=StudentScheduleInterval.objects.filter(student=student),
        prefix='intervals',
    )
    chapter_formset = StudentChapterProgressFormSet(
        request.POST,
        queryset=StudentChapterProgress.objects.filter(student=student),
        prefix='chapters',
    )
    if not (
        preference_form.is_valid()
        and interval_formset.is_valid()
        and chapter_formset.is_valid()
    ):
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        active_setup_step = (
            'preferences'
            if preference_form.errors
            else 'schedule'
            if interval_formset.errors or interval_formset.non_form_errors()
            else 'chapters'
        )
        today = timezone.localdate()
        week_start = week_start_for(today)
        if not is_ajax:
            messages.error(request, 'তথ্যগুলো যাচাই করে আবার চেষ্টা করো।')
        response = render(request, 'portal/student_study_planner.html', {
            'student': student,
            'tab': 'setup',
            'preference_form': preference_form,
            'interval_formset': interval_formset,
            'chapter_formset': chapter_formset,
            'week_start': week_start,
            'week_end': week_start + timedelta(days=6),
            'previous_week': week_start - timedelta(days=7),
            'next_week': week_start + timedelta(days=7),
            'today': today,
            'active_setup_step': active_setup_step,
            'chapter_progress_summary': _chapter_progress_summary(
                student,
                preference_form.cleaned_data.get('subjects', [])
                if preference_form.is_valid()
                else preference.subjects,
            ),
        })
        if is_ajax:
            return JsonResponse({
                'success': False,
                'html': response.content.decode(response.charset),
            }, status=422)
        return response
    try:
        with transaction.atomic():
            preference = preference_form.save()
            for interval_form in interval_formset.forms:
                interval_data = interval_form.cleaned_data
                if (
                    interval_data.get('DELETE')
                    and interval_form.instance.pk
                ):
                    interval_form.instance.delete()
                elif (
                    interval_data.get('weekday') is not None
                    and interval_data.get('start_time')
                    and interval_data.get('end_time')
                    and (interval_form.has_changed() or not interval_form.instance.pk)
                ):
                    interval = interval_form.save(commit=False)
                    interval.student = student
                    interval.full_clean()
                    interval.save()
            for progress_form in chapter_formset.forms:
                if (
                    progress_form.cleaned_data
                    and not progress_form.cleaned_data.get('DELETE')
                    and progress_form.has_changed()
                ):
                    progress = progress_form.save(commit=False)
                    progress.student = student
                    progress.full_clean()
                    progress.save()
                elif progress_form.cleaned_data.get('DELETE') and progress_form.instance.pk:
                    progress_form.instance.delete()
    except ValidationError as exc:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'তথ্য সংরক্ষণ করা যায়নি: {exc}',
            }, status=400)
        messages.error(request, f'তথ্য সংরক্ষণ করা যায়নি: {exc}')
        return redirect(f"{reverse('legacy_student_study_planner')}?tab=setup")
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'তোমার তথ্য সংরক্ষিত হয়েছে।',
        })
    messages.success(request, 'তোমার সাপ্তাহিক পছন্দ ও অধ্যায়ের অগ্রগতি সংরক্ষিত হয়েছে।')
    return redirect(f"{reverse('legacy_student_study_planner')}?tab=plan")


@role_required('student')
@require_POST
def generate_student_study_plan(request):
    student = _student_for_user(request.user)
    week_start = _parse_week(request.POST.get('week', ''), timezone.localdate())
    preferences = StudentStudyPreference.objects.filter(student=student).first()
    if not preferences:
        messages.error(request, 'সপ্তাহের পরিকল্পনা তৈরির আগে পড়ার পছন্দ সেটআপ করো।')
        return redirect(f"{reverse('legacy_student_study_planner')}?tab=setup")
    if not preferences.subjects or not StudentChapterProgress.objects.filter(
        student=student,
        subject__in=preferences.subjects,
    ).exclude(status=StudentChapterProgress.Status.COMPLETED).exists():
        messages.error(request, 'Plan তৈরির আগে অন্তত একটি subject ও chapter বেছে নাও।')
        return redirect(f"{reverse('legacy_student_study_planner')}?tab=setup")
    existing_plan = WeeklyStudyPlan.objects.filter(student=student, week_start=week_start).first()
    pending = (
        existing_plan.tasks.exclude(status=StudyPlanTask.Status.COMPLETED).exists()
        if existing_plan else False
    )
    if pending and request.POST.get('confirm_replace') != 'on':
        messages.error(request, 'অসম্পন্ন কাজগুলো রেখে পরিকল্পনা বদলানো হবে না। নিশ্চিত করলে শুধু AI-এর অসম্পন্ন প্রস্তাব নতুন করে তৈরি হবে।')
        return redirect(f"{reverse('legacy_student_study_planner')}?week={week_start.isoformat()}&confirm_replace=1")
    plan, conflicts, generated = generate_weekly_plan(
        student,
        preferences,
        week_start,
        replace_pending=bool(pending),
    )
    if not generated:
        messages.error(request, 'আগের অসম্পন্ন শিক্ষক-নির্ধারিত কাজ অপরিবর্তিত আছে।')
    else:
        request.session['study_plan_conflicts'] = conflicts
        messages.success(request, 'তোমার সপ্তাহের পরিকল্পনা তৈরি হয়েছে।')
    return redirect(f"{reverse('legacy_student_study_planner')}?week={week_start.isoformat()}")


@role_required('student')
@require_POST
def update_study_plan_task(request, task_id, action=None):
    student = _student_for_user(request.user)
    task = get_object_or_404(StudyPlanTask, pk=task_id, plan__student=student)
    action = action or request.POST.get('task_action') or request.POST.get('action')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    response_message = ''
    response_error = ''
    if task.status == StudyPlanTask.Status.COMPLETED:
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': 'এই পড়ার কাজটি আগেই সম্পন্ন হয়েছে।',
            }, status=409)
        messages.error(request, 'সম্পন্ন কাজের অবস্থা আর পরিবর্তন করা যাবে না।')
        return redirect(
            f"{reverse('legacy_student_study_planner')}?week={task.plan.week_start.isoformat()}",
        )
    if action == 'start':
        if task.status not in (StudyPlanTask.Status.NOT_STARTED, StudyPlanTask.Status.RESCHEDULED):
            response_error = 'এই কাজটি শুরু করা যাচ্ছে না।'
            if not is_ajax:
                messages.error(request, response_error)
        else:
            task.status = StudyPlanTask.Status.IN_PROGRESS
            task.save(update_fields=['status', 'updated_at'])
            response_message = 'কাজটি শুরু হিসেবে চিহ্নিত হয়েছে।'
            if not is_ajax:
                messages.success(request, response_message)
    elif action == 'complete':
        if task.status == StudyPlanTask.Status.SKIPPED:
            response_error = 'বাদ দেওয়া কাজ সম্পন্ন করতে আগে নতুন পরিকল্পনা তৈরি করো।'
            if not is_ajax:
                messages.error(request, response_error)
        else:
            with transaction.atomic():
                task.status = StudyPlanTask.Status.COMPLETED
                task.save(update_fields=['status', 'updated_at'])
                if task.assignment_id:
                    TeacherAssignmentProgress.objects.update_or_create(
                        assignment=task.assignment,
                        student=student,
                        defaults={'is_completed': True, 'reschedule_requested': False},
                    )
                topic_progress = _update_topic_progress(task, student)
            response_message = (
                'পড়ার কাজ সম্পন্ন হয়েছে—topic-এর অগ্রগতি update হয়েছে।'
                if topic_progress else 'পড়ার কাজ সম্পন্ন হয়েছে।'
            )
            if not is_ajax:
                messages.success(request, response_message)
    elif action == 'skip':
        task.status = StudyPlanTask.Status.SKIPPED
        task.save(update_fields=['status', 'updated_at'])
        response_message = 'কাজটি এই সপ্তাহের তালিকা থেকে বাদ দেওয়া হয়েছে।'
        if not is_ajax:
            messages.success(request, response_message)
    elif action == 'reschedule':
        if task.assignment_id:
            TeacherAssignmentProgress.objects.update_or_create(
                assignment=task.assignment,
                student=student,
                defaults={'reschedule_requested': True},
            )
            response_message = 'সময় পরিবর্তনের অনুরোধ শিক্ষককে জানানো হয়েছে; শিক্ষক-নির্ধারিত সময় অপরিবর্তিত আছে।'
            if not is_ajax:
                messages.success(request, response_message)
        else:
            from .study_planner import reschedule_ai_task

            if reschedule_ai_task(task):
                response_message = 'AI প্রস্তাবটি নতুন খালি সময়ে সরানো হয়েছে।'
                if not is_ajax:
                    messages.success(request, response_message)
            else:
                response_error = 'এই সপ্তাহে কাজটির জন্য আর কোনো উপযুক্ত খালি সময় নেই।'
                if not is_ajax:
                    messages.error(request, response_error)
    else:
        response_error = 'এই কাজের অনুরোধটি বৈধ নয়।'
        if not is_ajax:
            messages.error(request, response_error)
    if is_ajax:
        if response_error:
            return JsonResponse({'success': False, 'error': response_error}, status=400)
        response_data = {'success': True, 'message': response_message}
        if action == 'complete':
            day_tasks = task.plan.tasks.filter(scheduled_date=task.scheduled_date)
            response_data.update({
                'summary': plan_summary(task.plan),
                'day': {
                    'minutes': sum(item.duration_minutes for item in day_tasks),
                    'completed': day_tasks.filter(
                        status=StudyPlanTask.Status.COMPLETED,
                    ).count(),
                    'total': day_tasks.count(),
                },
            })
            if topic_progress:
                response_data['topic_progress'] = topic_progress
        return JsonResponse(response_data)
    return redirect(
        f"{reverse('legacy_student_study_planner')}?week={task.plan.week_start.isoformat()}",
    )


@role_required('teacher')
def teacher_study_assignments(request):
    form = TeacherStudyAssignmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        assignment = form.save(commit=False)
        assignment.teacher = request.user
        assignment.save()
        messages.success(request, 'শিক্ষার্থীর পড়ার কাজ বরাদ্দ হয়েছে।')
        return redirect('teacher_study_assignments')
    assignments = TeacherStudyAssignment.objects.filter(teacher=request.user).select_related(
        'student',
    ).prefetch_related(
        'student_progress__student',
    ).order_by('-created_at')
    for assignment in assignments:
        students = (
            [assignment.student]
            if assignment.student_id
            else list(Student.objects.filter(
                is_active=True,
                class_name=assignment.class_name,
                year_group=assignment.year_group,
            ).order_by('name'))
        )
        progress_by_student = {
            progress.student_id: progress
            for progress in assignment.student_progress.all()
        }
        assignment.completion_rows = [
            {
                'student': target,
                'progress': progress_by_student.get(target.pk),
            }
            for target in students
        ]
    return render(request, 'portal/teacher_study_assignments.html', {
        'form': form,
        'assignments': assignments,
    })
