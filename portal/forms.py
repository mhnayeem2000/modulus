from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from students.models import Student

from .form_fields import configure_curriculum_fields
from .year_groups import BATCH_LABELS
from .models import ClassSession, LearningMaterial, Routine, StudentFeeRecord, StudentFeedback


User = get_user_model()


class AccountProfileForm(forms.ModelForm):
    phone = forms.CharField(
        label='মোবাইল নম্বর',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'autocomplete': 'tel', 'placeholder': 'আপনার মোবাইল নম্বর'}),
    )
    student_name = forms.CharField(
        label='আপনার নাম',
        max_length=120,
        widget=forms.TextInput(attrs={'autocomplete': 'name', 'placeholder': 'আপনার পূর্ণ নাম'}),
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')
        labels = {
            'first_name': 'নামের প্রথম অংশ',
            'last_name': 'নামের শেষ অংশ',
            'email': 'ইমেইল',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email'}),
        }

    def __init__(self, *args, profile, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.student = student
        if student:
            self.fields.pop('first_name')
            self.fields.pop('last_name')
            self.fields['student_name'].initial = student.name
            self.fields['phone'].initial = student.phone
        else:
            self.fields.pop('student_name')
            self.fields['phone'].initial = profile.phone if profile else ''
            if not profile:
                self.fields.pop('phone')

    def save(self, commit=True):
        user = super().save(commit=commit)
        if not commit:
            return user
        if self.student:
            self.student.name = self.cleaned_data['student_name']
            self.student.phone = self.cleaned_data['phone']
            self.student.save(update_fields=['name', 'phone'])
        elif self.profile:
            self.profile.phone = self.cleaned_data['phone']
            self.profile.save(update_fields=['phone'])
        return user


class AccountPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'বর্তমান পাসওয়ার্ড'
        self.fields['old_password'].widget.attrs['autocomplete'] = 'current-password'
        self.fields['new_password1'].label = 'নতুন পাসওয়ার্ড'
        self.fields['new_password1'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['new_password1'].help_text = (
            'নতুন পাসওয়ার্ডটি শক্তিশালী এবং সহজে অনুমান করা যায় না—এমন রাখুন।'
        )
        self.fields['new_password2'].label = 'নতুন পাসওয়ার্ড নিশ্চিত করুন'
        self.fields['new_password2'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['new_password2'].help_text = 'নিশ্চিত করতে একই নতুন পাসওয়ার্ড আবার লিখুন।'


class RoutineForm(forms.ModelForm):
    class Meta:
        model = Routine
        fields = [
            'year_group', 'weekday', 'teacher', 'subject',
            'paper', 'chapter', 'is_revision', 'start_time', 'end_time',
        ]
        widgets = {
            'subject': forms.TextInput(attrs={'placeholder': 'যেমন: পদার্থবিজ্ঞান'}),
            'paper': forms.TextInput(attrs={'placeholder': 'যেমন: ১ম পত্র'}),
            'chapter': forms.TextInput(attrs={'placeholder': 'যেমন: ভেক্টর'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        start_time_choices = [('', 'শুরুর সময় বাছাই করুন')]
        end_time_choices = [('', 'শেষের সময়')]
        for minute_of_day in range(9 * 60, 10 * 60 + 31, 15):
            hour, minute = divmod(minute_of_day, 60)
            start_time_choices.append((f'{hour:02d}:{minute:02d}', f'সকাল {hour}:{minute:02d}'))
        for minute_of_day in range(14 * 60, 17 * 60 + 31, 15):
            hour, minute = divmod(minute_of_day, 60)
            period = 'দুপুর' if hour < 15 else 'বিকেল'
            hour_12 = hour % 12 or 12
            start_time_choices.append((
                f'{hour:02d}:{minute:02d}',
                f'{period} {hour_12}:{minute:02d}',
            ))
        for minute_of_day in range(10 * 60 + 30, 12 * 60 + 1, 15):
            hour, minute = divmod(minute_of_day, 60)
            end_time_choices.append((f'{hour:02d}:{minute:02d}', f'সকাল {hour}:{minute:02d}'))
        for minute_of_day in range(15 * 60 + 30, 19 * 60 + 1, 15):
            hour, minute = divmod(minute_of_day, 60)
            period = 'বিকেল' if hour < 18 else 'সন্ধ্যা'
            hour_12 = hour % 12 or 12
            end_time_choices.append((
                f'{hour:02d}:{minute:02d}',
                f'{period} {hour_12}:{minute:02d}',
            ))
        for field_name, choices in (
            ('start_time', start_time_choices),
            ('end_time', end_time_choices),
        ):
            field = self.fields[field_name]
            field.widget = forms.Select(choices=choices)
            existing_value = getattr(self.instance, field_name, None)
            if existing_value:
                value = existing_value.strftime('%H:%M')
                if value not in dict(choices):
                    field.widget.choices = [*choices, (value, existing_value.strftime('%I:%M %p'))]

        self.fields['year_group'].choices = [
            ('', 'বর্ষ নির্বাচন করুন'),
            *Routine.YearGroup.choices,
        ]
        self.fields['year_group'].required = True
        self.fields['is_revision'].help_text = (
            'প্রতিটি ক্লাস ১ ঘণ্টা ৩০ মিনিট। শুক্রবার সকাল ৯টা–দুপুর ১২টা; অন্যদিন সাধারণ ক্লাস বিকেল ৩টা–৭টা, রিভিশন ক্লাস দুপুর ২টা–৩টার মধ্যে শুরু হবে।'
        )
        self.fields['teacher'].queryset = get_user_model().objects.filter(
            profile__role='teacher',
        ).order_by('first_name', 'username')
        configure_curriculum_fields(self)
        self.fields['paper'].required = True
        self.fields['chapter'].required = True

    def save(self, commit=True):
        routine = super().save(commit=False)
        routine.class_name = BATCH_LABELS[routine.year_group]
        if commit:
            routine.save()
            self.save_m2m()
        return routine

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        is_revision = cleaned_data.get('is_revision', False)
        if not start_time or not end_time:
            return cleaned_data

        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        if end_minutes - start_minutes != 90:
            self.add_error('end_time', 'প্রতিটি ক্লাসের সময় ঠিক ১ ঘণ্টা ৩০ মিনিট হতে হবে।')

        if cleaned_data.get('weekday') == Routine.Weekday.FRIDAY:
            if start_minutes < 9 * 60 or end_minutes > 12 * 60:
                self.add_error('start_time', 'শুক্রবারের ক্লাস সকাল ৯টা থেকে দুপুর ১২টার মধ্যে হতে হবে।')
        elif is_revision:
            if not 14 * 60 <= start_minutes < 15 * 60:
                self.add_error('start_time', 'রিভিশন ক্লাস দুপুর ২টা থেকে ৩টার মধ্যে শুরু হতে হবে।')
        elif start_minutes < 15 * 60 or end_minutes > 19 * 60:
            self.add_error('start_time', 'সাধারণ ক্লাস বিকেল ৩টা থেকে শুরু করে ৭টার মধ্যে শেষ হতে হবে।')

        return cleaned_data


class ClassSessionForm(forms.ModelForm):
    class Meta:
        model = ClassSession
        exclude = ['teacher', 'created_at', 'start_time', 'end_time', 'class_name']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'subject': forms.TextInput(attrs={'placeholder': 'যেমন: পদার্থবিজ্ঞান'}),
            'paper': forms.TextInput(attrs={'placeholder': 'যেমন: ১ম পত্র'}),
            'chapter': forms.TextInput(attrs={'placeholder': 'আজ যে অধ্যায় পড়িয়েছেন'}),
            'topic': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'আজকের ক্লাসে কী কী পড়ানো হয়েছে বিস্তারিত লিখুন',
            }),
        }

    def __init__(self, *args, **kwargs):
            self.teacher = kwargs.pop('teacher', None)
            super().__init__(*args, **kwargs)
            if not self.is_bound and not self.instance.pk:
                self.initial.setdefault('date', timezone.localdate())
            configure_curriculum_fields(self)

    def save(self, commit=True):
        session = super().save(commit=False)
        session.class_name = BATCH_LABELS[session.year_group]
        if commit:
            session.save()
            self.save_m2m()
        return session

    def clean_date(self):
        session_date = self.cleaned_data['date']
        if session_date > timezone.localdate():
            raise ValidationError('যে ক্লাস হয়ে গেছে, শুধু সেই ক্লাসের তথ্য যোগ করুন।')
        if self.teacher is None:
            raise ValidationError('শিক্ষকের রুটিন যাচাই করা যায়নি।')
        if not Routine.objects.filter(
            teacher=self.teacher,
            weekday=session_date.weekday(),
        ).exists():
            if session_date == timezone.localdate():
                raise ValidationError('আজকে আপনার কোনো ক্লাস ছিল না।')
            raise ValidationError('এই তারিখে আপনার কোনো ক্লাস রুটিনে নেই।')
        return session_date


class ClassSessionProgressForm(forms.Form):
    is_completed = forms.BooleanField(required=False)
    problem_description = forms.CharField(
        required=False,
        max_length=1500,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'কোন অংশ বুঝতে সমস্যা হয়েছে? এখানে লিখো।',
        }),
    )


class LearningMaterialForm(forms.ModelForm):
    class Meta:
        model = LearningMaterial
        fields = [
            'title', 'kind', 'year_group', 'subject', 'paper', 'chapter',
            'description', 'file', 'external_url',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'যেমন: ভেক্টর অধ্যায়ের ক্লাস শিট'}),
            'subject': forms.TextInput(attrs={'placeholder': 'যেমন: পদার্থবিজ্ঞান'}),
            'paper': forms.TextInput(attrs={'placeholder': 'যেমন: ১ম পত্র'}),
            'chapter': forms.TextInput(attrs={'placeholder': 'যেমন: ভেক্টর'}),
            'description': forms.TextInput(attrs={'placeholder': 'শিক্ষার্থীদের জন্য সংক্ষিপ্ত নির্দেশনা'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_curriculum_fields(self)

    def save(self, commit=True):
        material = super().save(commit=False)
        material.class_name = BATCH_LABELS.get(material.year_group, '')
        if commit:
            material.save()
            self.save_m2m()
        return material

    def clean(self):
        cleaned_data = super().clean()
        upload = cleaned_data.get('file')
        external_url = cleaned_data.get('external_url')
        if not upload and not external_url:
            raise ValidationError('একটি ফাইল আপলোড করুন অথবা বাহ্যিক লিংক দিন।')
        return cleaned_data


class TeacherForm(forms.Form):
    first_name = forms.CharField(label='শিক্ষকের নাম', max_length=150)
    last_name = forms.CharField(label='পদবি', max_length=150, required=False)
    username = forms.CharField(label='ইউজারনেম', max_length=150)
    email = forms.EmailField(label='ইমেইল', required=False)
    phone = forms.CharField(label='মোবাইল নম্বর', max_length=20, required=False)
    password = forms.CharField(label='প্রাথমিক পাসওয়ার্ড', widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data['username']
        if get_user_model().objects.filter(username=username).exists():
            raise ValidationError('এই ইউজারনেমটি আগে থেকেই ব্যবহৃত হচ্ছে।')
        return username

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password


class TeacherUpdateForm(forms.Form):
    first_name = forms.CharField(label='শিক্ষকের নাম', max_length=150)
    last_name = forms.CharField(label='পদবি', max_length=150, required=False)
    username = forms.CharField(label='ইউজারনেম', max_length=150)
    email = forms.EmailField(label='ইমেইল', required=False)
    phone = forms.CharField(label='মোবাইল নম্বর', max_length=20, required=False)
    password = forms.CharField(
        label='নতুন পাসওয়ার্ড',
        required=False,
        widget=forms.PasswordInput,
        help_text='পাসওয়ার্ড পরিবর্তন না করলে ফাঁকা রাখুন।',
    )

    def __init__(self, *args, teacher, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)
        self.fields['first_name'].initial = teacher.first_name
        self.fields['last_name'].initial = teacher.last_name
        self.fields['username'].initial = teacher.username
        self.fields['email'].initial = teacher.email
        self.fields['phone'].initial = teacher.profile.phone

    def clean_username(self):
        username = self.cleaned_data['username']
        if get_user_model().objects.filter(username=username).exclude(pk=self.teacher.pk).exists():
            raise ValidationError('এই ইউজারনেমটি আগে থেকেই ব্যবহৃত হচ্ছে।')
        return username

    def clean_password(self):
        password = self.cleaned_data['password']
        if password:
            validate_password(password, user=self.teacher)
        return password


class StudentFeeRecordForm(forms.ModelForm):
    month = forms.CharField(
        label='মাস',
        max_length=7,
        widget=forms.TextInput(attrs={'type': 'month'}),
    )

    class Meta:
        model = StudentFeeRecord
        fields = ['student', 'month', 'monthly_fee', 'amount_paid', 'note']
        widgets = {
            'student': forms.Select(attrs={'class': 'fee-form-select'}),
            'monthly_fee': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'যেমন: 3500'}),
            'amount_paid': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'যেমন: 2000'}),
            'note': forms.TextInput(attrs={'placeholder': 'ধরন: জুলাই বেতন, বাকি, এডভান্স ইত্যাদি'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.filter(is_active=True).order_by('name')
        self.fields['student'].empty_label = 'শিক্ষার্থী নির্বাচন করুন'

    def clean_month(self):
        month_value = self.cleaned_data['month'].strip()
        try:
            __import__('datetime').datetime.strptime(month_value, '%Y-%m')
        except ValueError as exc:
            raise ValidationError('মাসের ফরম্যাট ঠিক করুন (উদাহরণ: 2026-09)') from exc
        return month_value

    def clean(self):
        cleaned_data = super().clean()
        monthly_fee = cleaned_data.get('monthly_fee')
        amount_paid = cleaned_data.get('amount_paid')
        if monthly_fee is not None and amount_paid is not None and amount_paid < 0:
            self.add_error('amount_paid', 'পরিশোধের পরিমাণ শূন্যের কম হতে পারবে না।')
        if monthly_fee is not None and monthly_fee < 0:
            self.add_error('monthly_fee', 'মাসিক বেতনের পরিমাণ শূন্যের কম হতে পারবে না।')
        return cleaned_data


class StudentMonthlyFeeForm(forms.Form):
    monthly_fee = forms.DecimalField(
        label='এই মাসে নির্ধারিত বেতন (টাকা)',
        max_digits=12,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'min': '0',
            'step': '0.01',
            'placeholder': 'যেমন: 3500',
            'inputmode': 'decimal',
        }),
    )


class StudentFeedbackForm(forms.ModelForm):
    class Meta:
        model = StudentFeedback
        fields = ['category', 'message']
        widgets = {
            'message': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'কোন বিষয়, অধ্যায় বা ক্লাস নিয়ে সমস্যা হচ্ছে—একটু বিস্তারিত লিখো।',
            }),
        }
