from django.conf import settings
from django.db import models
from django.utils import timezone

from students.models import Student


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'present', 'উপস্থিত'
        ABSENT = 'absent', 'অনুপস্থিত'
        LATE = 'late', 'দেরিতে এসেছে'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField('তারিখ', default=timezone.localdate)
    status = models.CharField('অবস্থা', max_length=10, choices=Status.choices, default=Status.PRESENT)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marked_attendance',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['student__name']
        constraints = [
            models.UniqueConstraint(fields=['student', 'date'], name='unique_student_attendance_per_day'),
        ]
        verbose_name = 'উপস্থিতি'
        verbose_name_plural = 'উপস্থিতি'

    def __str__(self):
        return f'{self.student} · {self.date} · {self.get_status_display()}'


class AttendanceWhatsAppNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'অপেক্ষমাণ'
        SENDING = 'sending', 'পাঠানো হচ্ছে'
        SENT = 'sent', 'Meta গ্রহণ করেছে'
        FAILED = 'failed', 'ব্যর্থ'
        CANCELLED = 'cancelled', 'বাতিল'

    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name='whatsapp_notifications',
    )
    attendance_status = models.CharField(max_length=10, choices=Attendance.Status.choices)
    state = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    delivery_status = models.CharField(max_length=20, default='pending')
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['attendance', 'attendance_status'],
                name='unique_attendance_whatsapp_status',
            ),
        ]

    def __str__(self):
        return f'{self.attendance} · WhatsApp {self.attendance_status}/{self.state}'


class AttendanceSMSNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'অপেক্ষমাণ'
        SENDING = 'sending', 'পাঠানো হচ্ছে'
        SENT = 'sent', 'পাঠানো হয়েছে'
        FAILED = 'failed', 'ব্যর্থ'
        CANCELLED = 'cancelled', 'বাতিল'

    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name='sms_notifications',
    )
    attendance_status = models.CharField(max_length=10, choices=Attendance.Status.choices)
    recipient_phone = models.CharField(max_length=32, blank=True)
    state = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['attendance', 'attendance_status'],
                name='unique_attendance_sms_status',
            ),
        ]

    def __str__(self):
        return f'{self.attendance} · SMS {self.attendance_status}/{self.state}'


class AttendanceSMSBatch(models.Model):
    attendance_date = models.DateField('উপস্থিতির তারিখ')
    accepted_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    sms_enabled = models.BooleanField(default=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_sms_batches',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'SMS save report'
        verbose_name_plural = 'SMS save reports'


class AttendanceSMSSettings(models.Model):
    enabled = models.BooleanField('SMS system চালু', default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_attendance_sms_settings',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SMS system setting'
        verbose_name_plural = 'SMS system settings'

    def __str__(self):
        return 'SMS চালু' if self.enabled else 'SMS বন্ধ'
