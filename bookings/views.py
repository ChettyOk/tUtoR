from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from decimal import Decimal

from accounts.models import Course, User
from accounts.constants import FACULTIES
from .models import Booking
from .services import (
    create_booking_request,
    get_user_bookings,
    DoubleBookingError,
    create_session_request,
    get_session_requests,
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
        # To be added once available slots are implemented
        pass

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


@require_POST
def decline_session_request_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please log in.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tutor:
        return JsonResponse({'error': 'Not your request, only the requested tutor can accept.'}, status=403)

    reason = request.POST.get('reason', 'Tutor declined').strip()

    try:
        booking.cancel(cancelled_by='tutor', reason=reason)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'message': 'Request declined.',
        'status': booking.status,
    })


