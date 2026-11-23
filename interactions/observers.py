from bookings.interfaces import (
    BookingEvent,
    BookingObserver,
    TutoringRequestEvent,
    TutoringRequestObserver,
)

from .models import Notification
from .factories import NotificationFactory


class WebsiteNotificationObserver(BookingObserver):
    """Persists booking lifecycle messages for both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event == BookingEvent.REQUESTED:
            notifications = (
                NotificationFactory.create("request", booking.student, booking),
                NotificationFactory.create(
                    "request",
                    booking.tutor,
                    booking,
                    title="New session request",
                    message=f"A session request was created for you (#{booking.id}).",
                ),
            )
        elif event == BookingEvent.BOOKED:
            notifications = (
                NotificationFactory.create("confirmation", booking.student, booking),
                NotificationFactory.create("confirmation", booking.tutor, booking),
            )
        elif event == BookingEvent.CANCELLED:
            notifications = (
                NotificationFactory.create("cancellation", booking.student, booking),
                NotificationFactory.create("cancellation", booking.tutor, booking),
            )
        else:
            return

        Notification.objects.bulk_create(notifications)


class TutoringRequestInterestNotificationObserver(TutoringRequestObserver):
    """Persists a notification when a tutor expresses request interest."""

    def update(self, event: TutoringRequestEvent, interest) -> None:
        if event != TutoringRequestEvent.INTEREST_EXPRESSED:
            return

        notification = NotificationFactory.create(
            "interest",
            interest=interest,
        )
        Notification.objects.bulk_create([notification])
