from django.urls import path

from . import ui_views

urlpatterns = [
    path("notifications/", ui_views.notifications_page, name="notifications"),
    path("notifications/recent/", ui_views.notifications_recent, name="notifications_recent"),
]