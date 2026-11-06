from django.db import models
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from accounts.models import Course
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

from datetime import timedelta

class CancellationDeadlinePassedError(Exception):
    pass

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

    CANCEL_DEADLINE = 4 #hours
    def cancel(self, cancelled_by, reason='', cancel_deadline=CANCEL_DEADLINE):
        

        if self.status in [self.Status.CANCELLED_STUDENT, self.Status.CANCELLED_TUTOR]:
            raise ValueError(f"Booking cannot be cancelled because it was already'{self.status}'.")
        if self.status == self.Status.COMPLETED:
            raise ValueError(f"Booking cannot be cancelled because it was already completed.")
        
        if cancelled_by == 'student':
            start_time = self.time_slot.start_time if hasattr(self, 'time_slot') and self.time_slot else None
            if start_time is not None:
                time_to_session = start_time - timezone.now()
                if time_to_session < timedelta(hours=cancel_deadline):
                    raise CancellationDeadlinePassedError(
                        f"Cancellation deadline has passed. Sessions can only be cancelled at least {cancel_deadline} hours in advance."
                    )
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

class Rating(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='rating',)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,related_name='ratings_given',)
    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ratings_received',)
    class RatedRole(models.TextChoices):
        TUTOR = 'tutor', 'Tutor'
        STUDENT = 'student', 'Student'
    rated_role = models.CharField(max_length=10, choices=RatedRole.choices)
    
    rating_stars = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])

    rating_comment = models.TextField(blank=True, default='')
    rating_created_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating #{self.id} ({self.rated_role}) | {self.rating_stars}/5"

class Available_Slots(models.Model):
    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='available_slots')

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    price_per_hour = models.DecimalField(max_digits=6, decimal_places=2)

    UPDATABLE_FIELDS = ('start_time', 'end_time', 'price_per_hour', 'location_type')

    class LocationType(models.TextChoices):
        ONLINE = 'online', 'Online'
        IN_PERSON = 'in_person', 'In person'
    location_type = models.CharField(max_length=10, choices=LocationType.choices, default=LocationType.ONLINE)

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        BOOKED = 'booked', 'Booked'
        CANCELLED = 'cancelled', 'Cancelled'
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['tutor', 'start_time']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Slot #{self.id} | {self.tutor.email} | {self.start_time:%Y-%m-%d %H:%M} ({self.status})"

    def _validate(self):
        try:
            self.full_clean()
        except ValidationError as e:
            messages = []
            for field, errors in e.message_dict.items():
                for error in errors:
                    messages.append(error if field == '__all__' else f"{field}: {error}")
            raise ValueError(" ".join(messages))

    @classmethod
    def create_slot(cls, tutor, start_time, end_time, price_per_hour, location_type=LocationType.ONLINE):
        slot = cls(
            tutor=tutor,
            start_time=start_time,
            end_time=end_time,
            price_per_hour=price_per_hour,
            location_type=location_type,
        )
        slot._validate()
        slot.save()
        return slot

    def is_available(self):
        return self.status == self.Status.AVAILABLE and self.start_time > timezone.now()

    def update_slot(self, **fields):
        if self.status != self.Status.AVAILABLE:
            raise ValueError(f"Slot cannot be updated (Status: '{self.status}').")

        unknown_fields = set(fields) - set(self.UPDATABLE_FIELDS)
        if unknown_fields:
            raise ValueError(f"Slot field(s) cannot be updated: {', '.join(sorted(unknown_fields))}.")

        old_values = {name: getattr(self, name) for name in fields}
        for name, value in fields.items():
            setattr(self, name, value)

        try:
            self._validate()
        except ValueError:
            for name, value in old_values.items():
                setattr(self, name, value)
            raise

        self.save()

    def cancel_slot(self):
        if self.status == self.Status.CANCELLED:
            raise ValueError("Slot was already cancelled.")
        if self.status == self.Status.BOOKED:
            raise ValueError("Slot is already booked, cancel the booking instead.")

        self.status = self.Status.CANCELLED
        self.save()
