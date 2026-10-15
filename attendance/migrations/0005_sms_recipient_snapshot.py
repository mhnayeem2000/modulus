from django.db import migrations, models


def store_existing_recipient_numbers(apps, schema_editor):
    notification = apps.get_model('attendance', 'AttendanceSMSNotification')
    for item in notification.objects.select_related('attendance__student').iterator():
        item.recipient_phone = item.attendance.student.guardian_phone or ''
        item.save(update_fields=['recipient_phone'])


class Migration(migrations.Migration):
    dependencies = [
        ('attendance', '0004_mark_sms_202_responses_as_sent'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendancesmsnotification',
            name='recipient_phone',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.RunPython(store_existing_recipient_numbers, migrations.RunPython.noop),
    ]
