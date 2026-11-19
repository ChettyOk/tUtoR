from decimal import Decimal

from django.db.models import Q
from django.db import OperationalError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import reverse

from accounts.constants import FACULTIES
from accounts.models import Course, StudentProfile, TutorProfile, User
from accounts.views import check_role_access

from .models import (
    Available_Slots,
    Booking,
    CancellationDeadlinePassedError,
    Rating,
    TutoringRequest,
)
from .pricing import (
    MAX_PRICE,
    MIN_PRICE,
    calc_price_suggestion,
    custom_pricing,
)
from .services import (
    create_rating,
    create_tutoring_request,
    get_interested_tutors,
    get_ratings,
    get_tutor_available_slots,
    get_tutor_schedule,
    get_tutoring_request_form_data,
    get_user_bookings,
    get_user_details,
    get_visible_tutoring_requests,
    serialize_slot,
    DoubleBookingError,
    get_student_tutoring_requests,
    cancel_booking,
    serialize_tutoring_request,
    withdraw_tutoring_request,
    express_tutoring_request_interest,
    withdraw_tutoring_request_interest,
    create_booking_request,
    get_student_dashboard,
    serialize_student_dashboard,
    fulfill_tutoring_request,
    RequestFulfillmentConflict,
)

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from accounts.forms import CoursePickForm

def filter_courses(request):
    search_query = request.GET.get('q', '').strip()
    selected_faculty = request.GET.get('faculty', '').strip()
    selected_subject = request.GET.get('subject', '').strip()
    has_tutor_offering = request.GET.get('has_tutor', '').lower() in ['true', '1', 'on']

    courses = Course.objects.all()

    if selected_faculty and selected_faculty != 'all': 
        courses = courses.filter(course_faculty__iexact = selected_faculty)
        available_subjects = sorted([i for i, v in FACULTIES.items() if v.lower() == selected_faculty.lower()])
    else:
        available_subjects = sorted(FACULTIES.keys())
    
    if selected_subject and selected_subject != 'all': 
        courses = courses.filter(course_code__istartswith=selected_subject)
        
    
    if has_tutor_offering: 
        courses = courses.filter(tutor_profiles__isnull=False).distinct()
        

    if search_query:
        courses = courses.filter(Q(course_code__icontains = search_query) | Q(course_name__icontains = search_query))
        
    available_faculties = sorted(set(FACULTIES.values()))

    context = {
        'courses': courses,
        'available_faculties': available_faculties,
        'available_subjects': available_subjects,
        'selected_faculty': selected_faculty,
        'selected_subject': selected_subject,
        'search_query': search_query,
        'has_tutor_offering': has_tutor_offering,
    }

    return render(request, 'bookings/search_results.html', context)
    

@require_POST
def create_tutoring_request_view(request):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    raw_course_id = request.POST.get('course_id', '').strip()

    if not raw_course_id:
        return JsonResponse(
            {'error': 'course_id is required.'},
            status=400,
        )

    try:
        course_id = int(raw_course_id)

        if course_id <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return JsonResponse(
            {'error': 'course_id must be a positive integer.'},
            status=400,
        )

    course = get_object_or_404(Course, pk=course_id)

    try:
        tutoring_request = create_tutoring_request(
            student=request.user,
            course=course,
            description=request.POST.get('description', ''),
            location_type=request.POST.get(
                'location_type',
                TutoringRequest.LocationType.FLEXIBLE,
            ),
            visibility=request.POST.get(
                'visibility',
                TutoringRequest.Visibility.ALL_TUTORS,
            ),
        )
    except PermissionError as error:
        return JsonResponse(
            {'error': str(error)},
            status=403,
        )
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse(
        {
            'message': 'Tutoring request published.',
            'request_id': tutoring_request.pk,
            'status': tutoring_request.status,
        },
        status=201,
    )

@require_GET
def get_my_tutoring_requests_view(request):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    tutoring_requests = get_student_tutoring_requests(request.user)

    return JsonResponse({
        'requests': [
            serialize_tutoring_request(tutoring_request)
            for tutoring_request in tutoring_requests
        ],
    })


@require_GET
def get_my_tutoring_request_view(request, request_id):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    tutoring_request = get_object_or_404(
        get_student_tutoring_requests(request.user),
        pk=request_id,
    )

    return JsonResponse({
        'request': serialize_tutoring_request(tutoring_request),
    })


@require_POST
def withdraw_tutoring_request_view(request, request_id):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    try:
        tutoring_request = withdraw_tutoring_request(
            request_id=request_id,
            student=request.user,
        )
    except TutoringRequest.DoesNotExist:
        return JsonResponse(
            {'error': 'Tutoring request not found.'},
            status=404,
        )
    except PermissionError as error:
        return JsonResponse(
            {'error': str(error)},
            status=403,
        )
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse({
        'message': 'Tutoring request withdrawn.',
        'request_id': tutoring_request.pk,
        'status': tutoring_request.status,
    })

@require_GET
def get_tutoring_request_form_view(request):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    course = None
    raw_course_id = request.GET.get('course_id')

    if raw_course_id is not None:
        try:
            course_id = int(raw_course_id)

            if course_id <= 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            return JsonResponse(
                {'error': 'course_id must be a positive integer.'},
                status=400,
            )

        course = get_object_or_404(Course, pk=course_id)

    return JsonResponse(
        get_tutoring_request_form_data(
            student=request.user,
            course=course,
        ),
    )

@require_POST
def express_tutoring_request_interest_view(request, request_id):
    error_response = check_role_access(
        request,
        User.Role.TUTOR,
    )

    if error_response is not None:
        return error_response

    try:
        interest, created = express_tutoring_request_interest(
            request_id=request_id,
            tutor=request.user,
        )
    except TutoringRequest.DoesNotExist:
        return JsonResponse(
            {'error': 'Tutoring request not found.'},
            status=404,
        )
    except PermissionError as error:
        return JsonResponse(
            {'error': str(error)},
            status=403,
        )
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse(
        {
            'message': 'Interest recorded.',
            'request_id': interest.tutoring_request_id,
            'interested': True,
        },
        status=201 if created else 200,
    )


@require_POST
def withdraw_tutoring_request_interest_view(request, request_id):
    error_response = check_role_access(
        request,
        User.Role.TUTOR,
    )

    if error_response is not None:
        return error_response

    try:
        removed = withdraw_tutoring_request_interest(
            request_id=request_id,
            tutor=request.user,
        )
    except TutoringRequest.DoesNotExist:
        return JsonResponse(
            {'error': 'Tutoring request not found.'},
            status=404,
        )
    except PermissionError as error:
        return JsonResponse(
            {'error': str(error)},
            status=403,
        )

    return JsonResponse({
        'message': 'Interest withdrawn.',
        'request_id': request_id,
        'interested': False,
        'removed': removed,
    })

@require_GET
def get_interested_tutors_view(request, request_id):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    tutoring_request = get_object_or_404(
        get_student_tutoring_requests(request.user),
        pk=request_id,
    )

    interests = get_interested_tutors(
        tutoring_request=tutoring_request,
    )

    return JsonResponse({
        'request_id': tutoring_request.pk,
        'status': tutoring_request.status,
        'interested_tutors': [
            {
                'tutor_id': interest.tutor_id,
                'first_name': interest.tutor.first_name,
                'last_name': interest.tutor.last_name,
                'interested_since': interest.created_at.isoformat(),
                'profile_url': reverse(
                    'tutor_details',
                    kwargs={'user_id': interest.tutor_id},
                ),
                'availability_url': reverse(
                    'tutor_slots',
                    kwargs={'tutor_id': interest.tutor_id},
                ),
            }
            for interest in interests
        ],
    })

@require_POST
def fulfill_tutoring_request_view(request, request_id):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Log in to fulfill a tutoring request.'},
            status=401,
        )

    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )
    if error_response is not None:
        return error_response

    raw_slot_id = request.POST.get('slot_id', '').strip()

    try:
        slot_id = int(raw_slot_id)
        if slot_id <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return JsonResponse(
            {'error': 'slot_id must be a positive integer.'},
            status=400,
        )

    raw_start = request.POST.get('start_time', '').strip()
    raw_end = request.POST.get('end_time', '').strip()

    if not raw_start or not raw_end:
        return JsonResponse(
            {'error': 'Please provide start_time and end_time.'},
            status=400,
        )

    try:
        start_time = parse_datetime(raw_start)
        end_time = parse_datetime(raw_end)
    except (ValueError, OverflowError):
        start_time = end_time = None

    if start_time is None or end_time is None:
        return JsonResponse(
            {'error': 'Please provide valid ISO start and end times.'},
            status=400,
        )

    try:
        booking, tutoring_request = fulfill_tutoring_request(
            request_id=request_id,
            student=request.user,
            slot_id=slot_id,
            start_time=start_time,
            end_time=end_time,
            student_note=request.POST.get(
                'student_note', '',
            ).strip(),
        )
    except TutoringRequest.DoesNotExist:
        return JsonResponse(
            {'error': 'Tutoring request not found.'},
            status=404,
        )
    except Available_Slots.DoesNotExist:
        return JsonResponse(
            {'error': 'Slot not found.'},
            status=404,
        )
    except PermissionError as error:
        return JsonResponse(
            {'error': str(error)},
            status=403,
        )
    except (RequestFulfillmentConflict, DoubleBookingError) as error:
        return JsonResponse(
            {'error': str(error)},
            status=409,
        )
    except OperationalError:
        return JsonResponse(
            {
                'error': (
                    'The request could not be processed. '
                    'Please try again.'
                ),
            },
            status=503,
        )
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse(
        {
            'message': 'Tutoring request fulfilled.',
            'request_id': tutoring_request.pk,
            'request_status': tutoring_request.status,
            'booking_id': booking.pk,
            'booking_status': booking.status,
            'time_slot_id': booking.time_slot_id,
            'start_time': booking.start_time.isoformat(),
            'end_time': booking.end_time.isoformat(),
            'session_price': str(booking.session_price),
        },
        status=201,
    )

@require_POST
def submit_rating_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'You have to be logged in to submit a rating.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)
    rating_stars = request.POST.get('stars')
    rating_comment = request.POST.get('comment', '')

    try:
        rating = create_rating(
            user=request.user,
            booking=booking,
            rating_stars=rating_stars,
            rating_comment=rating_comment,
        )
    except PermissionError as e:
        return JsonResponse({'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Rating submitted successfully.',
        'rating_id': rating.id,
        'stars': rating.rating_stars,
        'comment': rating.rating_comment,
    }, status=201)

@require_GET
def get_tutoring_request_forum_view(request):
    error_response = check_role_access(
        request,
        User.Role.TUTOR,
    )

    if error_response is not None:
        return error_response

    tutoring_requests = get_visible_tutoring_requests(
        tutor=request.user,
    )

    return JsonResponse({
        'open_requests': [
            serialize_tutoring_request(tutoring_request)
            for tutoring_request in tutoring_requests
        ],
    })

@require_GET
def get_ratings_view(request, user_id, rated_role):
    user = get_object_or_404(User, id=user_id)

    try:
        ratings = get_ratings(user, rated_role)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if rated_role == Rating.RatedRole.TUTOR:
        profile = TutorProfile.objects.filter(user=user).first()
        avg_rating = profile.display_tutor_rating if profile else 'No rating yet'
    else:
        profile = StudentProfile.objects.filter(user=user).first()
        avg_rating = profile.display_student_rating if profile else 'No rating yet'

    data = [
        {
            'id': rating.id,
            'student_email': rating.student.email,
            'tutor_email': rating.tutor.email,
            'stars': rating.rating_stars,
            'comment': rating.rating_comment,
            'created_at': rating.rating_created_time.isoformat() if rating.rating_created_time else None,
        }
        for rating in ratings
    ]

    return JsonResponse({
        'user_id': user.id,
        'rated_role': rated_role,
        'average_rating': avg_rating,
        'ratings': data,
    })

@require_GET
def get_user_details_view(request, user_id, role):
    user = get_object_or_404(User, id=user_id)

    try:
        details = get_user_details(user, role)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=404)

    return JsonResponse({role: details})


@require_GET
def get_tutor_slots_view(request, tutor_id):
    tutor = get_object_or_404(User, id=tutor_id)

    if not TutorProfile.objects.filter(user=tutor).exists():
        return JsonResponse({'error': 'No tutor Profile found for this user.'}, status=404)

    slots = get_tutor_available_slots(tutor)
    return JsonResponse({
        'tutor_id': tutor.id,
        'available_slots': slots,
    })  
@require_GET
def get_bookings(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to view bookings.'}, status=401)

    bookings = get_user_bookings(request.user)
    
    def serialize_booking(booking):
        return {
            'id': booking.id,
            'student_id': booking.student.id,
            'student_email': booking.student.email,
            'tutor_id': booking.tutor.id,
            'tutor_email': booking.tutor.email,
            'course': str(booking.course) if booking.course else None,
            'time_slot_id': booking.time_slot_id,
            'start_time': booking.start_time.isoformat() if booking.start_time else None,
            'end_time': booking.end_time.isoformat() if booking.end_time else None,
            'price_per_hour': str(booking.price_per_hour) if booking.price_per_hour is not None else None,
            'location_type': booking.location_type,
            'session_price': str(booking.session_price),
            'status': booking.status,
            'student_note': booking.student_note,
            'request_time': booking.request_time.isoformat() if booking.request_time else None,
            'cancel_time': booking.cancel_time.isoformat() if booking.cancel_time else None,
            'cancellation_reason': booking.cancellation_reason,
        }

    return JsonResponse({
        'student_bookings': [serialize_booking(booking) for booking in bookings['student_bookings']],
        'tutor_bookings': [serialize_booking(booking) for booking in bookings['tutor_bookings']],
    })


@require_POST
def decline_session_request_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please log in.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tutor:
        return JsonResponse({'error': 'Not your request, only the requested tutor can accept.'}, status=403)

    reason = request.POST.get('reason', 'Tutor declined').strip()

    try:
        cancel_booking(booking, cancelled_by='tutor', reason=reason)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Request declined.',
        'status': booking.status,
    })


@require_POST
def cancel_booking_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to cancel booking.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.student and request.user != booking.tutor:
        return JsonResponse({'error': 'You can only cancel your own bookings!!!'}, status=403)

    cancelled_by = 'student' if request.user == booking.student else 'tutor'
    reason = request.POST.get('reason', '').strip()

    try:
        cancel_booking(booking, cancelled_by=cancelled_by, reason=reason)
    except CancellationDeadlinePassedError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Booking cancelled!',
        'status': booking.status,
        'cancel_time': booking.cancel_time.isoformat() if booking.cancel_time else None,
    })

@require_GET
def get_tutor_schedule_view(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    if not request.user.has_role(User.Role.TUTOR):
        return JsonResponse(
            {'error': 'Your active role does not allow this action.'},
            status=403,
        )

    slots = get_tutor_schedule(request.user)

    return JsonResponse({
        'slots': [serialize_slot(slot) for slot in slots],
    })

def _parse_slot_input(data, *, partial=False):
    fields = {}

    for name in ('start_time', 'end_time', 'price_per_hour'):
        if name not in data:
            if partial:
                continue
            raise ValueError(f"{name} is required.")

        value = data.get(name, '').strip()
        if not value:
            raise ValueError(f"{name} must not be empty.")

        if name == 'price_per_hour':
            try:
                price = Decimal(value)
            except ArithmeticError:
                raise ValueError("Price must be a valid number.")

            if not price.is_finite():
                raise ValueError("Price must be a valid number.")

            fields[name] = custom_pricing(price)
        else:
            try:
                parsed_time = parse_datetime(value)
            except (ValueError, OverflowError):
                parsed_time = None

            if parsed_time is None:
                raise ValueError(f"{name} must be a valid ISO date and time.")

            fields[name] = parsed_time

    if 'location_type' in data:
        location_type = data.get('location_type', '').strip()
        if not location_type:
            raise ValueError("location_type must not be empty.")
        fields['location_type'] = location_type

    return fields

@require_http_methods(['GET', 'POST'])
def create_slot_view(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    if not request.user.has_role(User.Role.TUTOR):
        return JsonResponse(
            {'error': 'Your active role does not allow this action.'},
            status=403,
        )

    if request.method == 'GET':
        return JsonResponse({
            'suggested_price': str(calc_price_suggestion(request.user)),
            'min_price': str(MIN_PRICE),
            'max_price': str(MAX_PRICE),
            'location_types': [
                {'value': value, 'label': label}
                for value, label in Available_Slots.LocationType.choices
            ],
            'timezone': timezone.get_current_timezone_name(),
        })

    try:
        fields = _parse_slot_input(request.POST)
        slot = Available_Slots.create_slot(
            tutor=request.user,
            **fields,
        )
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse({
        'message': 'Slot created successfully.',
        'slot': serialize_slot(slot),
    }, status=201)

@require_http_methods(['GET', 'POST'])
def update_slot_view(request, slot_id):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    if not request.user.has_role(User.Role.TUTOR):
        return JsonResponse(
            {'error': 'Your active role does not allow this action.'},
            status=403,
        )

    try:
        slot = Available_Slots.objects.get(pk=slot_id)
    except Available_Slots.DoesNotExist:
        return JsonResponse(
            {'error': 'Slot not found.'},
            status=404,
        )

    if slot.tutor_id != request.user.id:
        return JsonResponse(
            {'error': 'You can only update your own slots.'},
            status=403,
        )

    if request.method == 'GET':
        return JsonResponse({
            'slot': serialize_slot(slot),
            'min_price': str(MIN_PRICE),
            'max_price': str(MAX_PRICE),
            'location_types': [
                {'value': value, 'label': label}
                for value, label in Available_Slots.LocationType.choices
            ],
            'timezone': timezone.get_current_timezone_name(),
        })

    try:
        fields = _parse_slot_input(request.POST, partial=True)

        if not fields:
            raise ValueError("Provide at least one slot field to update.")

        slot.update_slot(**fields)
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse({
        'message': 'Slot updated successfully.',
        'slot': serialize_slot(slot),
    })

@require_POST
def delete_slot_view(request, slot_id):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    if not request.user.has_role(User.Role.TUTOR):
        return JsonResponse(
            {'error': 'Your active role does not allow this action.'},
            status=403,
        )

    try:
        slot = Available_Slots.objects.get(pk=slot_id)
    except Available_Slots.DoesNotExist:
        return JsonResponse(
            {'error': 'Slot not found.'},
            status=404,
        )

    if slot.tutor_id != request.user.id:
        return JsonResponse(
            {'error': 'You can only cancel your own slots.'},
            status=403,
        )

    try:
        slot.cancel_slot()
    except ValueError as error:
        return JsonResponse(
            {'error': str(error)},
            status=400,
        )

    return JsonResponse({
        'message': 'Slot cancelled successfully.',
        'slot': serialize_slot(slot),
    })

@require_GET
def get_student_dashboard_view(request):
    error_response = check_role_access(
        request,
        User.Role.STUDENT,
    )

    if error_response is not None:
        return error_response

    dashboard = get_student_dashboard(request.user)

    return JsonResponse(
        serialize_student_dashboard(dashboard),
    )

@login_required
def tutor_sessions_page(request):
    """Page where a tutor sets up sessions: courses, slot form and schedule."""
    if not request.user.has_role(User.Role.TUTOR):
        return redirect('student_home')

    profile = TutorProfile.objects.filter(user=request.user).first()
    selected_ids = list(profile.courses_passed.values_list('pk', flat=True)) if profile else []

    return render(request, 'tutor/sessions/setup.html', {
        'site_name': 'tUtoR',
        'campus': 'University of Regina',
        # every course, for the search box; the page script filters them in the browser
        'courses': list(
            Course.objects.order_by('course_code')
            .values('id', 'course_code', 'course_name', 'course_faculty')
        ),
        'selected_ids': selected_ids,
    })


@login_required
@require_POST
def tutor_save_courses(request):
    """Save the courses a tutor teaches (the picker form on the sessions page)."""
    if not request.user.has_role(User.Role.TUTOR):
        return redirect('student_home')

    form = CoursePickForm(request.POST)   # no limit for tutors
    if form.is_valid():
        profile, _ = TutorProfile.objects.get_or_create(user=request.user)
        profile.courses_passed.set(form.cleaned_data['courses'])
        messages.success(request, 'Your courses were saved.')
    else:
        messages.error(request, 'Some of the chosen courses do not exist. Please try again.')

    return redirect('tutor_sessions')

@require_POST
def book_slot_view(request, slot_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'you have to be logged in to book a slot'}, status=401)

    error_response = check_role_access(request, User.Role.STUDENT)
    if error_response is not None:
        return error_response

    slot = get_object_or_404(Available_Slots, id=slot_id)

    course_id = request.POST.get('course_id')
    course = None
    if course_id:
        try:
            course_id = int(course_id)
            if course_id <= 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            return JsonResponse({'error': 'course_id invalid.'}, status=400)
        course = get_object_or_404(Course, id=course_id)

    raw_start = request.POST.get('start_time', '').strip()
    raw_end = request.POST.get('end_time', '').strip()
    start_time = end_time = None
    if raw_start or raw_end:
        if not raw_start or not raw_end:
            return JsonResponse({'error': 'please prvide start and end time'}, status=400)
        try:
            start_time = parse_datetime(raw_start)
            end_time = parse_datetime(raw_end)
        except (ValueError, OverflowError):
            start_time = end_time = None
        if start_time is None or end_time is None:
            return JsonResponse({'error': 'please provide a valid start and end time'}, status=400)

    try:
        booking = create_booking_request(
            student=request.user,
            tutor=slot.tutor,
            slot=slot,
            course=course,
            student_note=request.POST.get('student_note', '').strip(),
            start_time=start_time,
            end_time=end_time,
        )
    except (DoubleBookingError, OperationalError) as e:
        return JsonResponse({'error': str(e)}, status=409)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Booking confirmed.',
        'booking_id': booking.id,
        'status': booking.status,
        'session_price': str(booking.session_price),
        'time_slot_id': booking.time_slot_id,
        'start_time': booking.start_time.isoformat(),
        'end_time': booking.end_time.isoformat(),
    }, status=201)


@require_POST
def complete_booking_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'you must be logged in to complete a booking.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)
    if request.user != booking.tutor and request.user != booking.student:
        return JsonResponse({'error': 'you can only acces your own bookings'}, status=403)

    try:
        booking.completed()
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Booking marked as completed.',
        'status': booking.status,
    })
