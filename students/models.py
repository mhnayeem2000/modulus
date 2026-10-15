from django.conf import settings
from django.db import models

from portal.year_groups import BATCH_CHOICES


class Student(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_record',
        verbose_name='লগইন অ্যাকাউন্ট',
    )
    name = models.CharField('শিক্ষার্থীর নাম', max_length=120)
    student_id = models.CharField('আইডি', max_length=30, unique=True)
    class_name = models.CharField('শ্রেণি/ব্যাচ', max_length=60)
    year_group = models.CharField('বর্ষ', max_length=10, choices=BATCH_CHOICES, default='first')
    phone = models.CharField('মোবাইল নম্বর', max_length=20, blank=True)
    guardian_phone = models.CharField('অভিভাবকের WhatsApp/SMS নম্বর', max_length=32, blank=True)
    is_active = models.BooleanField('সক্রিয়', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'শিক্ষার্থী'
        verbose_name_plural = 'শিক্ষার্থী'

    def __str__(self):
        return f'{self.name} ({self.student_id})'
