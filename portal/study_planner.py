import json
import logging
import os
import urllib.error
import urllib.request
from datetime import date, time, timedelta

from django.db import transaction
from django.utils import timezone

from exams.models import Exam, ExamResult

from .curriculum import CURRICULUM
from .models import (
    Routine,
    StudentChapterProgress,
    StudentScheduleInterval,
    StudyPlanTask,
    TeacherAssignmentProgress,
    TeacherStudyAssignment,
    WeeklyStudyPlan,
)


logger = logging.getLogger(__name__)
PRIORITY_ORDER = {
    TeacherStudyAssignment.Priority.MANDATORY: 0,
    TeacherStudyAssignment.Priority.HIGH: 1,
    TeacherStudyAssignment.Priority.NORMAL: 2,
    TeacherStudyAssignment.Priority.LOW: 3,
}
AI_TASK_TYPES = {
    TeacherStudyAssignment.TaskType.LEARN,
    TeacherStudyAssignment.TaskType.REVISE,
    TeacherStudyAssignment.TaskType.MCQ,
    TeacherStudyAssignment.TaskType.CQ,
    TeacherStudyAssignment.TaskType.NUMERICAL,
    TeacherStudyAssignment.TaskType.MOCK_TEST,
}
AI_PRIORITY_VALUES = {
    TeacherStudyAssignment.Priority.LOW,
    TeacherStudyAssignment.Priority.NORMAL,
    TeacherStudyAssignment.Priority.HIGH,
}


def week_start_for(day):
    return day - timedelta(days=day.weekday())


def _to_minutes(value):
    return value.hour * 60 + value.minute


def _from_minutes(value):
    return time(value // 60, value % 60)


def _subtract_interval(intervals, blocked_start, blocked_end):
    remaining = []
    for start, end in intervals:
        if blocked_end <= start or blocked_start >= end:
            remaining.append((start, end))
            continue
        if start < blocked_start:
            remaining.append((start, blocked_start))
        if blocked_end < end:
            remaining.append((blocked_end, end))
    return remaining


def _available_intervals(student, weekday, rest_days):
    if weekday in rest_days:
        return []
    intervals = list(
        (_to_minutes(row.start_time), _to_minutes(row.end_time))
        for row in student.study_schedule_intervals.filter(
            weekday=weekday,
            kind=StudentScheduleInterval.Kind.AVAILABLE,
        )
    )
    if not intervals:
        intervals = [(19 * 60, 23 * 60)]
    blocked = [
        (_to_minutes(row.start_time), _to_minutes(row.end_time))
        for row in student.study_schedule_intervals.filter(
            weekday=weekday,
        ).exclude(kind=StudentScheduleInterval.Kind.AVAILABLE)
    ]
    blocked.extend(
        (_to_minutes(routine.start_time), _to_minutes(routine.end_time))
        for routine in Routine.objects.filter(year_group=student.year_group, weekday=weekday)
    )
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    intervals = merged
    for block_start, block_end in blocked:
        intervals = _subtract_interval(intervals, block_start, block_end)
    return sorted(intervals)


def _limit_daily_intervals(
    intervals,
    daily_minutes,
    break_minutes=0,
    session_duration_minutes=60,
):
    evening_start = 19 * 60
    prioritized = []
    earlier = []
    for start, end in intervals:
        if end > evening_start:
            prioritized.append((max(start, evening_start), end))
        if start < evening_start:
            earlier.append((start, min(end, evening_start)))
    max_sessions = daily_minutes // session_duration_minutes

    def interval_capacity(start, end):
        return (
            end - start + break_minutes
        ) // (session_duration_minutes + break_minutes)

    if sum(interval_capacity(start, end) for start, end in intervals) < max_sessions:
        return intervals

    limited = []
    remaining_sessions = max_sessions
    for start, end in (*prioritized, *earlier):
        if remaining_sessions <= 0:
            break
        sessions = min(interval_capacity(start, end), remaining_sessions)
        if sessions <= 0:
            continue
        window_minutes = sessions * session_duration_minutes + (sessions - 1) * break_minutes
        limited.append((start, start + window_minutes))
        remaining_sessions -= sessions
    return limited


def _find_slot(slots, duration):
    for day, ranges in slots.items():
        for index, (start, end) in enumerate(ranges):
            if end - start >= duration:
                return day, start, index
    return None


def _place_task(slots, day, range_index, start, duration, break_minutes):
    end = start + duration
    ranges = slots[day]
    range_start, range_end = ranges[range_index]
    replacement = []
    if range_start < start:
        replacement.append((range_start, start))
    next_start = min(end + break_minutes, range_end)
    if next_start < range_end:
        replacement.append((next_start, range_end))
    ranges[range_index:range_index + 1] = replacement
    return _from_minutes(start), _from_minutes(end)


def _assignment_queryset(student, week_start, week_end):
    return TeacherStudyAssignment.objects.filter(
        assigned_date__lte=week_end,
    ).filter(
        models_student_target(student),
    ).select_related('teacher').order_by('deadline', 'created_at')


def models_student_target(student):
    from django.db.models import Q

    return Q(student=student) | Q(
        student__isnull=True,
        class_name=student.class_name,
        year_group=student.year_group,
    )


def _study_candidates(student, subjects):
    progress_rows = list(
        StudentChapterProgress.objects.filter(student=student, subject__in=subjects)
        .order_by('-is_difficult', '-needs_revision', 'status', 'subject', 'chapter')
    )
    candidates = []
    for progress in progress_rows:
        if progress.status == StudentChapterProgress.Status.COMPLETED:
            continue
        candidates.append({
            'subject': progress.subject,
            'paper': progress.paper,
            'chapter': progress.chapter,
            'topic': progress.topic,
            'task_type': (
                TeacherStudyAssignment.TaskType.REVISE
                if progress.is_difficult or progress.needs_revision
                else TeacherStudyAssignment.TaskType.MCQ
                if progress.status == StudentChapterProgress.Status.IN_PROGRESS
                else TeacherStudyAssignment.TaskType.LEARN
            ),
            'priority': (
                TeacherStudyAssignment.Priority.HIGH
                if progress.is_difficult or progress.needs_revision
                else TeacherStudyAssignment.Priority.NORMAL
            ),
            'reason': (
                f'{progress.subject} · {progress.chapter} কঠিন হিসেবে চিহ্নিত'
                if progress.is_difficult
                else f'{progress.subject} · {progress.chapter} রিভিশন দরকার'
                if progress.needs_revision
                else f'{progress.subject} · {progress.chapter} এখনো সম্পন্ন হয়নি'
            ),
        })
    candidates.sort(
        key=lambda candidate: (
            PRIORITY_ORDER[candidate['priority']],
            candidate['subject'],
            candidate['paper'],
            candidate['chapter'],
        ),
    )
    return candidates


def _performance_context(student, subjects, week_start, week_end):
    latest_results = {}
    for result in ExamResult.objects.filter(
        student=student,
        exam__subject__in=subjects,
    ).select_related('exam').order_by('-exam__exam_date', '-updated_at'):
        latest_results.setdefault(
            result.exam.subject,
            round(float(result.marks) / result.exam.total_marks * 100),
        )
    exams = list(
        Exam.objects.filter(
            year_group=student.year_group,
            exam_date__gte=week_start,
            exam_date__lte=week_end + timedelta(days=30),
        ).order_by('exam_date')
    )
    next_exam_by_subject = {}
    for exam in exams:
        if exam.subject in subjects:
            next_exam_by_subject.setdefault(exam.subject, exam)
    return latest_results, next_exam_by_subject


def _apply_actual_priority(candidate, scores, exams, week_start):
    score = scores.get(candidate['subject'])
    exam = exams.get(candidate['subject'])
    if score is not None and score < 60:
        candidate['priority'] = TeacherStudyAssignment.Priority.HIGH
        candidate['reason'] = f'সাম্প্রতিক পরীক্ষায় {candidate["subject"]}-এ {score}% — এই অংশে অনুশীলন দরকার'
    elif exam and (exam.exam_date - week_start).days <= 7:
        candidate['priority'] = TeacherStudyAssignment.Priority.HIGH
        candidate['reason'] = f'{candidate["subject"]}-এর {exam.title} পরীক্ষা {exam.exam_date:%d %b}-এ'
    elif exam and (exam.exam_date - week_start).days <= 14:
        candidate['reason'] = f'{candidate["subject"]}-এর {exam.title} পরীক্ষা সামনে'


def _get_ai_recommendations(candidates, context):
    api_key = os.environ.get('AI_PLANNER_API_KEY', '').strip()
    openai_key = os.environ.get('OPENAI_API_KEY', '').strip()
    endpoint = os.environ.get('AI_PLANNER_ENDPOINT', '').strip()
    use_openai = bool(openai_key)
    if use_openai:
        endpoint = 'https://api.openai.com/v1/chat/completions'
        api_key = openai_key
    if not endpoint:
        return None, 'AI সেবা এখনো সংযুক্ত নয়; তোমার সময় ও বেছে রাখা chapter ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
    if api_key and not endpoint.lower().startswith('https://'):
        logger.warning('Study planner provider URL must use HTTPS when an API key is configured.')
        return None, 'AI সেবার সংযোগ নিরাপদ নয়; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
    request_data = {
        'candidates': candidates,
        'context': context,
    }
    if use_openai:
        request_data = {
            'model': os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
            'response_format': {'type': 'json_object'},
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'তুমি একজন সহানুভূতিশীল HSC study planner। শুধু দেওয়া subject, chapter, '
                        'availability এবং exam date ব্যবহার করবে। শিক্ষার্থীর চাপ কমিয়ে বাস্তবসম্মত '
                        'পড়ার session সাজাও। প্রতিটি candidate-এর জন্য recommendations-এ একটিমাত্র '
                        'entry দাও। topics-এ প্রতিটি candidate chapter-এর গুরুত্বপূর্ণ exam topic '
                        'দাও এবং প্রতিটি topic-এর জন্য ঠিক ৫টি বাংলা সৃজনশীল প্রশ্ন (CQ) লিখো; '
                        'প্রশ্নগুলো text only হবে, chapter/topic-এর বাইরে কিছু বানাবে না। '
                        'শুধু বৈধ JSON দেবে, কোনো markdown নয়। Shape: {"recommendations":'
                        '[{"task_type":"learn|revise|mcq|cq|numerical|mock_test",'
                        '"priority":"low|normal|high","description":"...","expected_outcome":"...",'
                        '"reason":"..."}],"topics":[{"subject":"...","paper":"...","chapter":"...",'
                        '"items":[{"topic":"...","questions":["...","...","...","...","..."]}]}],'
                        '"plan_note":"..."}'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(request_data, ensure_ascii=False),
                },
            ],
        }
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_data, ensure_ascii=False).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                **({'Authorization': f'Bearer {api_key}'} if api_key else {}),
            },
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read(1048577)
        if len(body) > 1048576:
            logger.warning('Study planner provider response exceeded the configured size limit.')
            return None, 'AI সেবার উত্তরটি ব্যবহার করা যায়নি; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
        result = json.loads(body.decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning('Study planner provider failed; using rule-based recommendations: %s', exc)
        return None, 'AI সেবা এই মুহূর্তে পাওয়া যাচ্ছে না; তোমার সময় ও বেছে রাখা chapter ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
    if use_openai:
        try:
            content = result['choices'][0]['message']['content']
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning('OpenAI returned an invalid study planner response.')
            return None, 'AI সেবার উত্তরটি যাচাই করা যায়নি; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
    recommendations = result.get('recommendations') if isinstance(result, dict) else None
    if not isinstance(recommendations, list) or len(recommendations) != len(candidates):
        logger.warning('Study planner provider returned an invalid recommendation shape.')
        return None, 'AI সেবার উত্তরটি যাচাই করা যায়নি; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
    clean = []
    for item in recommendations:
        if not isinstance(item, dict):
            logger.warning('Study planner provider returned a non-object recommendation.')
            return None, 'AI সেবার উত্তরটি যাচাই করা যায়নি; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
        task_type = item.get('task_type')
        priority = item.get('priority')
        if (
            not isinstance(task_type, str)
            or not isinstance(priority, str)
            or task_type not in AI_TASK_TYPES
            or priority not in AI_PRIORITY_VALUES
        ):
            logger.warning('Study planner provider returned unsupported task metadata.')
            return None, 'AI সেবার উত্তরটি যাচাই করা যায়নি; নির্বাচিত chapter ও সময় ধরে নিয়মভিত্তিক পরিকল্পনা তৈরি হয়েছে।', []
        clean.append({
            'task_type': task_type,
            'priority': priority,
            'description': str(item.get('description') or '')[:240],
            'expected_outcome': str(item.get('expected_outcome') or '')[:240],
            'reason': str(item.get('reason') or '')[:240],
        })
    question_bank = []
    topics = result.get('topics', [])
    if isinstance(topics, list):
        allowed_chapters = {
            (candidate['subject'], candidate['paper'], candidate['chapter'])
            for candidate in candidates
        }
        for chapter_data in topics:
            if not isinstance(chapter_data, dict):
                continue
            chapter_key = (
                str(chapter_data.get('subject', '')),
                str(chapter_data.get('paper', '')),
                str(chapter_data.get('chapter', '')),
            )
            if chapter_key not in allowed_chapters:
                continue
            items = chapter_data.get('items', [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                questions = item.get('questions')
                topic = str(item.get('topic', '')).strip()[:160]
                if (
                    not topic
                    or not isinstance(questions, list)
                    or len(questions) != 5
                    or any(not isinstance(question, str) or not question.strip() for question in questions)
                ):
                    continue
                question_bank.append({
                    'subject': chapter_key[0],
                    'paper': chapter_key[1],
                    'chapter': chapter_key[2],
                    'topic': topic[:120],
                    'questions': [question.strip()[:2000] for question in questions],
                })
    default_note = (
        'তোমার সময় ও পরীক্ষার তারিখ অনুযায়ী AI পরিকল্পনা সাজিয়েছে।'
        if use_openai
        else 'AI-এর পরামর্শ তোমার সময় ও বেছে রাখা chapter-এর সঙ্গে মিলিয়ে যুক্ত হয়েছে।'
    )
    note = str(result.get('plan_note') or default_note)[:240]
    if use_openai and not question_bank:
        note = 'AI plan তৈরি হয়েছে, তবে CQ তৈরি হয়নি। আবার plan তৈরি করে দেখো।'
    return clean, note, question_bank


@transaction.atomic
def generate_weekly_plan(student, preferences, week_start, replace_pending=False):
    week_end = week_start + timedelta(days=6)
    plan, _ = WeeklyStudyPlan.objects.select_for_update().get_or_create(
        student=student,
        week_start=week_start,
    )
    existing_tasks = list(plan.tasks.select_for_update())
    completed_tasks = [task for task in existing_tasks if task.status == StudyPlanTask.Status.COMPLETED]
    if any(task.status != StudyPlanTask.Status.COMPLETED for task in existing_tasks) and not replace_pending:
        return plan, ['আগের সপ্তাহের অসম্পন্ন কাজ আছে—নতুন পরিকল্পনার আগে নিশ্চিত করুন।'], False

    if replace_pending:
        plan.tasks.filter(
            source=StudyPlanTask.Source.AI,
        ).exclude(status=StudyPlanTask.Status.COMPLETED).delete()

    used_assignments = set(
        plan.tasks.filter(assignment__isnull=False).values_list('assignment_id', flat=True)
    )
    slots = {}
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        slots[day] = _limit_daily_intervals(
            _available_intervals(student, day.weekday(), set()),
            preferences.preferred_study_hours * 60,
            preferences.break_duration_minutes,
            preferences.session_duration_minutes,
        )
    weekly_availability_minutes = sum(
        end - start
        for ranges in slots.values()
        for start, end in ranges
    )

    conflicts = []
    preserved_tasks = list(plan.tasks.select_related('assignment'))
    current_assignment_tasks = {
        task.assignment_id: task
        for task in preserved_tasks
        if task.assignment_id
    }
    for task in preserved_tasks:
        if task.scheduled_date in slots and task.start_time and task.end_time:
            slots[task.scheduled_date] = _subtract_interval(
                slots[task.scheduled_date],
                _to_minutes(task.start_time),
                _to_minutes(task.end_time) + preferences.break_duration_minutes,
            )

    assignment_rows = sorted(
        _assignment_queryset(student, week_start, week_end),
        key=lambda assignment: (
            assignment.deadline,
            PRIORITY_ORDER[assignment.priority],
            assignment.created_at,
        ),
    )
    progress_by_assignment = {
        row.assignment_id: row
        for row in TeacherAssignmentProgress.objects.filter(
            student=student,
            assignment__in=assignment_rows,
        )
    }
    previously_planned_assignment_ids = set(
        StudyPlanTask.objects.filter(
            assignment__in=assignment_rows,
            plan__student=student,
        ).exclude(plan=plan).values_list('assignment_id', flat=True)
    )
    assignment_minutes = 0
    for assignment in assignment_rows:
        assignment_progress = progress_by_assignment.get(assignment.pk)
        existing_assignment_task = current_assignment_tasks.get(assignment.pk)
        if assignment_progress and assignment_progress.is_completed:
            continue
        if existing_assignment_task and existing_assignment_task.status == StudyPlanTask.Status.COMPLETED:
            continue
        if assignment.pk in used_assignments:
            assignment_minutes += assignment.estimated_duration_minutes
            continue
        if assignment.pk in previously_planned_assignment_ids:
            assignment_minutes += assignment.estimated_duration_minutes
            conflicts.append(
                f'শিক্ষকের কাজ “{assignment.description}” আগের পরিকল্পনায় ছিল; শিক্ষকের অনুমতি ছাড়া সময় বদলানো হয়নি।'
            )
            continue
        duration = assignment.estimated_duration_minutes
        assignment_minutes += duration
        possible_days = [
            day for day in slots
            if day >= max(week_start, assignment.assigned_date)
            and day <= min(week_end, assignment.deadline)
        ]
        candidate_slots = {day: slots[day] for day in possible_days}
        slot = _find_slot(candidate_slots, duration)
        if slot:
            day, start, index = slot
            start_time, end_time = _place_task(
                slots, day, index, start, duration, preferences.break_duration_minutes,
            )
        else:
            day = None
            start_time = end_time = None
            if assignment.deadline < timezone.localdate():
                conflicts.append(f'শিক্ষকের কাজ “{assignment.description}”-এর deadline পেরিয়েছে—শিক্ষকের সঙ্গে যোগাযোগ করো।')
            else:
                conflicts.append(f'শিক্ষকের কাজ “{assignment.description}” উপলভ্য সময়ে বসানো যায়নি; deadline বা সময় নিয়ে শিক্ষকের সঙ্গে কথা বলো।')
        StudyPlanTask.objects.create(
            plan=plan,
            assignment=assignment,
            source=StudyPlanTask.Source.TEACHER,
            task_type=assignment.task_type,
            subject=assignment.subject,
            paper=assignment.paper,
            chapter=assignment.chapter,
            topic=assignment.topic,
            description=assignment.description,
            expected_outcome=assignment.instructions[:240],
            scheduled_date=day,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            priority=(
                TeacherStudyAssignment.Priority.MANDATORY
                if assignment.priority == TeacherStudyAssignment.Priority.MANDATORY
                else assignment.priority
            ),
        )

    ai_budget = max(
        0,
        min(
            weekly_availability_minutes - assignment_minutes,
            weekly_availability_minutes,
        ),
    )
    subjects = [subject for subject in preferences.subjects if subject in CURRICULUM]
    scores, exams = _performance_context(student, subjects, week_start, week_end)
    candidates = _study_candidates(student, subjects)
    completed_chapters = {
        (task.subject, task.paper, task.chapter, task.topic)
        for task in completed_tasks
        if task.source == StudyPlanTask.Source.AI
    }
    candidates = [
        candidate for candidate in candidates
        if (
            candidate['subject'],
            candidate['paper'],
            candidate['chapter'],
            candidate['topic'],
        ) not in completed_chapters
    ]
    for candidate in candidates:
        _apply_actual_priority(candidate, scores, exams, week_start)
    recommendation_candidates = []
    duration = preferences.session_duration_minutes
    slot_capacity = sum(
        (end - start + preferences.break_duration_minutes)
        // (duration + preferences.break_duration_minutes)
        for ranges in slots.values()
        for start, end in ranges
    )
    task_count = min(ai_budget // duration, slot_capacity) if candidates else 0
    selected_candidates = []
    for index in range(task_count):
        candidate = dict(candidates[index % len(candidates)])
        candidate['repeat_index'] = index // len(candidates)
        if candidate['repeat_index']:
            activities = (
                TeacherStudyAssignment.TaskType.LEARN,
                TeacherStudyAssignment.TaskType.MCQ,
                TeacherStudyAssignment.TaskType.CQ,
                TeacherStudyAssignment.TaskType.REVISE,
            )
            candidate['task_type'] = activities[candidate['repeat_index'] % len(activities)]
        selected_candidates.append(candidate)
    provider_candidates = []
    seen_candidate_keys = set()
    for candidate in selected_candidates:
        key = (
            candidate['subject'],
            candidate['paper'],
            candidate['chapter'],
            candidate['topic'],
        )
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        provider_candidates.append(candidate)
    provider_context = {
        'subjects': subjects,
        'study_preferences': {
            'session_duration_minutes': preferences.session_duration_minutes,
            'preferred_study_hours_per_day': preferences.preferred_study_hours,
            'exam_date': preferences.exam_date.isoformat() if preferences.exam_date else None,
        },
        'available_windows': [
            {
                'date': day.isoformat(),
                'intervals': [
                    {'start_minute': start, 'end_minute': end}
                    for start, end in ranges
                ],
            }
            for day, ranges in slots.items()
        ],
        'teacher_assignments': [
            {
                'subject': assignment.subject,
                'description': assignment.description,
                'deadline': assignment.deadline.isoformat(),
                'estimated_duration_minutes': assignment.estimated_duration_minutes,
                'priority': assignment.priority,
            }
            for assignment in assignment_rows
            if assignment.pk in used_assignments
            or not progress_by_assignment.get(assignment.pk)
            or not progress_by_assignment[assignment.pk].is_completed
        ],
        'chapter_progress': [
            {
                'subject': row.subject,
                'chapter': row.chapter,
                'status': row.status,
                'is_difficult': row.is_difficult,
                'needs_revision': row.needs_revision,
            }
            for row in StudentChapterProgress.objects.filter(student=student, subject__in=subjects)
        ],
        'recent_exam_scores_percent': scores,
        'upcoming_exams': [
            {'subject': exam.subject, 'title': exam.title, 'date': exam.exam_date.isoformat()}
            for exam in exams.values()
        ],
        'student_exam_date': (
            preferences.exam_date.isoformat()
            if preferences.exam_date else None
        ),
    }
    for candidate in provider_candidates:
        recommendation_candidates.append({
            'subject': candidate['subject'],
            'paper': candidate['paper'],
            'chapter': candidate['chapter'],
            'topic': candidate['topic'],
            'task_type': candidate['task_type'],
            'priority': candidate['priority'],
            'reason': candidate['reason'],
        })
    recommendations, generation_note, question_bank = _get_ai_recommendations(
        recommendation_candidates,
        provider_context,
    ) if recommendation_candidates else (
        None,
        'কোনো নির্বাচিত বিষয়ের অসম্পন্ন অধ্যায় নেই।',
        [],
    )
    recommendations_by_candidate = {
        (
            candidate['subject'],
            candidate['paper'],
            candidate['chapter'],
            candidate['topic'],
        ): recommendation
        for candidate, recommendation in zip(provider_candidates, recommendations or [])
    }
    chapter_candidates = {
        (candidate['subject'], candidate['paper'], candidate['chapter']): candidate
        for candidate in provider_candidates
    }
    topic_candidates = []
    for item in question_bank:
        chapter_key = (item['subject'], item['paper'], item['chapter'])
        chapter_candidate = chapter_candidates.get(chapter_key)
        if not chapter_candidate:
            continue
        StudentChapterProgress.objects.get_or_create(
            student=student,
            subject=item['subject'],
            paper=item['paper'],
            chapter=item['chapter'],
            topic=item['topic'],
        )
        topic_candidates.append({
            **chapter_candidate,
            'topic': item['topic'],
            'task_type': TeacherStudyAssignment.TaskType.LEARN,
            'topic_activities': True,
        })
    if topic_candidates:
        selected_candidates = []
        activity_sequence = (
            TeacherStudyAssignment.TaskType.LEARN,
            TeacherStudyAssignment.TaskType.MCQ,
            TeacherStudyAssignment.TaskType.CQ,
            TeacherStudyAssignment.TaskType.REVISE,
        )
        for index in range(task_count):
            candidate = dict(topic_candidates[index % len(topic_candidates)])
            candidate['repeat_index'] = index // len(topic_candidates)
            candidate['task_type'] = activity_sequence[
                candidate['repeat_index'] % len(activity_sequence)
            ]
            selected_candidates.append(candidate)
    recommendations_by_chapter = {
        key[:3]: recommendation
        for key, recommendation in recommendations_by_candidate.items()
    }
    day_order = list(slots)
    for index, candidate in enumerate(selected_candidates):
        duration = preferences.session_duration_minutes
        ordered_slots = {day: slots[day] for day in day_order}
        slot = _find_slot(ordered_slots, duration)
        if not slot:
            break
        day, start, slot_index = slot
        start_time, end_time = _place_task(
            slots, day, slot_index, start, duration, preferences.break_duration_minutes,
        )
        day_index = day_order.index(day)
        day_order = day_order[day_index + 1:] + day_order[:day_index + 1]
        candidate_key = (
            candidate['subject'],
            candidate['paper'],
            candidate['chapter'],
            candidate['topic'],
        )
        recommendation = recommendations_by_candidate.get(
            candidate_key,
            recommendations_by_chapter.get(candidate_key[:3], {}),
        )
        repeat_index = candidate['repeat_index']
        candidate_priority = candidate['priority']
        recommended_priority = recommendation.get('priority', candidate_priority)
        priority = min(
            (candidate_priority, recommended_priority),
            key=lambda value: PRIORITY_ORDER[value],
        )
        StudyPlanTask.objects.create(
            plan=plan,
            source=StudyPlanTask.Source.AI,
            task_type=(
                candidate['task_type']
                if candidate.get('topic_activities')
                else recommendation.get('task_type', candidate['task_type'])
                if repeat_index == 0
                else candidate['task_type']
            ),
            subject=candidate['subject'],
            paper=candidate['paper'],
            chapter=candidate['chapter'],
            topic=candidate['topic'],
            description=(
                recommendation.get('description')
                if repeat_index == 0
                else f'{candidate["chapter"]} · {candidate["task_type"].replace("_", " ").title()}'
            ) or (
                recommendation.get('description')
                or f'{candidate["chapter"]} · {candidate["task_type"].replace("_", " ").title()}'
            ),
            expected_outcome=(
                recommendation.get('expected_outcome')
                if repeat_index == 0
                else ''
            ) or (
                recommendation.get('expected_outcome')
                or f'{candidate["chapter"]} থেকে মূল ধারণা অনুশীলন ও যাচাই'
            ),
            recommendation_reason=(
                recommendation.get('reason')
                if repeat_index == 0
                else candidate['reason']
            ) or (
                recommendation.get('reason') or candidate['reason']
            ),
            scheduled_date=day,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            priority=priority,
        )
    plan.generation_note = generation_note
    plan.question_bank = question_bank
    plan.save(update_fields=['generation_note', 'question_bank', 'updated_at'])
    return plan, conflicts, True


def plan_summary(plan):
    tasks = list(plan.tasks.all())
    assigned_minutes = sum(
        task.duration_minutes for task in tasks
        if (
            task.status != StudyPlanTask.Status.SKIPPED
            and task.scheduled_date
            and task.start_time
            and task.end_time
        )
    )
    completed_count = sum(task.status == StudyPlanTask.Status.COMPLETED for task in tasks)
    pending_count = sum(task.status in (
        StudyPlanTask.Status.NOT_STARTED,
        StudyPlanTask.Status.IN_PROGRESS,
        StudyPlanTask.Status.RESCHEDULED,
    ) for task in tasks)
    return {
        'planned_hours': round(assigned_minutes / 60, 1),
        'completed_count': completed_count,
        'pending_count': pending_count,
        'total_count': len(tasks),
        'completion_percent': round(completed_count / len(tasks) * 100) if tasks else 0,
    }


def reschedule_ai_task(task):
    if task.source != StudyPlanTask.Source.AI or not task.scheduled_date:
        return False
    student = task.plan.student
    preferences = student.study_preference
    rest_days = set()
    slots = {}
    for offset in range(7):
        day = task.plan.week_start + timedelta(days=offset)
        daily_slots = _limit_daily_intervals(
            _available_intervals(student, day.weekday(), rest_days),
            preferences.preferred_study_hours * 60,
            preferences.break_duration_minutes,
            preferences.session_duration_minutes,
        )
        if day < task.scheduled_date:
            slots[day] = []
            continue
        slots[day] = daily_slots
        if day == task.scheduled_date:
            task_start = _to_minutes(task.start_time)
            task_end = _to_minutes(task.end_time) + preferences.break_duration_minutes
            slots[day] = _subtract_interval(slots[day], task_start, task_end)
            slots[day] = [
                (start, end)
                for start, end in slots[day]
                if end > task_end
            ]
    for other in task.plan.tasks.exclude(pk=task.pk).exclude(scheduled_date__isnull=True):
        day_slots = slots.get(other.scheduled_date)
        if day_slots is not None and other.start_time and other.end_time:
            slots[other.scheduled_date] = _subtract_interval(
                day_slots,
                _to_minutes(other.start_time),
                _to_minutes(other.end_time) + preferences.break_duration_minutes,
            )
    slot = _find_slot(slots, task.duration_minutes)
    if not slot:
        return False
    day, start, index = slot
    start_time, end_time = _place_task(
        slots, day, index, start, task.duration_minutes, preferences.break_duration_minutes,
    )
    task.scheduled_date = day
    task.start_time = start_time
    task.end_time = end_time
    task.status = StudyPlanTask.Status.RESCHEDULED
    task.save(update_fields=['scheduled_date', 'start_time', 'end_time', 'status', 'updated_at'])
    return True
