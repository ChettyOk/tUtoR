from django.db import transaction
from bookings.models import Booking, Rating
from django.db.models import Q, Avg
from decimal import Decimal, ROUND_HALF_UP
from accounts.models import TutorProfile


class DoubleBookingError(Exception):
    pass

def create_booking_request(student, tutor, slot, course=None, student_note=''):
    with transaction.atomic():
        slot_model = slot.__class__
        slot = slot_model.objects.select_for_update().get(id=slot.id)

        if hasattr(slot, 'status') and slot.status != 'available':
            raise DoubleBookingError("Booking failed, slot has already been booked.")
        if hasattr(slot, 'status'):
            slot.status = 'booked'
            slot.save()

        session_price = Booking.calc_price_per_session(price_per_hour=slot.price_per_hour, start_time=slot.start_time, end_time=slot.end_time)

        booking = Booking.objects.create(
            student=student,
            tutor=tutor,
            course=course,
            student_note=student_note,
            session_price=session_price,
            status=Booking.Status.CONFIRMED
        )
        return booking

def get_user_bookings(user):
    sort_by = 'request_time'        # once available model -> 'time_slot__start_time'

    student_bookings = Booking.objects.filter(student=user).order_by(sort_by)
    tutor_bookings = Booking.objects.filter(tutor=user).order_by(sort_by)
    all_bookings = Booking.objects.filter(Q(student=user) | Q(tutor=user)).order_by(sort_by)
    
    return {'all_bookings': all_bookings, 'student_bookings': student_bookings, 'tutor_bookings': tutor_bookings}

def update_tutor_rating(tutor):
    existing_ratings = Rating.objects.filter(tutor=tutor)
    tutor_profile = TutorProfile.objects.filter(user=tutor).first()

    if tutor_profile and existing_ratings.exists():
        stars_list = [r.rating_stars for r in existing_ratings]
        mean_rating = Decimal(sum(stars_list)) / Decimal(len(stars_list))
        tutor_profile.average_rating = mean_rating.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        tutor_profile.save()

def create_rating(student, booking, rating_stars, rating_comment=''):
    if booking.student != student:
        raise PermissionError("You cannot rate a session you didnt attend.")

    if booking.status != Booking.Status.COMPLETED:
        raise ValueError("You can rate sessions once they are completed.")

    if Rating.objects.filter(booking=booking).exists():
        raise ValueError("You can only rate a booking once.")

    try:
        stars_int = int(rating_stars)
    except (ValueError, TypeError):
        raise ValueError("Stars must be an whole number between 1 and 5.")

    if stars_int < 1 or stars_int > 5:
        raise ValueError("please give between 1 and 5 stars.")

    with transaction.atomic():
        rating = Rating.objects.create(
            booking=booking,
            student=student,
            tutor=booking.tutor,
            rating_stars=stars_int,
            rating_comment=rating_comment.strip() if rating_comment else '',
        )

    update_tutor_rating(booking.tutor)

    return rating


def get_tutor_ratings(tutor):
    return Rating.objects.filter(tutor=tutor).order_by('-rating_created_time')