from django.test import TestCase

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