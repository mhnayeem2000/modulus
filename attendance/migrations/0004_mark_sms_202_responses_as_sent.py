from django.db import migrations
from django.db.models import F


def mark_accepted_sms_as_sent(apps, schema_editor):
    notification = apps.get_model('attendance', 'AttendanceSMSNotification')
    notification.objects.filter(
        state='failed',
        last_error__contains='response code 202',
    ).update(
        state='sent',
        sent_at=F('updated_at'),
        last_error='',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('attendance', '0003_attendancesmsnotification'),
    ]

    operations = [
        migrations.RunPython(mark_accepted_sms_as_sent, migrations.RunPython.noop),
    ]
