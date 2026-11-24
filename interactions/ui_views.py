from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Notification
from .ui import notification_for_ui

BELL_LIMIT = 6
PAGE_SIZE = 15


@login_required
@require_GET
def notifications_recent(request):
    """Unread count plus the latest notifications for the bell dropdown."""
    unread_count = Notification.get_unread_notifications(request.user).count()
    latest = Notification.objects.filter(recipient=request.user)[:BELL_LIMIT]
    return JsonResponse({
        "unread_count": unread_count,
        "notifications": [notification_for_ui(n, request.user) for n in latest],
    })


@login_required
@require_GET
def notifications_page(request):
    """Full list of the user's notifications, newest first."""
    only_unread = request.GET.get("filter") == "unread"
    queryset = Notification.objects.filter(recipient=request.user)
    if only_unread:
        queryset = queryset.filter(status_in_web=False)

    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    items = [notification_for_ui(n, request.user) for n in page.object_list]
    unread_count = Notification.get_unread_notifications(request.user).count()
    return render(request, "interactions/notifications_page.html", {
        "site_name": "tUtoR",
        "campus": "University of Regina",
        "page": page,
        "items": items,
        "only_unread": only_unread,
        "unread_count": unread_count,
    })