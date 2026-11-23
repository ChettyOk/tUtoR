from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from bookings.interfaces import BookingEvent
from bookings.models import Booking
from bookings.subjects import booking_event_manager


class Command(BaseCommand):
    help = 'Send reminders for confirmed sessions starting within two hours.'

    def handle(self, *args, **options):
        now = timezone.now()
        deadline = now + timedelta(hours=2)
        bookings = Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            reminder_sent=False,
        ).filter(
            Q(start_time__gte=now, start_time__lte=deadline)
            | Q(
                start_time__isnull=True,
                time_slot__start_time__gte=now,
                time_slot__start_time__lte=deadline,
            )
        ).select_related('student', 'tutor', 'time_slot')

        sent_count = 0
        for booking in bookings:
            with transaction.atomic():
                locked_booking = (
                    Booking.objects.select_for_update()
                    .select_related('student', 'tutor', 'time_slot')
                    .get(pk=booking.pk)
                )
                if (
                    locked_booking.status != Booking.Status.CONFIRMED
                    or locked_booking.reminder_sent
                ):
                    continue

                locked_booking.reminder_sent = True
                locked_booking.save(update_fields=['reminder_sent'])
                transaction.on_commit(
                    lambda booking=locked_booking: booking_event_manager.notify(
                        BookingEvent.REMINDER, booking
                    )
                )
                sent_count += 1

        self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} reminder(s).'))
