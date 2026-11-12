from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q

from accounts.models import StudentProfile, TutorProfile
from bookings.models import Available_Slots, Booking, Rating
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
def update_rating(user, rated_role):
    if rated_role == Rating.RatedRole.TUTOR:
        existing_ratings = Rating.objects.filter(tutor=user, rated_role=Rating.RatedRole.TUTOR)
        profile = TutorProfile.objects.filter(user=user).first()
    elif rated_role == Rating.RatedRole.STUDENT:
        existing_ratings = Rating.objects.filter(student=user, rated_role=Rating.RatedRole.STUDENT)
        profile = StudentProfile.objects.filter(user=user).first()
    else:
        raise ValueError("Error: no role (student/tutor) provided.")

    if profile and existing_ratings.exists():
        stars_list = [r.rating_stars for r in existing_ratings]
        mean_rating = Decimal(sum(stars_list)) / Decimal(len(stars_list))
        profile.average_rating = mean_rating.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        profile.save()


def create_rating(user, booking, rating_stars, rating_comment=''):
    if user == booking.student:
        rated_role = Rating.RatedRole.TUTOR
        rated_user = booking.tutor
    elif user == booking.tutor:
        rated_role = Rating.RatedRole.STUDENT
        rated_user = booking.student
    else:
        raise PermissionError("You cannot rate a session you didnt attend.")

    if booking.status != Booking.Status.COMPLETED:
        raise ValueError("You can rate sessions once they are completed.")

    if Rating.objects.filter(booking=booking, rated_role=rated_role).exists():
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
            student=booking.student,
            tutor=booking.tutor,
            rated_role=rated_role,
            rating_stars=stars_int,
            rating_comment=rating_comment.strip() if rating_comment else '',
        )

    update_rating(rated_user, rated_role)

    return rating


def get_ratings(user, rated_role):
    if rated_role == Rating.RatedRole.STUDENT:
        return Rating.objects.filter(student=user, rated_role=Rating.RatedRole.STUDENT).order_by('-rating_created_time')
    elif rated_role == Rating.RatedRole.TUTOR:
        return Rating.objects.filter(tutor=user, rated_role=Rating.RatedRole.TUTOR).order_by('-rating_created_time')
    else:
        raise ValueError("Error: no role (student/tutor) provided.")


def get_user_details(user, role):
    if role == user.Role.TUTOR:
        tutor_profile = TutorProfile.objects.filter(user=user).first()
        if not tutor_profile:
            raise ValueError("This user doesnt have an tutor profile.")

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
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'bio': tutor_profile.bio,
            'average_rating': tutor_profile.display_tutor_rating,
            'suggested_price': str(calc_price_suggestion(user)),
            'courses_passed': courses,
        }

    elif role == user.Role.STUDENT:
        student_profile = StudentProfile.objects.filter(user=user).first()
        if not student_profile:
            raise ValueError("This user doesnt have an tutor profile.")

        courses = [
            {
                'id': course.id,
                'course_code': course.course_code,
                'course_name': course.course_name,
                'course_faculty': course.course_faculty,
            }
            for course in student_profile.courses.all().order_by('course_code')
        ]

        return {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'major': student_profile.major,
            'semester': student_profile.semester,
            'average_rating': student_profile.display_student_rating,
            'courses': courses,
        }
    else:
        raise ValueError("Error: no role (student/tutor) provided.")


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

def serialize_slot(slot):
    return {
        'id': slot.id,
        'start_time': slot.start_time.isoformat(),
        'end_time': slot.end_time.isoformat(),
        'price_per_hour': str(slot.price_per_hour),
        'location_type': slot.location_type,
        'status': slot.status,
    }


def get_tutor_schedule(tutor):
    return Available_Slots.objects.filter(
        tutor=tutor,
    ).order_by('start_time', 'id')
