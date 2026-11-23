from django.urls import path

from . import views


urlpatterns = [
    path(
        "notifications/unread/",
        views.get_unread_notifications,
        name="unread_notifications",
    ),
    path(
        "notifications/unread/count/",
        views.get_unread_notification_count,
        name="unread_notification_count",
    ),
    path(
        "notifications/read-all/",
        views.mark_all_notifications_as_read,
        name="mark_all_notifications_as_read",
    ),
    path(
        "notifications/<int:notification_id>/read/",
        views.mark_notification_as_read,
        name="mark_notification_as_read",
    ),
    path(
        "notifications/<int:notification_id>/delete/",
        views.delete_notification,
        name="delete_notification",
    ),
]
