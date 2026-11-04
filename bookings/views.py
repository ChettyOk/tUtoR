from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Course, User, TutorProfile
from accounts.constants import FACULTIES
from .models import Booking, Rating
from .services import create_rating, get_tutor_ratings


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
def submit_rating_view(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'You have to be logged in to submit a rating.'}, status=401)

    booking = get_object_or_404(Booking, id=booking_id)
    rating_stars = request.POST.get('stars')
    rating_comment = request.POST.get('comment', '')

    try:
        rating = create_rating(
            student=request.user,
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
def get_tutor_ratings_view(request, tutor_id):
    tutor = get_object_or_404(User, id=tutor_id)
    ratings = get_tutor_ratings(tutor)
    tutor_profile = TutorProfile.objects.filter(user=tutor).first()

    data = [
        {
            'id': rating.id,
            'student_email': rating.student.email,
            'stars': rating.rating_stars,
            'comment': rating.rating_comment,
            'created_at': rating.rating_created_time.isoformat() if rating.rating_created_time else None,
        }
        for rating in ratings
    ]

    return JsonResponse({
        'tutor_id': tutor.id,
        'average_rating': tutor_profile.display_tutor_rating if tutor_profile else 'No rating yet',
        'ratings': data,
    })