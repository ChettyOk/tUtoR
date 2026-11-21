from .models import Notification


class NotificationFactory:
    """Creates the supported notification types for web and email observers."""

    @staticmethod
    def create(notification_type, recipient=None, booking=None, sender=None,
               title=None, message=None, interest=None):
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
        elif notification_type == "interest":
            if interest is None:
                raise ValueError("An interest is required for interest notifications.")

            notification_type = Notification.Type.INTEREST
            tutor = interest.tutor
            tutoring_request = interest.tutoring_request
            recipient = recipient or tutoring_request.student
            sender = sender or tutor
            title = title or "New tutor interest"
            message = message or (
                f"{tutor.get_full_name() or tutor.email} is interested "
                f"in your tutoring request #{tutoring_request.pk}."
            )
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
