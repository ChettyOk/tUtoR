from bookings.interfaces import BookingEvent, BookingObserver
from interactions.models import Notification, NotificationSettings


class WebsiteNotificationObserver(BookingObserver):
    """Creates in-website notifications independently of mail delivery."""

    _event_types = {
        BookingEvent.BOOKED: Notification.NotificationType.CONFIRMATION,
        BookingEvent.CANCELLED: Notification.NotificationType.CANCELLATION,
        BookingEvent.REMINDER: Notification.NotificationType.REMINDER,
    }

    def update(self, event: BookingEvent, booking) -> None:
        notification_type = self._event_types.get(event)
        if notification_type is None:
            return

        sender = self._get_sender(event, booking)
        title, message = self._get_content(notification_type, booking)
        recipients = (booking.student, booking.tutor)

        for recipient in recipients:
            settings, _ = NotificationSettings.objects.get_or_create(
                user=recipient
            )
            if settings.website_enabled:
                Notification.objects.create(
                    recipient=recipient,
                    sender=sender,
                    related_booking=booking,
                    type=notification_type,
                    title=title,
                    message=message,
                )

    @staticmethod
    def _get_sender(event: BookingEvent, booking):
        if event == BookingEvent.BOOKED:
            return booking.student
        if event == BookingEvent.CANCELLED:
            return (
                booking.student
                if booking.status == booking.Status.CANCELLED_STUDENT
                else booking.tutor
            )
        return None

    @staticmethod
    def _get_content(notification_type, booking):
        if notification_type == Notification.NotificationType.CONFIRMATION:
            return (
                "Booking confirmed",
                f"Booking #{booking.id} has been confirmed.",
            )
        if notification_type == Notification.NotificationType.CANCELLATION:
            return (
                "Booking cancelled",
                f"Booking #{booking.id} has been cancelled.",
            )
        return (
            "Booking reminder",
            f"Booking #{booking.id} starts in two hours.",
        )
