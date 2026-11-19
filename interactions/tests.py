from django.test import TestCase

from accounts.models import User
from bookings.models import Booking
from bookings.interfaces import BookingEvent
from bookings.subjects import booking_event_manager
from bookings.services import (
    cancel_booking,
)

from .models import Notification


class WebsiteNotificationObserverTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "student@example.com",
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            "tutor@example.com",
            role=User.Role.TUTOR,
        )

    def test_booking_lifecycle_creates_notifications_for_both_users(self):
        booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            student_note="I need help.",
            session_price=10,
            status=Booking.Status.CONFIRMED,
        )

        with self.captureOnCommitCallbacks(execute=True):
            booking_event_manager.notify(
                BookingEvent.BOOKED,
                booking,
            )

        self.assertEqual(
            Notification.objects.filter(
                related_booking=booking,
                type=Notification.Type.CONFIRMATION,
            ).count(),
            2,
        )

        with self.captureOnCommitCallbacks(execute=True):
            cancel_booking(booking, cancelled_by="tutor")

        self.assertEqual(
            Notification.objects.filter(
                related_booking=booking,
                type=Notification.Type.CANCELLATION,
            ).count(),
            2,
        )
