from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from bookings.interfaces import BookingEvent, BookingObserver
from interactions.factories import NotificationFactory


class ConfirmationMailObserver(BookingObserver):
    """Sends booking confirmations to both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event == BookingEvent.BOOKED:
            self.sendConfirmationMail(booking)

    def sendConfirmationMail(self, booking) -> None:
        recipient_list = [booking.student.email, booking.tutor.email]
        context = {"booking": booking}
        notification = NotificationFactory.create(
            "confirmation",
            booking=booking,
            title=f"Booking confirmation for booking #{booking.id}",
            message=render_to_string("emails/confirmation.txt", context).strip(),
        )
        send_mail(
            subject=notification.title,
            message=notification.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
            html_message=render_to_string("emails/confirmation.html", context),
            fail_silently=False,
        ) 


class CancellationMailObserver(BookingObserver):
    """Sends cancellation information to both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event == BookingEvent.CANCELLED:
            self.sendCancellationMail(booking)

    def sendCancellationMail(self, booking) -> None:
        recipient_list = [booking.student.email, booking.tutor.email]
        context = {"booking": booking}
        notification = NotificationFactory.create(
            "cancellation",
            booking=booking,
            title=f"Booking cancellation for booking #{booking.id}",
            message=render_to_string("emails/cancellation.txt", context).strip(),
        )
        send_mail(
            subject=notification.title,
            message=notification.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
            html_message=render_to_string("emails/cancellation.html", context),
            fail_silently=False,
        )


class ReminderMailObserver(BookingObserver):
    """Sends two-hour reminders to both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event != BookingEvent.REMINDER:
            return

        if booking.status in {
            "cancelled_by_student",
            "cancelled_by_tutor",
        }:
            return

        self.sendReminderMail(booking)

    def sendReminderMail(self, booking) -> None:
        recipient_list = [booking.student.email, booking.tutor.email]
        context = {"booking": booking}
        notification = NotificationFactory.create(
            "reminder",
            booking=booking,
            title=f"Reminder: booking #{booking.id} starts in 2 hours",
            message=render_to_string("emails/reminder.txt", context).strip(),
        )
        send_mail(
            subject=notification.title,
            message=notification.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
            html_message=render_to_string("emails/reminder.html", context),
            fail_silently=False,
        )