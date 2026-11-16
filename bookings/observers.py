from django.conf import settings
from django.core.mail import send_mail

from bookings.interfaces import BookingEvent, BookingObserver


class ConfirmationMailObserver(BookingObserver):
    """Sends booking confirmations to both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event == BookingEvent.BOOKED:
            self.sendConfirmationMail(booking)

    def sendConfirmationMail(self, booking) -> None:
        recipient_list = [booking.student.email, booking.tutor.email]
        send_mail(
            subject=f"Booking confirmation for booking #{booking.id}",
            message=(
                "Your tutoring session has been booked successfully.\n\n"
                f"Booking: #{booking.id}\n"
                f"Student: {booking.student.email}\n"
                f"Tutor: {booking.tutor.email}\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
            fail_silently=False,
        ) 


class CancellationMailObserver(BookingObserver):
    """Sends cancellation information to both participants."""

    def update(self, event: BookingEvent, booking) -> None:
        if event == BookingEvent.CANCELLED:
            self.sendCancellationMail(booking)

    def sendCancellationMail(self, booking) -> None:
        recipient_list = [booking.student.email, booking.tutor.email]
        send_mail(
            subject=f"Booking cancellation for booking #{booking.id}",
            message=(
                "Your tutoring session has been cancelled.\n\n"
                f"Booking: #{booking.id}\n"
                f"Student: {booking.student.email}\n"
                f"Tutor: {booking.tutor.email}\n"
                f"Reason: {booking.cancellation_reason or 'Not provided'}\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
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
        send_mail(
            subject=f"Reminder: booking #{booking.id} starts in 2 hours",
            message=(
                "Your tutoring session starts in 2 hours.\n\n"
                f"Booking: #{booking.id}\n"
                f"Student: {booking.student.email}\n"
                f"Tutor: {booking.tutor.email}\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipient_list,
            fail_silently=False,
        )