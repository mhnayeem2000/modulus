from django.contrib import admin

from portal.year_groups import BATCH_LABELS
from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    exclude = ('class_name',)
    list_display = ('student_id', 'name', 'year_group_label', 'phone', 'guardian_phone', 'is_active')
    list_filter = ('year_group', 'is_active')
    search_fields = ('student_id', 'name', 'phone', 'guardian_phone')

    @admin.display(description='বর্ষ')
    def year_group_label(self, student):
        return student.get_year_group_display()

    def save_model(self, request, obj, form, change):
        obj.class_name = BATCH_LABELS[obj.year_group]
        super().save_model(request, obj, form, change)
