from decimal import Decimal

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.constants import FACULTIES
from accounts.models import Course, StudentProfile, TutorProfile, User

from .models import (
    Available_Slots,
    Booking,
    CancellationDeadlinePassedError,
    Rating,
)
from .pricing import (
    MAX_PRICE,
    MIN_PRICE,
    calc_price_suggestion,
    custom_pricing,
)
from .services import (
    create_rating,
    create_session_request,
    decline_session_request,
    get_ratings,
    get_session_requests,
    get_tutor_available_slots,
    get_tutor_schedule,
    get_user_bookings,
    get_user_details,
    serialize_slot,
)

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
def create_session_request_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to make a request.'}, status=401)

    tutor_id = request.POST.get('tutor_id')
    course_id = request.POST.get('course_id')
    student_note = request.POST.get('student_note', '').strip()
    session_price = request.POST.get('session_price')

    if not tutor_id:
        return JsonResponse({'error': 'tutor_id required.'}, status=400)

    tutor = get_object_or_404(User, id=tutor_id)
    course = Course.objects.filter(id=course_id).first() if course_id else None
    price = Decimal(str(session_price)) if session_price else None

    try:
        booking = create_session_request(
            student=request.user,
            tutor=tutor,
            course=course,
            student_note=student_note,
            session_price=price,
        )
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Session request submitted.',
        'booking_id': booking.id,
        'status': booking.status,
    }, status=201)


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
def get_session_request_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to view your session requests.'}, status=401)

    open_requests = get_session_requests(request.user)

    data = [
        {
            'id': booking.id,
            'student_id': booking.student.id,
            'student_email': booking.student.email,
            'course': str(booking.course) if booking.course else None,
            'student_note': booking.student_note,
            'session_price': str(booking.session_price),
            'status': booking.status,
            'request_time': booking.request_time.isoformat() if booking.request_time else None,
        }
        for booking in open_requests
    ]

    return JsonResponse({'open_requests': data})


@require_POST
def accept_session_request_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please log in.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tutor:
        return JsonResponse({'error': 'Not your request, only the requested tutor can accept.'}, status=403)

    try:
        booking.confirm()
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Request accepted.',
        'status': booking.status,
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

    reason = request.POST.get('reason', 'Tutor declined').strip()
    if not reason:
        reason = 'Tutor declined'

    try:
        booking = decline_session_request(
            booking_id=booking_id,
            tutor=request.user,
            reason=reason,
        )
    except Booking.DoesNotExist:
        return JsonResponse(
            {'error': 'Session request not found.'},
            status=404,
        )
    except PermissionError as error:
        return JsonResponse({'error': str(error)}, status=403)
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)

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
        booking.cancel(cancelled_by=cancelled_by, reason=reason)
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
