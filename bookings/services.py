from django.db import transaction
from bookings.models import Booking
from django.db.models import Q
from bookings.pricing import calc_price_suggestion


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

def create_session_request(student, tutor, course=None, student_note='', session_price=None):

    if not tutor:
        raise ValueError("Please select a tutor.")
    
    if session_price is None:
        session_price = calc_price_suggestion(tutor)

    if not student_note or not student_note.strip():
        raise ValueError("Please specify your request in the note field.")

    booking = Booking.objects.create(
        student=student,
        tutor=tutor,
        course=course,
        student_note=student_note,
        session_price=session_price,
        status=Booking.Status.PENDING,)
    return booking


def get_session_requests(tutor):
    return Booking.objects.filter(
        tutor=tutor,
        status=Booking.Status.PENDING).order_by('-request_time')