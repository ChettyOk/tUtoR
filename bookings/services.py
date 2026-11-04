from django.db import transaction
from bookings.models import Booking
from django.db.models import Q

from bookings.pricing import calc_price_suggestion
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


def get_tutor_details(tutor):
    tutor_profile = TutorProfile.objects.filter(user=tutor).first()
    if not tutor_profile:
        raise ValueError("No Tutor Profile found for this user.")

    courses = [
        {
            'id': course.id,
            'course_code': course.course_code,
            'course_name': course.course_name,
            'course_faculty': course.course_faculty,
        }
        for course in tutor_profile.courses_passed.all().order_by('course_code')
    ]

    return {
        'id': tutor.id,
        'first_name': tutor.first_name,
        'last_name': tutor.last_name,
        'email': tutor.email,
        'bio': tutor_profile.bio,
        'average_rating': tutor_profile.display_tutor_rating,
        'suggested_price': str(calc_price_suggestion(tutor)),
        'courses_passed': courses,
    }


def get_tutor_available_slots(tutor):
    if hasattr(tutor, 'available_slots'):
        slot_list = tutor.available_slots.filter(status='available').order_by('start_time')

        return [
            {
                'id': slot.id,
                'start_time': slot.start_time.isoformat() if hasattr(slot, 'start_time') and slot.start_time else None,
                'end_time': slot.end_time.isoformat() if hasattr(slot, 'end_time') and slot.end_time else None,
                'price_per_hour': str(getattr(slot, 'price_per_hour', '0.00')),
                'status': getattr(slot, 'status', 'available'),
            }
            for slot in slot_list
        ]
    return []