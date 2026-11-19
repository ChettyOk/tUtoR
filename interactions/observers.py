from bookings.interfaces import (
    BookingEvent,
    BookingObserver,
    TutoringRequestEvent,
    TutoringRequestObserver,
)

from .models import Notification


class WebsiteNotificationObserver(BookingObserver):
    """Persists booking lifecycle messages for both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        messages = {
            BookingEvent.REQUESTED: (
                (booking.student, "Session requested", f"You requested session #{booking.id}."),
                (booking.tutor, "New session request", f"A session request was created for you (#{booking.id})."),
            ),
            BookingEvent.BOOKED: (
                (booking.student, "Session confirmed", f"Session #{booking.id} was confirmed."),
                (booking.tutor, "Session confirmed", f"Session #{booking.id} was confirmed."),
            ),
            BookingEvent.CANCELLED: (
                (booking.student, "Session cancelled", f"Session #{booking.id} was cancelled."),
                (booking.tutor, "Session cancelled", f"Session #{booking.id} was cancelled."),
            ),
        }.get(event)

        if messages is None:
            return

        notification_type = {
            BookingEvent.REQUESTED: Notification.Type.REQUESTED,
            BookingEvent.BOOKED: Notification.Type.CONFIRMATION,
            BookingEvent.CANCELLED: Notification.Type.CANCELLATION,
        }[event]
        Notification.objects.bulk_create(
            Notification(
                recipient=recipient,
                related_booking=booking,
                type=notification_type,
                title=title,
                message=message,
            )
            for recipient, title, message in messages
        )


class TutoringRequestInterestNotificationObserver(TutoringRequestObserver):
    """Persists a notification when a tutor expresses request interest."""

    def update(self, event: TutoringRequestEvent, interest) -> None:
        if event != TutoringRequestEvent.INTEREST_EXPRESSED:
            return

        tutor = interest.tutor
        tutoring_request = interest.tutoring_request
        Notification.create_notification(
            recipient=tutoring_request.student,
            sender=tutor,
            notification_type=Notification.Type.INTEREST,
            title="New tutor interest",
            message=(
                f"{tutor.get_full_name() or tutor.email} is interested "
                f"in your tutoring request #{tutoring_request.pk}."
            ),
        )
