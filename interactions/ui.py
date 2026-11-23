"""Helpers for the notification bell and the "all notifications" page."""
from django.urls import reverse
from django.utils.timesince import timesince

from .models import Notification


def notification_url(notification, user):
    """Where a click on this notification should take the user."""
    if notification.type == Notification.Type.INTEREST:
        return reverse("my_requests")
    if getattr(user, "role", "") == "tutor":
        return reverse("tutor_home")
    return reverse("student_home")


def time_ago(notification):
    """'5 minutes ago' style label (uses the first unit only)."""
    first = timesince(notification.created_at).split(",")[0].replace("\xa0", " ")
    if first.startswith("0 "):
        return "Just now"
    return f"{first} ago"


def notification_for_ui(notification, user):
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "is_read": notification.status_in_web,
        "url": notification_url(notification, user),
        "time_ago": time_ago(notification),
    }