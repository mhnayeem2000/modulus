from django import forms

from portal.curriculum import SUBJECT_CHOICES
from portal.form_fields import configure_curriculum_fields
from portal.year_groups import BATCH_LABELS
from .models import Exam


class ExamForm(forms.ModelForm):
    subject = forms.ChoiceField(
        label='বিষয়',
        choices=[('', 'বিষয় নির্বাচন করুন'), *SUBJECT_CHOICES],
        help_text='HSC 2027-এর textbook-ভিত্তিক provisional তালিকা; চূড়ান্ত সিলেবাস মিলিয়ে নিন।',
    )

    class Meta:
        model = Exam
        fields = ['title', 'exam_date', 'year_group', 'subject', 'paper', 'chapter', 'topic', 'total_marks']
        widgets = {
            'exam_date': forms.DateInput(attrs={'type': 'date'}),
            'title': forms.TextInput(attrs={'placeholder': 'যেমন: সাপ্তাহিক পরীক্ষা ০৩'}),
            'paper': forms.TextInput(attrs={'placeholder': 'যেমন: পদার্থবিজ্ঞান ১ম পত্র'}),
            'chapter': forms.TextInput(attrs={'placeholder': 'যেমন: ভেক্টর'}),
            'topic': forms.TextInput(attrs={'placeholder': 'যেমন: ডট ও ক্রস গুণন'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_curriculum_fields(self)

    def save(self, commit=True):
        exam = super().save(commit=False)
        exam.class_name = BATCH_LABELS[exam.year_group]
        if commit:
            exam.save()
            self.save_m2m()
        return exam
