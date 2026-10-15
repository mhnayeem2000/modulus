from django.urls import path

from . import views

urlpatterns = [
    path('install-app/', views.install_app, name='install_app'),
    path('account/profile/', views.account_profile, name='account_profile'),
    path('account/password/', views.account_password, name='account_password'),
    path('student/', views.student_dashboard, name='student_dashboard'),
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
