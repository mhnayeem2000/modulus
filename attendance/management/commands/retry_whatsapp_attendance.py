from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from attendance.models import AttendanceWhatsAppNotification
from attendance.whatsapp import send_queued_notifications


class Command(BaseCommand):
    help = 'Retry failed and pending attendance WhatsApp notifications.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        limit = options['limit']
        if limit < 1:
            self.stderr.write(self.style.ERROR('--limit must be greater than zero.'))
            return

        stale_before = timezone.now() - timedelta(minutes=10)
        notifications = AttendanceWhatsAppNotification.objects.filter(
            Q(state__in=[
                AttendanceWhatsAppNotification.Status.PENDING,
                AttendanceWhatsAppNotification.Status.FAILED,
            ])
            | Q(
                state=AttendanceWhatsAppNotification.Status.SENDING,
                updated_at__lt=stale_before,
            ),
        ).order_by('created_at')[:limit]
        sent, failed = send_queued_notifications(list(notifications.values_list('pk', flat=True)))
        self.stdout.write(f'WhatsApp retries complete: {sent} accepted, {failed} failed.')
