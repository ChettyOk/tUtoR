from django.db import models
from django.conf import settings
from django.core.mail import send_mail

class Notification(models.Model):
    class Type(models.TextChoices):
        REQUESTED = "requested", "Requested"
        CONFIRMATION = "confirmation", "Confirmation"
        CANCELLATION = "cancellation", "Cancellation"
        REMINDER = "reminder", "Reminder"
        RATING = "rating", "Rating"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.REQUESTED,
    )
    title = models.CharField(max_length=255, default="")
    message = models.TextField(default="")
    related_booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )
    status_in_web = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "status_in_web", "created_at"]),
        ]

    @classmethod
    def create_notification(
        cls,
        recipient,
        notification_type,
        title,
        message,
        related_booking=None,
        sender=None,
    ):
        return cls.objects.create(
            recipient=recipient,
            type=notification_type,
            title=title,
            message=message,
            related_booking=related_booking,
            sender=sender,
        )

    def get_contact_information(self):
        return {
            "id": self.recipient_id,
            "email": self.recipient.email,
            "first_name": self.recipient.first_name,
            "last_name": self.recipient.last_name,
        }

    @classmethod
    def get_unread_notifications(cls, recipient):
        return cls.objects.filter(
            recipient=recipient,
            status_in_web=False,
        )

    def trigger_notification(self):
        return self.save()

    def trigger_email(self, from_email=None):
        send_mail(
            subject=self.title,
            message=self.message,
            from_email=from_email,
            recipient_list=[self.recipient.email],
            fail_silently=False,
        )

    def mark_as_read(self):
        if not self.status_in_web:
            self.status_in_web = True
            self.save(update_fields=["status_in_web"])
        return self

    @classmethod
    def rating_notification(
        cls,
        recipient,
        message,
        related_booking=None,
        sender=None,
    ):
        return cls.create_notification(
            recipient=recipient,
            notification_type=cls.Type.RATING,
            title="New rating",
            message=message,
            related_booking=related_booking,
            sender=sender,
        )

    def __str__(self):
        return f"Notification for {self.recipient_id}: {self.title}"

# ==========================================
# VON MIR (DJANGO DEFAULTS)
# ==========================================

# ==========================================
# VON EUCH (AUS DEM PDF)
# ==========================================


# Ratings
#     ID
#     reviewer ID
#     reviewer Role
#     reviewed Person ID
#     rating
#     created At
#     (comment)
#     status (reviewed, not reviewed)
#     create Review()
#     check for Booking()
#     update Tutor Rating()
#     update Student Rating()
