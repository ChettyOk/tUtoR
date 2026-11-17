from django.test import TestCase

from accounts.models import User
from bookings.services import (
    cancel_booking,
    confirm_booking,
    create_session_request,
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
        with self.captureOnCommitCallbacks(execute=True):
            booking = create_session_request(
                self.student,
                self.tutor,
                student_note="I need help.",
                session_price=10,
            )

        self.assertCountEqual(
            Notification.objects.filter(related_booking=booking).values_list(
                "recipient_id",
                "type",
            ),
            [
                (self.student.id, "requested"),
                (self.tutor.id, "requested"),
            ],
        )

        with self.captureOnCommitCallbacks(execute=True):
            confirm_booking(booking)

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
