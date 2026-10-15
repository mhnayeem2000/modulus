from django.urls import path

from . import views

urlpatterns = [
    path('', views.attendance_list, name='attendance_list'),
    path('sms-system/', views.sms_system, name='sms_system'),
    path('sms-api/state/', views.sms_state_api, name='sms_state_api'),
    path('sms-api/balance/', views.sms_balance_api, name='sms_balance_api'),
    path('sms-report/', views.sms_report, name='sms_report'),
]
