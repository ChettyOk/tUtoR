from django.test import TestCase
from unittest.mock import Mock

# Create your tests here.
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Notification
from .ui import notification_url

User = get_user_model()


def make_user(email, role):
    return User.objects.create_user(
        email=email, password="pw12345!", role=role,
    )


class NotificationUITests(TestCase):
    def setUp(self):
        self.student = make_user("s@example.com", "student")
        self.tutor = make_user("t@example.com", "tutor")

    def note(self, user, title="Hello", read=False, ntype=Notification.Type.CONFIRMATION):
        return Notification.objects.create(
            recipient=user, type=ntype, title=title, message="msg",
            status_in_web=read,
        )

    # ---- bell JSON ----
    def test_recent_requires_login(self):
        res = self.client.get(reverse("notifications_recent"))
        self.assertEqual(res.status_code, 302)

    def test_recent_returns_count_and_latest_only_for_me(self):
        self.note(self.student, "mine unread")
        self.note(self.student, "mine read", read=True)
        self.note(self.tutor, "someone else")
        self.client.force_login(self.student)
        data = self.client.get(reverse("notifications_recent")).json()
        self.assertEqual(data["unread_count"], 1)
        self.assertEqual(
            sorted(n["title"] for n in data["notifications"]),
            ["mine read", "mine unread"],
        )

    def test_recent_is_capped_to_six(self):
        for i in range(9):
            self.note(self.student, f"n{i}")
        self.client.force_login(self.student)
        data = self.client.get(reverse("notifications_recent")).json()
        self.assertEqual(len(data["notifications"]), 6)
        self.assertEqual(data["unread_count"], 9)

    # ---- links ----
    def test_link_targets_depend_on_type_and_role(self):
        interest = self.note(self.student, ntype=Notification.Type.INTEREST)
        confirm = self.note(self.student)
        self.assertEqual(notification_url(interest, self.student), reverse("my_requests"))
        self.assertEqual(notification_url(confirm, self.student), reverse("student_home"))
        self.assertEqual(notification_url(confirm, self.tutor), reverse("tutor_home"))

    # ---- page ----
    def test_page_requires_login(self):
        res = self.client.get(reverse("notifications"))
        self.assertEqual(res.status_code, 302)

    def test_page_lists_read_and_unread_but_not_others(self):
        self.note(self.student, "Unread one")
        self.note(self.student, "Read one", read=True)
        self.note(self.tutor, "Not yours")
        self.client.force_login(self.student)
        html = self.client.get(reverse("notifications")).content.decode()
        self.assertIn("Unread one", html)
        self.assertIn("Read one", html)
        self.assertNotIn("Not yours", html)

    def test_unread_filter(self):
        self.note(self.student, "Unread one")
        self.note(self.student, "Read one", read=True)
        self.client.force_login(self.student)
        html = self.client.get(reverse("notifications") + "?filter=unread").content.decode()
        self.assertIn("Unread one", html)
        self.assertNotIn("Read one", html)

    def test_empty_state(self):
        self.client.force_login(self.student)
        html = self.client.get(reverse("notifications")).content.decode()
        self.assertIn("no notifications yet", html)

    def test_pagination(self):
        for i in range(20):
            self.note(self.student, f"n{i}")
        self.client.force_login(self.student)
        first = self.client.get(reverse("notifications"))
        self.assertEqual(len(first.context["items"]), 15)
        second = self.client.get(reverse("notifications") + "?page=2")
        self.assertEqual(len(second.context["items"]), 5)

    def test_message_is_escaped(self):
        Notification.objects.create(
            recipient=self.student, title="<script>x</script>", message="m",
        )
        self.client.force_login(self.student)
        html = self.client.get(reverse("notifications")).content.decode()
        self.assertNotIn("<script>x</script>", html)

    def test_bell_is_in_header_when_signed_in(self):
        self.client.force_login(self.student)
        html = self.client.get(reverse("notifications")).content.decode()
        self.assertIn('id="notif-bell"', html)
        self.client.logout()
        html = self.client.get(reverse("landing")).content.decode()
        self.assertNotIn('id="notif-bell"', html)

    # ---- existing endpoints the buttons rely on ----
    def test_mark_read_and_mark_all_buttons_work_against_backend(self):
        a = self.note(self.student, "a")
        self.note(self.student, "b")
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse("mark_notification_as_read", args=[a.id])).status_code, 200)
        data = self.client.get(reverse("notifications_recent")).json()
        self.assertEqual(data["unread_count"], 1)
        self.client.post(reverse("mark_all_notifications_as_read"))
        data = self.client.get(reverse("notifications_recent")).json()
        self.assertEqual(data["unread_count"], 0)

    def test_cannot_mark_someone_elses_notification(self):
        other = self.note(self.tutor, "private")
        self.client.force_login(self.student)
        res = self.client.post(reverse("mark_notification_as_read", args=[other.id]))
        self.assertEqual(res.status_code, 404)
        other.refresh_from_db()
        self.assertFalse(other.status_in_web)
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
from .factories import NotificationFactory
from .observers import TutoringRequestInterestNotificationObserver


class NotificationFactoryTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "factory-student@example.com",
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            "factory-tutor@example.com",
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

    def test_interest_notification_uses_request_and_tutor_defaults(self):
        notification = NotificationFactory.create(
            "interest",
            interest=self.interest,
        )

        self.assertEqual(notification.type, Notification.Type.INTEREST)
        self.assertEqual(notification.title, "New tutor interest")
        self.assertEqual(notification.recipient, self.student)
        self.assertEqual(notification.sender, self.tutor)
        self.assertIn(
            f"tutoring request #{self.tutoring_request.pk}",
            notification.message,
        )

    def test_interest_notification_accepts_custom_text_and_recipient(self):
        notification = NotificationFactory.create(
            "interest",
            interest=self.interest,
            recipient=self.student,
            sender=self.tutor,
            title="Custom interest title",
            message="Custom interest message",
        )

        self.assertEqual(notification.title, "Custom interest title")
        self.assertEqual(notification.message, "Custom interest message")
        self.assertEqual(notification.recipient, self.student)
        self.assertEqual(notification.sender, self.tutor)

    def test_interest_notification_requires_interest(self):
        with self.assertRaisesRegex(
            ValueError,
            "An interest is required",
        ):
            NotificationFactory.create("interest")

    def test_booking_notification_types_use_default_values(self):
        booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            student_note="I need help.",
            session_price=10,
            status=Booking.Status.CONFIRMED,
        )

        cases = (
            ("confirmation", Notification.Type.CONFIRMATION, "Session confirmed"),
            ("cancellation", Notification.Type.CANCELLATION, "Session cancelled"),
            ("reminder", Notification.Type.REMINDER, "Session reminder"),
            ("request", Notification.Type.REQUESTED, "Session requested"),
        )

        for notification_type, expected_type, expected_title in cases:
            with self.subTest(notification_type=notification_type):
                notification = NotificationFactory.create(
                    notification_type,
                    recipient=self.student,
                    sender=self.tutor,
                    booking=booking,
                )

                self.assertEqual(notification.type, expected_type)
                self.assertEqual(notification.title, expected_title)
                self.assertEqual(notification.recipient, self.student)
                self.assertEqual(notification.sender, self.tutor)
                self.assertEqual(notification.related_booking, booking)

    def test_unknown_notification_type_raises_value_error(self):
        with self.assertRaisesRegex(
            ValueError,
            "Unknown notification type",
        ):
            NotificationFactory.create("unknown")


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
