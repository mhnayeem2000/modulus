from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('attendance', '0002_attendancewhatsappnotification'),
    ]

    operations = [
        migrations.CreateModel(
            name='AttendanceSMSNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attendance_status', models.CharField(
                    choices=[('present', 'উপস্থিত'), ('absent', 'অনুপস্থিত'), ('late', 'দেরিতে এসেছে')],
                    max_length=10,
                )),
                ('state', models.CharField(
                    choices=[
                        ('pending', 'অপেক্ষমাণ'),
                        ('sending', 'পাঠানো হচ্ছে'),
                        ('sent', 'পাঠানো হয়েছে'),
                        ('failed', 'ব্যর্থ'),
                        ('cancelled', 'বাতিল'),
                    ],
                    default='pending',
                    max_length=10,
                )),
                ('provider_message_id', models.CharField(blank=True, max_length=128)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('attendance', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sms_notifications',
                    to='attendance.attendance',
                )),
            ],
            options={
                'ordering': ['created_at'],
                'constraints': [
                    models.UniqueConstraint(
                        fields=('attendance', 'attendance_status'),
                        name='unique_attendance_sms_status',
                    ),
                ],
            },
        ),
    ]
