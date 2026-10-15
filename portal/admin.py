from django.contrib import admin

from .year_groups import BATCH_LABELS
from .models import (
    ClassSession,
    LearningMaterial,
    Routine,
    SupportSessionAttendance,
    TeacherAttendance,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone')


@admin.register(Routine)
class RoutineAdmin(admin.ModelAdmin):
    exclude = ('class_name',)
    list_display = ('year_group_label', 'weekday', 'start_time', 'end_time', 'subject', 'teacher')
    list_filter = ('weekday', 'year_group', 'teacher')
    search_fields = ('class_name', 'subject', 'chapter', 'teacher__username')

    @admin.display(description='বর্ষ')
    def year_group_label(self, routine):
        return routine.get_year_group_display()

    def save_model(self, request, obj, form, change):
        obj.class_name = BATCH_LABELS[obj.year_group]
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'date', 'routine', 'status', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'date')
    search_fields = ('teacher__username', 'teacher__first_name', 'routine__class_name')
    readonly_fields = ('requested_at',)


@admin.register(SupportSessionAttendance)
class SupportSessionAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'date', 'joined_at')
    list_filter = ('date', 'teacher')
    search_fields = ('teacher__username', 'teacher__first_name', 'teacher__last_name')
    readonly_fields = ('joined_at',)


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    exclude = ('class_name',)
    list_display = ('date', 'year_group_label', 'subject', 'chapter', 'topic', 'teacher')
    list_filter = ('date', 'year_group', 'teacher')
    search_fields = ('class_name', 'subject', 'chapter', 'topic', 'teacher__username')

    @admin.display(description='বর্ষ')
    def year_group_label(self, session):
        return session.get_year_group_display()

    def save_model(self, request, obj, form, change):
        obj.class_name = BATCH_LABELS[obj.year_group]
        super().save_model(request, obj, form, change)


@admin.register(LearningMaterial)
class LearningMaterialAdmin(admin.ModelAdmin):
    exclude = ('class_name',)
    list_display = ('title', 'kind', 'year_group_label', 'subject', 'paper', 'chapter', 'uploaded_by', 'created_at')
    list_filter = ('kind', 'year_group', 'subject')
    search_fields = ('title', 'subject', 'paper', 'chapter', 'uploaded_by__username')

    @admin.display(description='বর্ষ')
    def year_group_label(self, material):
        return material.get_year_group_display() if material.year_group else 'সব বর্ষ'

    def save_model(self, request, obj, form, change):
        obj.class_name = BATCH_LABELS.get(obj.year_group, '')
        super().save_model(request, obj, form, change)
