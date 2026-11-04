from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from accounts.models import Course, User, TutorProfile
from accounts.constants import FACULTIES
from .services import get_tutor_details, get_tutor_available_slots


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
    

@require_GET
def get_tutor_details_view(request, tutor_id):
    tutor = get_object_or_404(User, id=tutor_id)

    try:
        details = get_tutor_details(tutor)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=404)

    return JsonResponse({'tutor': details})


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