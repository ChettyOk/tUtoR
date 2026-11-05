from django.shortcuts import render
from django.db.models import Q
from accounts.models import Course
from accounts.constants import FACULTIES

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.shortcuts import get_object_or_404
from .models import Booking, CancellationDeadlinePassedError
from .services import create_booking_request, get_user_bookings, DoubleBookingError


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