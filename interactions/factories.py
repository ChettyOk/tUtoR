from .models import Notification


class NotificationFactory:
    """Creates the supported notification types for web and email observers."""

    @staticmethod
    def create(notification_type, recipient=None, booking=None, sender=None,
               title=None, message=None):
        if notification_type == "confirmation":
            notification_type = Notification.Type.CONFIRMATION
            title = title or "Session confirmed"
            message = message or f"Session #{booking.id} was confirmed."
        elif notification_type == "cancellation":
            notification_type = Notification.Type.CANCELLATION
            title = title or "Session cancelled"
            message = message or f"Session #{booking.id} was cancelled."
        elif notification_type == "reminder":
            notification_type = Notification.Type.REMINDER
            title = title or "Session reminder"
            message = message or f"Session #{booking.id} starts in 2 hours."
        elif notification_type == "request":
            notification_type = Notification.Type.REQUESTED
            title = title or "Session requested"
            message = message or f"You requested session #{booking.id}."
        else:
            raise ValueError(f"Unknown notification type: {notification_type}")

        notification = Notification(
            type=notification_type,
            title=title,
            message=message,
        )
        if recipient is not None and hasattr(recipient, "_meta"):
            notification.recipient = recipient
        if sender is not None and hasattr(sender, "_meta"):
            notification.sender = sender
        if booking is not None and hasattr(booking, "_meta"):
            notification.related_booking = booking

        return notification
