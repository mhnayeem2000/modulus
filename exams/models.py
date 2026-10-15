from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from portal.year_groups import BATCH_CHOICES
from students.models import Student


class Exam(models.Model):
    title = models.CharField('পরীক্ষার নাম', max_length=120)
    exam_date = models.DateField('পরীক্ষার তারিখ')
    class_name = models.CharField('শ্রেণি/ব্যাচ', max_length=60)
    year_group = models.CharField('বর্ষ', max_length=10, choices=BATCH_CHOICES, default='first')
    subject = models.CharField('বিষয়', max_length=100, blank=True)
    paper = models.CharField('পত্র', max_length=100)
    chapter = models.CharField('অধ্যায়', max_length=120)
    topic = models.CharField('টপিক', max_length=120)
    total_marks = models.PositiveIntegerField('পূর্ণমান', validators=[MinValueValidator(1)])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='coaching_exams',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-exam_date', '-created_at']
        verbose_name = 'পরীক্ষা'
        verbose_name_plural = 'পরীক্ষা'

    def __str__(self):
        return f'{self.title} · {self.class_name}'


class ExamResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='exam_results')
    marks = models.DecimalField('প্রাপ্ত নম্বর', max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recorded_exam_results',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'student__name']
        constraints = [
            models.UniqueConstraint(fields=['exam', 'student'], name='unique_result_per_exam_student'),
        ]
        verbose_name = 'পরীক্ষার ফলাফল'
        verbose_name_plural = 'পরীক্ষার ফলাফল'

    def __str__(self):
        return f'{self.student} · {self.exam}: {self.marks}/{self.exam.total_marks}'


class ExamResultSMSNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'অপেক্ষমাণ'
        SENDING = 'sending', 'পাঠানো হচ্ছে'
        SENT = 'sent', 'BulkSMSBD গ্রহণ করেছে'
        FAILED = 'failed', 'ব্যর্থ'
        CANCELLED = 'cancelled', 'SMS System বন্ধ থাকায় বাতিল'

    result = models.ForeignKey(
        ExamResult,
        on_delete=models.CASCADE,
        related_name='sms_notifications',
    )
    marks = models.DecimalField(max_digits=7, decimal_places=2)
    rank = models.PositiveIntegerField(null=True, blank=True)
    rank_out_of = models.PositiveIntegerField(null=True, blank=True)
    recipient_phone = models.CharField(max_length=32, blank=True)
    state = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.result} · Marks SMS {self.marks}/{self.state}'
