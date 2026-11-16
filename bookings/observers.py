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