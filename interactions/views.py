from django.shortcuts import render

# Create your views here.

# ==========================================
# VON MIR (DJANGO DEFAULTS)
# ==========================================

# ==========================================
# VON EUCH (AUS DEM PDF - CONTROLLER)
# ==========================================

# Rating Controller
#     create Student Rating()
#     create Tutor Rating()

# Notification Controller
#     get Unread Notifications()
#     mark As read()
#     mark All As read()
#     get Unread Count()
#     delete Notifications()
#     Send Confirmation Mail()
#     Send Cancellation Mail()
#     Send Reminder Mail()
#     Set Notification Settings()
#     update Notification Settings()


from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


def serialize_notification(notification):
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "related_booking_id": notification.related_booking_id,
        "created_at": notification.created_at.isoformat(),
        "sender_id": notification.sender_id,
        "status_in_web": notification.status_in_web,
    }


@login_required
@require_GET
def get_unread_notifications(request):
    notifications = Notification.get_unread_notifications(
        request.user,
    )
    return JsonResponse({
        "notifications": [
            serialize_notification(notification)
            for notification in notifications
        ],
    })


@login_required
@require_POST
def mark_notification_as_read(request, notification_id):
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient=request.user,
    )
    notification.mark_as_read()
    return JsonResponse({
        "notification": serialize_notification(notification),
    })


@login_required
@require_POST
def mark_all_notifications_as_read(request):
    updated_count = Notification.get_unread_notifications(
        request.user,
    ).update(status_in_web=True)
    return JsonResponse({"updated_count": updated_count})


@login_required
@require_GET
def get_unread_notification_count(request):
    count = Notification.get_unread_notifications(request.user).count()
    return JsonResponse({"count": count})


@login_required
@require_POST
def delete_notification(request, notification_id):
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient=request.user,
    )
    notification.delete()
    return JsonResponse({"deleted": True, "notification_id": notification_id})
