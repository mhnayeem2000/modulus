import json
from datetime import date

from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import role_required
from .curriculum import CURRICULUM, SUBJECT_CHOICES
from .models import TopicPracticeQuestion, TopicPracticeSession
from .topic_practice import (
    CQ_INITIAL_COUNT,
    CQ_MORE_COUNT,
    MCQ_INITIAL_COUNT,
    MCQ_MORE_COUNT,
    KHO_INITIAL_COUNT,
    KHO_MORE_COUNT,
    KO_INITIAL_COUNT,
    KO_MORE_COUNT,
    TopicPracticeError,
    generate_topic_practice,
    generate_topic_recommendations,
)
from .study_planner_views import _student_for_user


def _practice_session_html(request, session, expanded=False):
    batch_counts = {
        TopicPracticeSession.QuestionType.CQ: CQ_MORE_COUNT,
        TopicPracticeSession.QuestionType.MCQ: MCQ_MORE_COUNT,
        TopicPracticeSession.QuestionType.KO: KO_MORE_COUNT,
        TopicPracticeSession.QuestionType.KHO: KHO_MORE_COUNT,
    }
    return render_to_string(
        'portal/partials/topic_practice_session.html',
        {
            'session': session,
            'expanded': expanded,
            'batch_count': batch_counts[session.question_type],
        },
        request=request,
    )


@role_required('student')
def student_topic_practice(request):
    student = _student_for_user(request.user)
    sessions = TopicPracticeSession.objects.filter(student=student)
    raw_date = request.GET.get('date', '').strip()
    selected_date = None
    date_error = ''
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            date_error = 'তারিখটি সঠিক নয়; YYYY-MM-DD format ব্যবহার করুন।'
    if selected_date:
        sessions = sessions.filter(created_at__date=selected_date)
    selected_subject = request.GET.get('subject', '')
    if selected_subject in CURRICULUM:
        sessions = sessions.filter(subject=selected_subject)
    else:
        selected_subject = ''
    sessions = sessions.prefetch_related('questions').order_by('-created_at', '-pk')
    session_page = Paginator(sessions, 10).get_page(request.GET.get('page'))
    return render(request, 'portal/student_topic_practice.html', {
        'student': student,
        'subjects': SUBJECT_CHOICES,
        'curriculum_json': json.dumps(CURRICULUM, ensure_ascii=False),
        'session_page': session_page,
        'selected_date': raw_date if selected_date else '',
        'selected_subject': selected_subject,
        'date_error': date_error,
        'today': timezone.localdate(),
    })


@role_required('student')
@require_POST
def create_topic_practice(request):
    student = _student_for_user(request.user)
    subject = request.POST.get('subject', '').strip()
    paper = request.POST.get('paper', '').strip()
    chapter = request.POST.get('chapter', '').strip()
    topic = request.POST.get('topic', '').strip()
    question_type = request.POST.get('question_type', '').strip()
    if subject not in CURRICULUM:
        return JsonResponse({'success': False, 'error': 'বিষয়টি curriculum-এ নেই।'}, status=400)
    if paper not in CURRICULUM[subject]:
        return JsonResponse({'success': False, 'error': 'সঠিক paper নির্বাচন করুন।'}, status=400)
    if chapter not in CURRICULUM[subject][paper]:
        return JsonResponse({'success': False, 'error': 'সঠিক chapter নির্বাচন করুন।'}, status=400)
    if not topic or len(topic) > 160:
        return JsonResponse({
            'success': False,
            'error': 'Topic লিখুন (সর্বোচ্চ ১৬০ অক্ষর)।',
        }, status=400)
    initial_counts = {
        TopicPracticeSession.QuestionType.CQ: CQ_INITIAL_COUNT,
        TopicPracticeSession.QuestionType.MCQ: MCQ_INITIAL_COUNT,
        TopicPracticeSession.QuestionType.KO: KO_INITIAL_COUNT,
        TopicPracticeSession.QuestionType.KHO: KHO_INITIAL_COUNT,
    }
    if question_type not in initial_counts:
        return JsonResponse({
            'success': False,
            'error': 'CQ, MCQ, ক (জ্ঞান) বা খ (অনুধাবন) বেছে নিন।',
        }, status=400)
    count = initial_counts[question_type]
    try:
        questions = generate_topic_practice(
            subject,
            paper,
            chapter,
            topic,
            question_type,
            count,
        )
    except TopicPracticeError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    with transaction.atomic():
        session = TopicPracticeSession.objects.create(
            student=student,
            subject=subject,
            paper=paper,
            chapter=chapter,
            topic=topic,
            question_type=question_type,
            sources=[],
        )
        TopicPracticeQuestion.objects.bulk_create([
            TopicPracticeQuestion(
                session=session,
                sequence=index,
                prompt=item['prompt'],
                choices=item['choices'],
                answer=item['answer'],
                explanation=item['explanation'],
            )
            for index, item in enumerate(questions, start=1)
        ])
    session = TopicPracticeSession.objects.prefetch_related('questions').get(pk=session.pk)
    history_date = request.POST.get('history_date', '')
    history_subject = request.POST.get('history_subject', '')
    history_matches = (
        (not history_date or history_date == timezone.localdate().isoformat())
        and (not history_subject or history_subject == subject)
    )
    return JsonResponse({
        'success': True,
        'message': f'{count}টি original practice question তৈরি ও save হয়েছে।',
        'html': _practice_session_html(request, session, expanded=True),
        'history_html': _practice_session_html(request, session),
        'history_matches': history_matches,
    })


@role_required('student')
@require_POST
def recommend_chapter_topics(request):
    subject = request.POST.get('subject', '').strip()
    paper = request.POST.get('paper', '').strip()
    chapter = request.POST.get('chapter', '').strip()
    if subject not in CURRICULUM:
        return JsonResponse({'success': False, 'error': 'বিষয়টি curriculum-এ নেই।'}, status=400)
    if paper not in CURRICULUM[subject]:
        return JsonResponse({'success': False, 'error': 'সঠিক paper নির্বাচন করুন।'}, status=400)
    if chapter not in CURRICULUM[subject][paper]:
        return JsonResponse({'success': False, 'error': 'সঠিক chapter নির্বাচন করুন।'}, status=400)
    try:
        recommendations = generate_topic_recommendations(subject, paper, chapter)
    except TopicPracticeError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    html = render_to_string(
        'portal/partials/topic_practice_recommendations.html',
        {'chapter': chapter, 'recommendations': recommendations},
        request=request,
    )
    return JsonResponse({
        'success': True,
        'message': 'CQ ও MCQ-এর জন্য topic suggestion তৈরি হয়েছে।',
        'html': html,
    })


@role_required('student')
@require_POST
def load_more_topic_practice(request, session_id):
    student = _student_for_user(request.user)
    session = get_object_or_404(
        TopicPracticeSession,
        pk=session_id,
        student=student,
    )
    more_counts = {
        TopicPracticeSession.QuestionType.CQ: CQ_MORE_COUNT,
        TopicPracticeSession.QuestionType.MCQ: MCQ_MORE_COUNT,
        TopicPracticeSession.QuestionType.KO: KO_MORE_COUNT,
        TopicPracticeSession.QuestionType.KHO: KHO_MORE_COUNT,
    }
    count = more_counts[session.question_type]
    try:
        questions = generate_topic_practice(
            session.subject,
            session.paper,
            session.chapter,
            session.topic,
            session.question_type,
            count,
        )
    except TopicPracticeError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    with transaction.atomic():
        last_sequence = session.questions.order_by('-sequence').values_list(
            'sequence',
            flat=True,
        ).first() or 0
        TopicPracticeQuestion.objects.bulk_create([
            TopicPracticeQuestion(
                session=session,
                sequence=last_sequence + index,
                prompt=item['prompt'],
                choices=item['choices'],
                answer=item['answer'],
                explanation=item['explanation'],
            )
            for index, item in enumerate(questions, start=1)
        ])
    session = TopicPracticeSession.objects.prefetch_related('questions').get(pk=session.pk)
    return JsonResponse({
        'success': True,
        'message': f'আরও {count}টি প্রশ্ন যোগ হয়েছে।',
        'html': _practice_session_html(request, session, expanded=True),
        'question_count': session.questions.count(),
    })


@role_required('student')
@require_POST
def update_topic_practice_status(request, question_id):
    student = _student_for_user(request.user)
    question = get_object_or_404(
        TopicPracticeQuestion.objects.select_related('session'),
        pk=question_id,
        session__student=student,
    )
    status = request.POST.get('status', '')
    if status not in TopicPracticeQuestion.Status.values:
        return JsonResponse({'success': False, 'error': 'Progress option সঠিক নয়।'}, status=400)
    question.status = status
    question.save(update_fields=['status'])
    return JsonResponse({
        'success': True,
        'status': question.status,
        'status_label': question.get_status_display(),
        'message': 'Progress save হয়েছে।',
    })
