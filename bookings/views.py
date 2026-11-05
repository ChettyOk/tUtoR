from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from accounts.models import Course, User, TutorProfile, User, TutorProfile, StudentProfile
from accounts.constants import FACULTIES
from .models import Booking, Rating
from .services import create_rating, get_ratings
from .services import get_user_details, get_tutor_available_slots


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