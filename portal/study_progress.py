from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from students.models import Student

from .models import ClassSessionProgress, UserProfile
from .year_groups import BATCH_CHOICES


def get_study_report_date(raw_date):
    if not raw_date:
        return timezone.localdate()
    return parse_date(raw_date) or timezone.localdate()


def build_class_session_progress(sessions):
    sessions = list(
        sessions.select_related('teacher')
        .annotate(
            completed_student_count=Count(
                'student_progress',
                filter=Q(
                    student_progress__is_completed=True,
                    student_progress__student__is_active=True,
                    student_progress__student__user__isnull=False,
                    student_progress__student__user__profile__role=UserProfile.Role.STUDENT,
                    student_progress__student__year_group=F('year_group'),
                ),
                distinct=True,
            ),
            submitted_student_count=Count(
                'student_progress',
                filter=Q(
                    student_progress__student__is_active=True,
                    student_progress__student__user__isnull=False,
                    student_progress__student__user__profile__role=UserProfile.Role.STUDENT,
                    student_progress__student__year_group=F('year_group'),
                ),
                distinct=True,
            ),
        )
    )
    student_counts = dict(
        Student.objects.filter(
            is_active=True,
            user__isnull=False,
            user__profile__role=UserProfile.Role.STUDENT,
            year_group__in={session.year_group for session in sessions},
        )
        .values('year_group')
        .annotate(total=Count('pk'))
        .values_list('year_group', 'total')
    )
    for session in sessions:
        session.eligible_student_count = student_counts.get(session.year_group, 0)
        session.not_completed_student_count = max(
            session.eligible_student_count - session.completed_student_count,
            0,
        )
        session.progress_reports = []
    return sessions


def paginate_study_progress(sessions, page_number):
    sessions = list(sessions)
    if not sessions:
        return sessions, Paginator([], 15).get_page(page_number)

    progress_reports = ClassSessionProgress.objects.filter(
        session_id__in=[session.pk for session in sessions],
        student__is_active=True,
        student__user__isnull=False,
        student__user__profile__role=UserProfile.Role.STUDENT,
        student__year_group=F('session__year_group'),
    ).select_related(
        'session',
        'student',
        'session__teacher',
    ).order_by(
        'session__year_group',
        'session__subject',
        'session_id',
        'student__name',
        'pk',
    )
    page = Paginator(progress_reports, 15).get_page(page_number)
    reports_by_session = {}
    for progress in page.object_list:
        reports_by_session.setdefault(progress.session_id, []).append(progress)
    for session in sessions:
        session.progress_reports = reports_by_session.get(session.pk, [])
    return sessions, page


def group_class_session_progress(sessions):
    sessions_by_year = {
        year_group: []
        for year_group, _ in BATCH_CHOICES
    }
    for session in sessions:
        if session.year_group in sessions_by_year:
            sessions_by_year[session.year_group].append(session)
    return [
        {
            'key': year_group,
            'label': label,
            'sessions': sessions_by_year[year_group],
        }
        for year_group, label in BATCH_CHOICES
    ]
