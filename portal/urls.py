from django.urls import path

from . import views
from . import study_planner_views
from . import topic_practice_views

urlpatterns = [
    path('install-app/', views.install_app, name='install_app'),
    path('account/profile/', views.account_profile, name='account_profile'),
    path('account/password/', views.account_password, name='account_password'),
    path('student/', views.student_dashboard, name='student_dashboard'),
    path(
        'student/fees/<str:month>/receipt.pdf',
        views.student_fee_receipt,
        name='student_fee_receipt',
    ),
    path('student/study-planner/', topic_practice_views.student_topic_practice, name='student_study_planner'),
    path(
        'student/study-planner/legacy/',
        study_planner_views.legacy_student_study_planner,
        name='legacy_student_study_planner',
    ),
    path(
        'student/study-practice/generate/',
        topic_practice_views.create_topic_practice,
        name='create_topic_practice',
    ),
    path(
        'student/study-practice/recommendations/',
        topic_practice_views.recommend_chapter_topics,
        name='recommend_chapter_topics',
    ),
    path(
        'student/study-practice/<int:session_id>/load-more/',
        topic_practice_views.load_more_topic_practice,
        name='load_more_topic_practice',
    ),
    path(
        'student/study-practice/questions/<int:question_id>/status/',
        topic_practice_views.update_topic_practice_status,
        name='update_topic_practice_status',
    ),
    path('student/study-planner/setup/', study_planner_views.save_study_planner_setup, name='save_study_planner_setup'),
    path('student/study-planner/generate/', study_planner_views.generate_student_study_plan, name='generate_student_study_plan'),
    path('student/study-planner/tasks/<int:task_id>/', study_planner_views.update_study_plan_task, name='update_study_plan_task'),
    path('teacher/study-assignments/', study_planner_views.teacher_study_assignments, name='teacher_study_assignments'),
    path(
        'student/classes/<int:session_id>/progress/',
        views.update_class_session_progress,
        name='update_class_session_progress',
    ),
    path(
        'teacher/support-session/join/',
        views.join_support_session,
        name='join_support_session',
    ),
    path('student/feedback/', views.student_feedback, name='student_feedback'),
    path('student/routine/', views.student_routine, name='student_routine'),
    path('student/books/', views.student_books, name='student_books'),
    path('student/exams/', views.student_exams, name='student_exams'),
    path('student/materials/', views.student_materials, name='student_materials'),
    path('student/statistics/', views.student_statistics, name='student_statistics'),
    path('student/results/', views.student_results, name='student_results'),
    path('classes/', views.class_management, name='class_management'),
    path(
        'classes/teacher-routine-version/',
        views.teacher_routine_version,
        name='teacher_routine_version',
    ),
    path('materials/', views.teacher_materials, name='teacher_materials'),
    path('materials/<int:material_id>/download/', views.download_material, name='download_material'),
    path('materials/<int:material_id>/delete/', views.delete_material, name='delete_material'),
    path('management/', views.admin_dashboard, name='admin_dashboard'),
    path('management/student-accounts/', views.admin_student_accounts, name='admin_student_accounts'),
    path(
        'management/student-accounts/<int:student_id>/<str:month>/receipt.pdf',
        views.admin_student_fee_receipt,
        name='admin_student_fee_receipt',
    ),
    path('management/student-feedback/', views.admin_student_feedback, name='admin_student_feedback'),
    path('management/teachers/', views.admin_teachers, name='admin_teachers'),
    path(
        'management/teachers/<int:teacher_id>/edit/',
        views.admin_teacher_edit,
        name='admin_teacher_edit',
    ),
    path(
        'management/teachers/<int:teacher_id>/delete/',
        views.admin_teacher_delete,
        name='admin_teacher_delete',
    ),
    path('management/teacher-attendance/', views.admin_teacher_attendance, name='admin_teacher_attendance'),
    path(
        'teacher-attendance/<int:routine_id>/request/',
        views.request_teacher_attendance,
        name='request_teacher_attendance',
    ),
]
