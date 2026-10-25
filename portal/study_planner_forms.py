import json

from django import forms
from django.forms import BaseModelFormSet, modelformset_factory

from students.models import Student

from .curriculum import CURRICULUM, SUBJECT_CHOICES, chapter_choices, paper_choices
from .models import (
    StudentChapterProgress,
    StudentScheduleInterval,
    StudentStudyPreference,
    TeacherStudyAssignment,
)
from .year_groups import BATCH_CHOICES


WEEKDAY_CHOICES = (
    (0, 'সোমবার'),
    (1, 'মঙ্গলবার'),
    (2, 'বুধবার'),
    (3, 'বৃহস্পতিবার'),
    (4, 'শুক্রবার'),
    (5, 'শনিবার'),
    (6, 'রবিবার'),
)


class StudentStudyPreferenceForm(forms.ModelForm):
    preferred_study_hours = forms.IntegerField(
        label='প্রতিদিন কত ঘণ্টা পড়তে পারবে?',
        min_value=1,
        max_value=12,
        required=False,
        widget=forms.NumberInput(attrs={'min': 1, 'max': 12, 'step': 1}),
    )
    exam_date = forms.DateField(
        label='পরের পরীক্ষার তারিখ',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
    )

    subjects = forms.MultipleChoiceField(
        label='আমার বিষয়',
        choices=SUBJECT_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    class Meta:
        model = StudentStudyPreference
        fields = (
            'preferred_study_hours',
            'subjects',
            'exam_date',
        )
        widgets = {
            'exam_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_exam_date(self):
        exam_date = self.cleaned_data['exam_date']
        from django.utils import timezone

        if exam_date and exam_date < timezone.localdate():
            raise forms.ValidationError('পরীক্ষার তারিখ আজকের বা পরের হতে হবে।')
        return exam_date

    def clean_preferred_study_hours(self):
        hours = self.cleaned_data.get('preferred_study_hours')
        return hours or self.instance.preferred_study_hours or 2

    def clean_subjects(self):
        subjects = self.cleaned_data.get('subjects', [])
        if not subjects:
            raise forms.ValidationError('অন্তত একটি বিষয় বেছে নাও।')
        return subjects


class StudentScheduleIntervalForm(forms.ModelForm):
    weekday = forms.TypedChoiceField(
        choices=WEEKDAY_CHOICES,
        coerce=int,
        label='দিন',
        required=False,
    )
    kind = forms.ChoiceField(
        choices=StudentScheduleInterval.Kind.choices,
        label='রুটিনের ধরন',
    )
    start_time = forms.TimeField(
        label='শুরু',
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time'}),
    )
    end_time = forms.TimeField(
        label='শেষ',
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time'}),
    )

    class Meta:
        model = StudentScheduleInterval
        fields = ('weekday', 'kind', 'start_time', 'end_time')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        weekday = cleaned_data.get('weekday')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if weekday in (None, '') and start_time is None and end_time is None:
            return cleaned_data
        if weekday in (None, ''):
            self.add_error('weekday', 'দিন বেছে নাও।')
        if start_time is None:
            self.add_error('start_time', 'শুরুর সময় দাও।')
        if end_time is None:
            self.add_error('end_time', 'শেষের সময় দাও।')
        if start_time and end_time and end_time <= start_time:
            self.add_error('end_time', 'শেষের সময় শুরুর সময়ের পরে হতে হবে।')
        return cleaned_data


class StudentChapterProgressForm(forms.ModelForm):
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES, label='বিষয়')
    paper = forms.ChoiceField(choices=(), required=False, label='পত্র')
    chapter = forms.ChoiceField(choices=(), label='অধ্যায়')
    status = forms.ChoiceField(
        choices=(('', 'অগ্রগতি বাছাই করুন'), *StudentChapterProgress.Status.choices),
        label='অবস্থা',
        initial='',
        required=False,
    )

    class Meta:
        model = StudentChapterProgress
        fields = (
            'subject',
            'paper',
            'chapter',
            'topic',
            'status',
        )
        widgets = {
            'topic': forms.TextInput(attrs={'placeholder': 'ঐচ্ছিক টপিক'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subject = (
            self.data.get(self.add_prefix('subject'))
            if self.is_bound
            else self.instance.subject
        )
        paper = self.data.get(self.add_prefix('paper')) if self.is_bound else self.instance.paper
        self.fields['paper'].choices = [('', 'প্রযোজ্য নয়'), *paper_choices(subject)]
        self.fields['chapter'].choices = [('', 'অধ্যায় বাছাই করুন'), *chapter_choices(subject, paper)]
        self.fields['subject'].widget.attrs['data-curriculum'] = json.dumps(CURRICULUM, ensure_ascii=False)

    def clean_status(self):
        return self.cleaned_data.get('status') or StudentChapterProgress.Status.NOT_STARTED


class BaseStudentChapterProgressFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            subject = form.cleaned_data.get('subject')
            paper = form.cleaned_data.get('paper') or ''
            chapter = form.cleaned_data.get('chapter')
            topic = (form.cleaned_data.get('topic') or '').strip()
            if not subject or not chapter:
                continue
            if chapter not in dict(chapter_choices(subject, paper)):
                form.add_error('chapter', 'নির্বাচিত পত্রে এই অধ্যায় নেই।')
            key = (subject, paper, chapter, topic)
            if key in seen:
                form.add_error('chapter', 'একই অধ্যায় ও টপিক একাধিকবার যোগ করা হয়েছে।')
            seen.add(key)


StudentScheduleIntervalFormSet = forms.modelformset_factory(
    StudentScheduleInterval,
    form=StudentScheduleIntervalForm,
    extra=1,
    can_delete=True,
    max_num=42,
    validate_max=True,
)
StudentChapterProgressFormSet = modelformset_factory(
    StudentChapterProgress,
    form=StudentChapterProgressForm,
    formset=BaseStudentChapterProgressFormSet,
    extra=1,
    can_delete=True,
    max_num=100,
    validate_max=True,
)


class TeacherStudyAssignmentForm(forms.ModelForm):
    target = forms.ChoiceField(
        label='কাকে দেবেন?',
        choices=(('student', 'একজন শিক্ষার্থী'), ('batch', 'পুরো ব্যাচ')),
    )
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES, label='বিষয়')
    paper = forms.ChoiceField(choices=(), required=False, label='পত্র')
    chapter = forms.ChoiceField(choices=(), required=False, label='অধ্যায়')
    year_group = forms.ChoiceField(choices=BATCH_CHOICES, required=False, label='বর্ষ')
    class_name = forms.ChoiceField(choices=(), required=False, label='ব্যাচ')

    class Meta:
        model = TeacherStudyAssignment
        fields = (
            'target',
            'student',
            'year_group',
            'class_name',
            'subject',
            'paper',
            'chapter',
            'topic',
            'task_type',
            'description',
            'instructions',
            'assigned_date',
            'deadline',
            'estimated_duration_minutes',
            'priority',
        )
        widgets = {
            'topic': forms.TextInput(attrs={'placeholder': 'ঐচ্ছিক টপিক'}),
            'description': forms.TextInput(attrs={'placeholder': 'যেমন: অধ্যায় ৩-এর অনুশীলনী'}),
            'instructions': forms.Textarea(attrs={'rows': 3}),
            'assigned_date': forms.DateInput(attrs={'type': 'date'}),
            'deadline': forms.DateInput(attrs={'type': 'date'}),
            'estimated_duration_minutes': forms.NumberInput(attrs={'min': 15, 'max': 240, 'step': 15}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.filter(is_active=True).order_by('name')
        self.fields['student'].required = False
        class_names = Student.objects.filter(is_active=True).values_list('class_name', flat=True).distinct()
        self.fields['class_name'].choices = [('', 'ব্যাচ বাছাই করুন'), *((name, name) for name in class_names)]
        subject = self.data.get('subject') if self.is_bound else self.instance.subject
        paper = self.data.get('paper') if self.is_bound else self.instance.paper
        self.fields['paper'].choices = [('', 'পত্র বাছাই করুন'), *paper_choices(subject)]
        self.fields['chapter'].choices = [('', 'অধ্যায় বাছাই করুন'), *chapter_choices(subject, paper)]
        self.fields['subject'].widget.attrs['data-curriculum'] = json.dumps(CURRICULUM, ensure_ascii=False)

    def clean(self):
        cleaned_data = super().clean()
        target = cleaned_data.get('target')
        if target == 'student' and not cleaned_data.get('student'):
            self.add_error('student', 'একজন শিক্ষার্থী বাছাই করুন।')
        if target == 'batch' and not (
            cleaned_data.get('year_group') and cleaned_data.get('class_name')
        ):
            self.add_error('class_name', 'বর্ষ ও ব্যাচ বাছাই করুন।')
        elif target == 'batch' and not Student.objects.filter(
            is_active=True,
            year_group=cleaned_data.get('year_group'),
            class_name=cleaned_data.get('class_name'),
        ).exists():
            self.add_error('class_name', 'এই বর্ষ ও ব্যাচে কোনো সক্রিয় শিক্ষার্থী নেই।')
        assigned_date = cleaned_data.get('assigned_date')
        deadline = cleaned_data.get('deadline')
        if assigned_date and deadline and deadline < assigned_date:
            self.add_error('deadline', 'জমার শেষ তারিখ নির্ধারিত তারিখের আগে হতে পারে না।')
        subject = cleaned_data.get('subject')
        paper = cleaned_data.get('paper')
        chapter = cleaned_data.get('chapter')
        if paper and paper not in dict(paper_choices(subject)):
            self.add_error('paper', 'নির্বাচিত বিষয়ের পত্রটি বৈধ নয়।')
        if chapter and chapter not in dict(chapter_choices(subject, paper)):
            self.add_error('chapter', 'নির্বাচিত পত্রে এই অধ্যায় নেই।')
        duration = cleaned_data.get('estimated_duration_minutes')
        if duration is not None and not 15 <= duration <= 240:
            self.add_error('estimated_duration_minutes', 'কাজের সময় ১৫ থেকে ২৪০ মিনিটের মধ্যে হতে হবে।')
        return cleaned_data

    def save(self, commit=True):
        assignment = super().save(commit=False)
        if self.cleaned_data['target'] == 'student':
            assignment.class_name = ''
            assignment.year_group = ''
        else:
            assignment.student = None
        if commit:
            assignment.save()
        return assignment
