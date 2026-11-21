from django.test import TestCase
from unittest.mock import Mock

from accounts.models import User, Course
from bookings.models import Booking, TutoringRequest, TutoringRequestInterest
from bookings.interfaces import BookingEvent, TutoringRequestEvent
from bookings.subjects import (
    booking_event_manager,
    TutoringRequestEventManager,
)
from bookings.services import (
    cancel_booking,
)

from .models import Notification
from .observers import TutoringRequestInterestNotificationObserver


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


class TutoringRequestInterestNotificationObserverTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "interest-student@example.com",
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            "interest-tutor@example.com",
            role=User.Role.TUTOR,
        )
        self.course = Course.create_course(
            "CS 476",
            "Software Development Project",
        )
        self.tutoring_request = TutoringRequest.objects.create(
            student=self.student,
            course=self.course,
            description="Please help me with Django.",
        )
        self.interest = TutoringRequestInterest.objects.create(
            tutoring_request=self.tutoring_request,
            tutor=self.tutor,
        )

    def test_interest_event_creates_notification_through_factory(self):
        TutoringRequestInterestNotificationObserver().update(
            TutoringRequestEvent.INTEREST_EXPRESSED,
            self.interest,
        )

        notification = Notification.objects.get(
            recipient=self.student,
            sender=self.tutor,
            type=Notification.Type.INTEREST,
        )
        self.assertEqual(notification.title, "New tutor interest")
        self.assertIn(
            f"tutoring request #{self.tutoring_request.pk}",
            notification.message,
        )

    def test_other_event_does_not_create_notification(self):
        TutoringRequestInterestNotificationObserver().update(
            Mock(name="other_event"),
            self.interest,
        )

        self.assertFalse(
            Notification.objects.filter(
                type=Notification.Type.INTEREST,
            ).exists()
        )


class TutoringRequestEventManagerTests(TestCase):
    def test_attach_detach_and_notify(self):
        manager = TutoringRequestEventManager()
        observer = Mock()
        interest = Mock()

        manager.attach(observer)
        manager.attach(observer)
        self.assertEqual(manager._observers, [observer])

        manager.notify(
            TutoringRequestEvent.INTEREST_EXPRESSED,
            interest,
        )
        observer.update.assert_called_once_with(
            TutoringRequestEvent.INTEREST_EXPRESSED,
            interest,
        )

        manager.detach(observer)
        manager.detach(observer)
        self.assertEqual(manager._observers, [])

    def test_observer_failure_does_not_stop_other_observers(self):
        manager = TutoringRequestEventManager()
        failing_observer = Mock()
        succeeding_observer = Mock()
        interest = Mock()
        failing_observer.update.side_effect = RuntimeError("notification failed")

        manager.attach(failing_observer)
        manager.attach(succeeding_observer)

        with self.assertLogs("bookings.subjects", level="ERROR"):
            manager.notify(
                TutoringRequestEvent.INTEREST_EXPRESSED,
                interest,
            )

        succeeding_observer.update.assert_called_once_with(
            TutoringRequestEvent.INTEREST_EXPRESSED,
            interest,
        )
