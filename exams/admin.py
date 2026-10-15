from django.contrib import admin

from portal.year_groups import BATCH_LABELS
from .models import Exam, ExamResult


class ExamResultInline(admin.TabularInline):
    model = ExamResult
    extra = 0


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    exclude = ('class_name',)
    list_display = ('title', 'exam_date', 'year_group_label', 'subject', 'paper', 'chapter', 'topic', 'total_marks')
    list_filter = ('exam_date', 'year_group', 'subject')
    search_fields = ('title', 'paper', 'chapter', 'topic')
    inlines = [ExamResultInline]

    @admin.display(description='বর্ষ')
    def year_group_label(self, exam):
        return exam.get_year_group_display()

    def save_model(self, request, obj, form, change):
        obj.class_name = BATCH_LABELS[obj.year_group]
        super().save_model(request, obj, form, change)


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ('exam', 'student', 'marks', 'recorded_by', 'updated_at')
    list_filter = ('exam', 'exam__exam_date')
    search_fields = ('student__name', 'student__student_id', 'exam__title')
