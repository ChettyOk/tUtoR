from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Exists, OuterRef, F
from django.core.exceptions import ValidationError
from django.db.models.functions import Coalesce

from accounts.models import Course, StudentProfile, TutorProfile
from bookings.models import (
    Available_Slots,
    Booking,
    Rating,
    TutoringRequest,
    TutoringRequestInterest,
)
from bookings.pricing import calc_price_suggestion

from django.utils import timezone


class DoubleBookingError(Exception):
    pass

class RequestFulfillmentConflict(ValueError):
    pass

def create_booking_request(student, tutor, slot, course=None, student_note='', start_time=None, end_time=None):
    if (start_time is None) != (end_time is None):
        raise ValueError("Please provide both start and end time")

    if start_time is None and end_time is None:
        start_time = slot.start_time
        end_time = slot.end_time

    if timezone.is_aware(slot.start_time):
        if timezone.is_naive(start_time):
            start_time = timezone.make_aware(start_time)
        if timezone.is_naive(end_time):
            end_time = timezone.make_aware(end_time)

    if end_time <= start_time:
        raise ValueError("End time cannot be before start time.")

    if isinstance(slot, Available_Slots) and start_time <= timezone.now():
        raise ValueError("Start time cannot be in past.")

    with transaction.atomic():
        slot_model = slot.__class__
        slot = slot_model.objects.select_for_update().get(id=slot.id)

        if hasattr(slot, 'status') and slot.status != 'available':
            raise DoubleBookingError("Booking failed, slot has already been booked.")
        if isinstance(slot, Available_Slots) and slot.tutor_id != tutor.id:
            raise ValueError("slot must be offered by the tutor.")
        if start_time < slot.start_time or end_time > slot.end_time:
            raise ValueError("Booking must be fully within timeslot.")

        if isinstance(slot, Available_Slots):
            overlap = Booking.objects.filter(
                tutor_id=tutor.id,
                status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED],
                start_time__lt=end_time,
                end_time__gt=start_time,
            ).exists()

            if overlap:
                raise DoubleBookingError("This time is already booked, please choose a different slot")

        is_full_slot = (start_time == slot.start_time and end_time == slot.end_time)
        
        if hasattr(slot, 'status') and is_full_slot :
            slot.status = 'booked'
            slot.save()

        session_price = Booking.calc_price_per_session(
            price_per_hour=slot.price_per_hour,
            start_time=start_time,
            end_time=end_time,
        )

        booking = Booking.objects.create(
            student=student,
            tutor=tutor,
            course=course,
            time_slot=slot if isinstance(slot, Available_Slots) else None,
            start_time=start_time if isinstance(slot, Available_Slots) else None,
            end_time=end_time if isinstance(slot, Available_Slots) else None,
            price_per_hour=slot.price_per_hour if isinstance(slot, Available_Slots) else None,
            location_type=getattr(slot, 'location_type', None) if isinstance(slot, Available_Slots) else None,
            student_note=student_note,
            session_price=session_price,
            status=Booking.Status.CONFIRMED,
        )
        return booking

def get_user_bookings(user):

    sort_by = 'request_time'        # once available model -> 'time_slot__start_time'

    student_bookings = Booking.objects.filter(student=user).order_by(sort_by)
    tutor_bookings = Booking.objects.filter(tutor=user).order_by(sort_by)
    all_bookings = Booking.objects.filter(Q(student=user) | Q(tutor=user)).order_by(sort_by)
    
    return {'all_bookings': all_bookings, 'student_bookings': student_bookings, 'tutor_bookings': tutor_bookings}

def create_tutoring_request(
    *,
    student,
    course,
    description,
    location_type=TutoringRequest.LocationType.FLEXIBLE,
    visibility=TutoringRequest.Visibility.ALL_TUTORS,
):
    if not student.is_authenticated or not student.has_role(
        student.Role.STUDENT
    ):
        raise PermissionError(
            'Only users with an active student role can create requests.'
        )

    if not isinstance(description, str) or not description.strip():
        raise ValueError('Please describe the support you need.')

    if visibility != TutoringRequest.Visibility.ALL_TUTORS:
        raise ValueError(
            'Only visibility to all tutors is currently supported.'
        )

    tutoring_request = TutoringRequest(
        student=student,
        course=course,
        description=description.strip(),
        location_type=location_type,
        visibility=visibility,
    )

    try:
        tutoring_request.full_clean()
    except ValidationError as error:
        raise ValueError(' '.join(error.messages)) from error

    if get_existing_request_tutors(
        student=student,
        course=course,
    ).exists():
        raise ValueError(
            'Tutors already offer this course. '
            'Please view the existing tutors instead.'
        )

    tutoring_request.save()

    return tutoring_request

def get_student_tutoring_requests(student):
    return (
        TutoringRequest.objects
        .filter(student=student)
        .select_related('course')
    )


def serialize_tutoring_request(tutoring_request):
    return {
        'request_id': tutoring_request.pk,
        'course_id': tutoring_request.course_id,
        'course': str(tutoring_request.course),
        'description': tutoring_request.description,
        'location_type': tutoring_request.location_type,
        'visibility': tutoring_request.visibility,
        'status': tutoring_request.status,
        'fulfilled_booking_id': tutoring_request.fulfilled_booking_id,
        'created_at': tutoring_request.created_at.isoformat(),
    }


def withdraw_tutoring_request(*, request_id, student):
    if not student.is_authenticated or not student.has_role(
        student.Role.STUDENT
    ):
        raise PermissionError(
            'Only users with an active student role can withdraw requests.'
        )

    with transaction.atomic():
        tutoring_request = (
            TutoringRequest.objects
            .select_for_update()
            .get(
                pk=request_id,
                student=student,
            )
        )

        if tutoring_request.status != TutoringRequest.Status.OPEN:
            raise ValueError(
                'Only open tutoring requests can be withdrawn.'
            )

        tutoring_request.status = TutoringRequest.Status.WITHDRAWN
        tutoring_request.save(update_fields=['status'])

    return tutoring_request

def get_existing_request_tutors(*, student, course):
    return (
        TutorProfile.objects
        .filter(
            courses_passed=course,
            user__is_active=True,
        )
        .exclude(user_id=student.pk)
        .select_related('user')
        .order_by(
            'user__first_name',
            'user__last_name',
            'user_id',
        )
    )

def get_tutoring_request_form_data(*, student, course=None):
    existing_tutors = []

    if course is not None:
        tutor_profiles = get_existing_request_tutors(
            student=student,
            course=course,
        )

        existing_tutors = [
            {
                'tutor_id': profile.user_id,
                'first_name': profile.user.first_name,
                'last_name': profile.user.last_name,
            }
            for profile in tutor_profiles
        ]

    can_create_request = None

    if course is not None:
        can_create_request = not existing_tutors

    return {
        'courses': list(
            Course.objects
            .order_by('course_code')
            .values(
                'id',
                'course_code',
                'course_name',
                'course_faculty',
            )
        ),
        'location_types': [
            {'value': value, 'label': label}
            for value, label in TutoringRequest.LocationType.choices
        ],
        'visibility_options': [
            {
                'value': TutoringRequest.Visibility.ALL_TUTORS,
                'label': TutoringRequest.Visibility.ALL_TUTORS.label,
            },
        ],
        'description_max_length': (
            TutoringRequest._meta.get_field('description').max_length
        ),
        'selected_course_id': course.pk if course is not None else None,
        'can_create_request': can_create_request,
        'existing_tutors': existing_tutors,
    }

def get_visible_tutoring_requests(*, tutor):
    if not tutor.is_authenticated or not tutor.has_role(
        tutor.Role.TUTOR
    ):
        raise PermissionError(
            'Only users with an active tutor role can view the forum.'
        )

    return (
        TutoringRequest.objects
        .filter(
            status=TutoringRequest.Status.OPEN,
            visibility=TutoringRequest.Visibility.ALL_TUTORS,
        )
        .exclude(student=tutor)
        .select_related('course', 'student')
        .order_by('-created_at', '-id')
    )

def express_tutoring_request_interest(*, request_id, tutor):
    if not tutor.is_authenticated or not tutor.has_role(
        tutor.Role.TUTOR
    ):
        raise PermissionError(
            'Only users with an active tutor role can express interest.'
        )

    with transaction.atomic():
        tutoring_request = (
            TutoringRequest.objects
            .select_for_update()
            .filter(
                visibility=TutoringRequest.Visibility.ALL_TUTORS,
            )
            .exclude(student=tutor)
            .get(pk=request_id)
        )

        if tutoring_request.status != TutoringRequest.Status.OPEN:
            raise ValueError(
                'Interest can only be expressed in open tutoring requests.'
            )

        interest, created = (
            TutoringRequestInterest.objects.get_or_create(
                tutoring_request=tutoring_request,
                tutor=tutor,
            )
        )

    return interest, created


def withdraw_tutoring_request_interest(*, request_id, tutor):
    if not tutor.is_authenticated or not tutor.has_role(
        tutor.Role.TUTOR
    ):
        raise PermissionError(
            'Only users with an active tutor role can withdraw interest.'
        )

    with transaction.atomic():
        tutoring_request = (
            TutoringRequest.objects
            .select_for_update()
            .filter(
                visibility=TutoringRequest.Visibility.ALL_TUTORS,
            )
            .exclude(student=tutor)
            .get(pk=request_id)
        )

        deleted_count, _ = TutoringRequestInterest.objects.filter(
            tutoring_request=tutoring_request,
            tutor=tutor,
        ).delete()

    return deleted_count > 0

def get_interested_tutors(*, tutoring_request):
    return (
        TutoringRequestInterest.objects
        .filter(
            tutoring_request=tutoring_request,
            tutor__is_active=True,
        )
        .select_related('tutor')
        .order_by('created_at', 'id')
    )

def fulfill_tutoring_request(
    *,
    request_id,
    student,
    slot_id,
    start_time,
    end_time,
    student_note='',
):
    if not student.is_authenticated or not student.has_role(
        student.Role.STUDENT
    ):
        raise PermissionError(
            'Only users with an active student role can fulfill requests.'
        )

    if start_time is None or end_time is None:
        raise ValueError(
            'Please select a start and end time for this request.'
        )

    with transaction.atomic():
        tutoring_request = (
            TutoringRequest.objects
            .select_for_update()
            .get(
                pk=request_id,
                student=student,
            )
        )

        if (
            tutoring_request.status != TutoringRequest.Status.OPEN
            or tutoring_request.fulfilled_booking_id is not None
        ):
            raise RequestFulfillmentConflict(
                'Only open, unfulfilled requests can be booked.'
            )

        slot = (
            Available_Slots.objects
            .select_for_update()
            .get(pk=slot_id)
        )
        tutor = slot.tutor

        if tutor.pk == student.pk:
            raise ValueError(
                'You cannot fulfill your request with your own slot.'
            )

        if not tutor.is_active:
            raise ValueError(
                'The selected tutor is no longer active.'
            )

        has_interest = TutoringRequestInterest.objects.filter(
            tutoring_request=tutoring_request,
            tutor_id=slot.tutor_id,
        ).exists()

        if not has_interest:
            raise ValueError(
                'The selected tutor has not expressed interest '
                'in this request.'
            )

        booking = create_booking_request(
            student=student,
            tutor=tutor,
            slot=slot,
            course=tutoring_request.course,
            student_note=student_note,
            start_time=start_time,
            end_time=end_time,
        )

        tutoring_request.fulfilled_booking = booking
        tutoring_request.status = TutoringRequest.Status.FULFILLED
        tutoring_request.save(
            update_fields=['fulfilled_booking', 'status'],
        )

    return booking, tutoring_request

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
    if not hasattr(tutor, 'available_slots'):
        return []

    now = timezone.now()
    slot_list = tutor.available_slots.filter(
        status='available',
        end_time__gt=now,
    ).order_by('start_time')

    booked_intervals = sorted(
        Booking.objects.filter(
            tutor=tutor,
            status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED],
            start_time__isnull=False,
            end_time__isnull=False,
        ).values_list('start_time', 'end_time')
    )

    available_times = []
    for slot in slot_list:
        effective_start = max(slot.start_time, now)
        if slot.end_time <= effective_start:
            continue
        windows = [(effective_start, slot.end_time)]
        for booking_start, booking_end in booked_intervals:
            next_windows = []
            for window_start, window_end in windows:
                if booking_end <= window_start or booking_start >= window_end:
                    next_windows.append((window_start, window_end))
                else:
                    if booking_start > window_start:
                        next_windows.append((window_start, booking_start))
                    if booking_end < window_end:
                        next_windows.append((booking_end, window_end))
            windows = next_windows

        for window_start, window_end in windows:
            available_times.append({
                'id': slot.id,
                'start_time': window_start.isoformat() if window_start else None,
                'end_time': window_end.isoformat() if window_end else None,
                'price_per_hour': str(getattr(slot, 'price_per_hour', '0.00')),
                'location_type': getattr(slot, 'location_type', None),
                'status': getattr(slot, 'status', 'available'),
            })

    return available_times

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

def get_tutor_dashboard(tutor):
    user_bookings = get_user_bookings(tutor)

    booked_sessions = (
        user_bookings['tutor_bookings']
        .filter(status=Booking.Status.CONFIRMED)
        .select_related('student', 'course')
        .order_by('-request_time', '-pk')
    )

    own_interest = TutoringRequestInterest.objects.filter(
        tutoring_request_id=OuterRef('pk'),
        tutor_id=tutor.pk,
    )

    open_requests = (
        get_visible_tutoring_requests(tutor=tutor)
        .annotate(
            has_expressed_interest=Exists(own_interest),
        )
        .filter(has_expressed_interest=True)
    )

    schedule = get_tutor_schedule(tutor)
    
    return {
       'booked_sessions': booked_sessions,
       'open_requests': open_requests,
       'schedule': schedule,
    }
  
def get_student_dashboard(student):
    user_bookings = get_user_bookings(student)

    booked_sessions = (
        user_bookings['student_bookings']
        .filter(status=Booking.Status.CONFIRMED)
        .select_related('tutor', 'course', 'time_slot')
        .annotate(
            session_start=Coalesce(
                'start_time',
                'time_slot__start_time',
            ),
        )
        .order_by(
            F('session_start').asc(nulls_last=True),
            'pk',
        )
    )

    open_requests = (
        get_student_tutoring_requests(student)
        .filter(status=TutoringRequest.Status.OPEN)
        .order_by('-created_at', '-pk')
    )
    
    return {
        'booked_sessions': booked_sessions,
        'open_requests': open_requests,
    }

   
       

def _serialize_dashboard_booking(booking):
    return {
        'id': booking.pk,
        'student_id': booking.student_id,
        'student_email': booking.student.email,
        'course': str(booking.course) if booking.course else None,
        'student_note': booking.student_note,
        'status': booking.status,
        'request_time': (
            booking.request_time.isoformat()
            if booking.request_time is not None
            else None
        ),
        'time_slot_id': booking.time_slot_id,
        'start_time': (
            booking.start_time.isoformat()
            if booking.start_time is not None
            else None
        ),
        'end_time': (
            booking.end_time.isoformat()
            if booking.end_time is not None
            else None
        ),
        'price_per_hour': (
            str(booking.price_per_hour)
            if booking.price_per_hour is not None
            else None
        ),
        'session_price': str(booking.session_price),
        'location_type': booking.location_type,
    }
    

def _serialize_student_dashboard_booking(booking):
    start_time = booking.start_time
    end_time = booking.end_time

    if booking.time_slot_id is not None:
        if start_time is None:
            start_time = booking.time_slot.start_time

        if end_time is None:
            end_time = booking.time_slot.end_time

    return {
        'id': booking.pk,
        'status': booking.status,
        'tutor_id': booking.tutor_id,
        'tutor_first_name': booking.tutor.first_name,
        'tutor_last_name': booking.tutor.last_name,
        'course_id': booking.course_id,
        'course': (
            str(booking.course)
            if booking.course is not None
            else None
        ),
        'start_time': (
            start_time.isoformat()
            if start_time is not None
            else None
        ),
        'end_time': (
            end_time.isoformat()
            if end_time is not None
            else None
        ),
        'session_price': str(booking.session_price),
        'location_type': booking.location_type,
    }

def serialize_tutor_dashboard(dashboard):
    return {
        'booked_sessions': [
            _serialize_dashboard_booking(booking)
            for booking in dashboard['booked_sessions']
        ],
        'open_requests': [
            _serialize_dashboard_request(tutoring_request)
            for tutoring_request in dashboard['open_requests']
        ],
        'schedule': [
            serialize_slot(slot)
            for slot in dashboard['schedule']
        ],
    }

def _serialize_dashboard_request(tutoring_request):
    data = serialize_tutoring_request(tutoring_request)
    data['has_expressed_interest'] = (
        tutoring_request.has_expressed_interest
    )
    return data

def serialize_student_dashboard(dashboard):
    return {
        'booked_sessions': [
            _serialize_student_dashboard_booking(booking)
            for booking in dashboard['booked_sessions']
        ],
        'open_requests': [
            serialize_tutoring_request(tutoring_request)
            for tutoring_request in dashboard['open_requests']
        ],
    }
