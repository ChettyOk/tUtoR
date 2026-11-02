from django.db import models
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from accounts.models import Course
from decimal import Decimal, ROUND_HALF_UP

class Booking(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_bookings')

    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tutor_bookings')

    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='course_bookings')

    # ----- uncomment as soon as Available_slots is implemented -----
    # time_slot = models.ForeignKey('Available_Slots', on_delete=models.PROTECT, related_name='bookings') 

    student_note = models.CharField(max_length=255, blank=True, default='')

    session_price = models.DecimalField(max_digits=6, decimal_places=2)

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        CANCELLED_STUDENT = 'cancelled_by_student', 'Cancelled by Student'
        CANCELLED_TUTOR = 'cancelled_by_tutor', 'Cancelled by Tutor'
        COMPLETED = 'completed', 'Completed'
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)

    request_time = models.DateTimeField(auto_now_add=True)
    cancel_time = models.DateTimeField(null=True, blank=True)
    complete_time = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default='')


    def __str__(self):
        return f"Booking #{self.id} | {self.student.email} -> {self.tutor.email} ({self.status})"


    def confirm(self):
        if self.status != self.Status.PENDING:
            raise ValueError(f"Booking cannot be confirmed (Status: '{self.status}').")
        self.status = self.Status.CONFIRMED
        self.save()


    def cancel(self, cancelled_by, reason=''):
        if self.status in [self.Status.CANCELLED_STUDENT, self.Status.CANCELLED_TUTOR]:
            raise ValueError(f"Booking cannot be cancelled because it was already'{self.status}'.")
        if self.status == self.Status.COMPLETED:
            raise ValueError(f"Booking cannot be cancelled because it was already completed.")
        
        if cancelled_by == 'student':
            self.status = self.Status.CANCELLED_STUDENT
        elif cancelled_by == 'tutor':
            self.status = self.Status.CANCELLED_TUTOR
        else:
            raise ValueError(f"cancellation must be made by student or tutor")

        self.cancel_time = timezone.now()
        self.cancellation_reason = reason
        self.unblock_booking()
        self.save()


    def completed(self):
        if self.status != self.Status.CONFIRMED:
            raise ValueError(f"Booking cannot be marked completed since it has not been confirmed (Current status: '{self.status}').")
        self.status = self.Status.COMPLETED
        self.complete_time = timezone.now()
        self.save()


    @staticmethod
    def calc_price_per_session(price_per_hour, start_time, end_time):
        duration_seconds = (end_time - start_time).total_seconds()
        if duration_seconds <= 0:
            raise ValueError("End time cannot be before start time.") 
        duration_hours = Decimal(str(duration_seconds)) / Decimal('3600')

        price = Decimal(str(price_per_hour)) * duration_hours

        return price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


    def unblock_booking(self):
        if hasattr(self, 'time_slot') and self.time_slot:
            self.time_slot.status = 'available'
            self.time_slot.save()