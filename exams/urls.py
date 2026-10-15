from django.urls import path

from . import views

urlpatterns = [
    path('', views.exam_list, name='exam_list'),
    path('<int:exam_id>/edit/', views.exam_edit, name='exam_edit'),
    path('<int:exam_id>/results/', views.exam_results, name='exam_results'),
]
