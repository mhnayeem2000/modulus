from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from portal.year_groups import BATCH_LABELS
from .models import Student


class StudentForm(forms.ModelForm):
    username = forms.CharField(
        label='শিক্ষার্থীর ইউজারনেম',
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'লগইন অ্যাকাউন্টের জন্য'}),
    )
    password = forms.CharField(
        label='প্রাথমিক পাসওয়ার্ড',
        required=False,
        widget=forms.PasswordInput(attrs={'placeholder': 'শিক্ষার্থীকে জানিয়ে দিন'}),
    )

    class Meta:
        model = Student
        fields = ['name', 'student_id', 'year_group', 'phone', 'guardian_phone']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'যেমন: আয়েশা রহমান'}),
            'student_id': forms.TextInput(attrs={'placeholder': 'যেমন: ST-1024'}),
            'phone': forms.TextInput(attrs={'placeholder': '01XXXXXXXXX'}),
            'guardian_phone': forms.TextInput(attrs={'placeholder': '+8801XXXXXXXXX'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username', '').strip()
        password = cleaned_data.get('password', '')
        if bool(username) != bool(password):
            message = 'লগইন অ্যাকাউন্ট তৈরি করতে ইউজারনেম ও পাসওয়ার্ড—দুটিই দিন।'
            self.add_error('username', message)
            self.add_error('password', message)
        if username and get_user_model().objects.filter(username=username).exists():
            self.add_error('username', 'এই ইউজারনেমটি আগে থেকেই ব্যবহৃত হচ্ছে।')
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error('password', error)
        return cleaned_data

    def save(self, commit=True):
        student = super().save(commit=False)
        student.class_name = BATCH_LABELS[student.year_group]
        if commit:
            student.save()
            self.save_m2m()
        return student


class StudentUpdateForm(forms.ModelForm):
    username = forms.CharField(
        label='শিক্ষার্থীর ইউজারনেম',
        required=False,
    )
    password = forms.CharField(
        label='নতুন পাসওয়ার্ড',
        required=False,
        widget=forms.PasswordInput,
        help_text='পাসওয়ার্ড পরিবর্তন না করলে ফাঁকা রাখুন।',
    )

    class Meta:
        model = Student
        fields = ['name', 'student_id', 'year_group', 'phone', 'guardian_phone']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'যেমন: আয়েশা রহমান'}),
            'student_id': forms.TextInput(attrs={'placeholder': 'যেমন: ST-1024'}),
            'phone': forms.TextInput(attrs={'placeholder': '01XXXXXXXXX'}),
            'guardian_phone': forms.TextInput(attrs={'placeholder': '+8801XXXXXXXXX'}),
        }

    def __init__(self, *args, **kwargs):
        self.student = kwargs['instance']
        super().__init__(*args, **kwargs)
        if self.student.user_id:
            self.fields['username'].initial = self.student.user.username
        else:
            self.fields.pop('username')
            self.fields.pop('password')

    def save(self, commit=True):
        student = super().save(commit=False)
        student.class_name = BATCH_LABELS[student.year_group]
        if commit:
            student.save()
            self.save_m2m()
        return student

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username and get_user_model().objects.filter(username=username).exclude(
            pk=self.student.user_id,
        ).exists():
            raise ValidationError('এই ইউজারনেমটি আগে থেকেই ব্যবহৃত হচ্ছে।')
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password', '')
        if password and self.student.user_id:
            try:
                validate_password(password, user=self.student.user)
            except ValidationError as error:
                self.add_error('password', error)
        return password


class StudentAccountForm(forms.Form):
    username = forms.CharField(
        label='শিক্ষার্থীর ইউজারনেম',
        widget=forms.TextInput(attrs={'placeholder': 'শিক্ষার্থী এই নাম দিয়ে লগইন করবে'}),
    )
    password = forms.CharField(
        label='প্রাথমিক পাসওয়ার্ড',
        widget=forms.PasswordInput(attrs={'placeholder': 'শিক্ষার্থীকে নিরাপদে জানিয়ে দিন'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if get_user_model().objects.filter(username=username).exists():
            raise ValidationError('এই ইউজারনেমটি আগে থেকেই ব্যবহৃত হচ্ছে।')
        return username

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password
