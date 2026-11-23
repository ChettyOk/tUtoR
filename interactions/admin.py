from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "recipient",
        "sender",
        "type",
        "status_in_web",
        "created_at",
    )
    list_filter = ("type", "status_in_web", "created_at")
    search_fields = (
        "title",
        "message",
        "recipient__email",
        "sender__email",
    )
    readonly_fields = ("created_at",)
