from django.db import models
from django.conf import settings

# Create your models here.

# ==========================================
# VON MIR (DJANGO DEFAULTS)
# ==========================================

# ==========================================
# VON EUCH (AUS DEM PDF)
# ==========================================

class Notification(models.Model):
    class NotificationType(models.TextChoices):
        CONFIRMATION = "confirmation", "Confirmation"
        CANCELLATION = "cancellation", "Cancellation"
        REMINDER = "reminder", "Reminder"
        RATING = "rating", "Rating"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_notifications",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )
    related_booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    status_in_web = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} notification for {self.recipient}"

    def mark_as_read(self):
        if not self.status_in_web:
            self.status_in_web = True
            self.save(update_fields=["status_in_web"])


class NotificationSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_settings",
    )
    website_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    reminder_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"Notification settings for {self.user}"

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
