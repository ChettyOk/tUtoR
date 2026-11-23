from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)

from bookings.services import (
    get_student_dashboard,
    get_tutor_dashboard,
    serialize_tutor_dashboard,
)

from .constants import FACULTIES
from .forms import (
    AccountProfileForm,
    CoursePickForm,
    RegisterForm,
    StudentProfileForm,
    TutorProfileForm,
)
from .models import Course, StudentProfile, TutorProfile, User

# Auth Controller
@require_POST
def register(request):
    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")

    errors = {}

    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Please enter a valid email address."

    if len(password) < 8:
        errors["password"] = "The password must be at least 8 characters long."

    if errors:
        return JsonResponse({"errors": errors}, status=400)

    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse(
            {"errors": {"email": "This email address is already registered."}},
            status=409,
        )

    User.objects.create_user(email=email, password=password)
    return JsonResponse({"message": "User account created."}, status=201)


@require_POST
def login(request):
    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")

    user = authenticate(request, username=email, password=password)

    if user is None:
        return JsonResponse(
            {"error": "Invalid email address or password."},
            status=401,
        )
    auth_login(request, user)
    return JsonResponse({"message": "Login successful."}, status=200)


@require_POST
def logout(request):
    auth_logout(request)
    # Browser account menu posts with ui=1; API clients still get JSON.
    if request.POST.get("ui") == "1":
        return redirect("landing")
    return JsonResponse({"message": "Logout successful."}, status=200)


@require_POST
def request_forgotten_password(request):
    form = PasswordResetForm(request.POST)

    if not form.is_valid():
        return JsonResponse(
            {"errors": form.errors.get_json_data()},
            status=400,
        )

    form.save(
        request=request,
        use_https=request.is_secure(),
        email_template_name="registration/password_reset_email.txt",
        subject_template_name="registration/password_reset_subject.txt",
    )

    # Keep the response the same whether or not the email belongs to an account.
    return JsonResponse(
        {"message": "If an account exists for that email, a reset link has been sent."},
        status=200,
    )

# Profile Controller
from django.http import JsonResponse


def check_role_access(request, required_role):
    user = request.user

    if not user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    if not user.has_role(required_role):
        return JsonResponse(
            {'error': 'Your active role does not allow this action.'},
            status=403,
        )

    return None

@require_http_methods(['GET', 'POST'])
def get_my_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Please log in to view or update your profile.'},
            status=401,
        )

    user = request.user

    if request.method == 'POST':
        profile_type = request.POST.get('profile_type', 'account')

        if profile_type == 'student':
            error_response = check_role_access(
                request,
                User.Role.STUDENT,
            )

            if error_response is not None:
                return error_response

            return _update_student_profile(user, request.POST)

        if profile_type == 'tutor':
            error_response = check_role_access(
                request,
                User.Role.TUTOR,
            )

            if error_response is not None:
                return error_response

            return _update_tutor_profile(user, request.POST)

        if profile_type != 'account':
            return JsonResponse(
                {'errors': {
                    'profile_type': ['Choose a valid profile type.'],
                }},
                status=400,
            )

        form = AccountProfileForm(
            data=request.POST,
            instance=user,
        )

        if not form.is_valid():
            return JsonResponse(
                {'errors': form.errors.get_json_data()},
                status=400,
            )

        form.save()

        return JsonResponse({
            'message': 'Account profile updated.',
        })

    student_profile = StudentProfile.objects.filter(user=user).first()
    student_data = None

    if student_profile is not None:
        student_data = {
            'major': student_profile.major,
            'semester': student_profile.semester,
            'courses': list(
                student_profile.courses
                .order_by('pk')
                .values_list('pk', flat=True)
            ),
            'average_rating': (
                str(student_profile.average_rating)
                if student_profile.average_rating is not None
                else None
            ),
        }

    tutor_profile = TutorProfile.objects.filter(user=user).first()
    tutor_data = None

    if tutor_profile is not None:
        tutor_data = {
            'bio': tutor_profile.bio,
            'courses_passed': list(
                tutor_profile.courses_passed
                .order_by('pk')
                .values_list('pk', flat=True)
            ),
            'average_rating': (
                str(tutor_profile.average_rating)
                if tutor_profile.average_rating is not None
                else None
            ),
        }

    return JsonResponse({
        'account': {
            'id': user.pk,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone': user.phone,
            'role': user.role,
        },
        'student_profile': student_data,
        'tutor_profile': tutor_data,
    })

def _update_student_profile(user, data):
    profile = StudentProfile.objects.filter(user=user).first()

    if profile is None:
        profile = StudentProfile(user=user)

    form = StudentProfileForm(
        data=data,
        instance=profile,
    )

    if not form.is_valid():
        return JsonResponse(
            {'errors': form.errors.get_json_data()},
            status=400,
        )

    with transaction.atomic():
        form.save()

    return JsonResponse({
        'message': 'Student profile updated.',
    })

@require_POST
def switch_role(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Please log in to switch your role.'},
            status=401,
        )

    user = request.user
    role = request.POST.get('role', '')

    try:
        user.switch_role(role)
    except ValueError as error:
        return JsonResponse(
            {'errors': {
                'role': [str(error)],
            }},
            status=400,
        )

    user.save(update_fields=['role', 'updated_at'])

    return JsonResponse({
        'message': 'Active role updated.',
        'role': user.role,
    })

def _update_tutor_profile(user, data):
    profile = TutorProfile.objects.filter(user=user).first()

    if profile is None:
        profile = TutorProfile(user=user)

    form = TutorProfileForm(
        data=data,
        instance=profile,
    )

    if not form.is_valid():
        return JsonResponse(
            {'errors': form.errors.get_json_data()},
            status=400,
        )

    with transaction.atomic():
        form.save()

    return JsonResponse(
        {'message': 'Tutor profile updated.'},
        status=200,
    )


@require_POST
def favorite_tutor_view(request, tutor_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to add or remove favorite tutors.'}, status=401)

    tutor = get_object_or_404(User, id=tutor_id)
    tutor_profile = TutorProfile.objects.filter(user=tutor).first()
    if not tutor_profile:
        return JsonResponse({'error': 'No tutor profile found for this user ask them to create one first.'}, status=400)

    student_profile = StudentProfile.objects.filter(user=request.user).first()

    if not student_profile:
        return JsonResponse({'error': 'This User does not have an Student Profile, please create one first.'}, status=400)

    if student_profile.favorite_tutors.filter(id=tutor.id).exists():
        student_profile.remove_favorite_tutor(tutor)
        is_favorite = False
        message = 'Tutor successfully removed from favorites.'
    else:
        student_profile.add_favorite_tutor(tutor)
        is_favorite = True
        message = 'Tutor added to favorites.'

    return JsonResponse({
        'message': message,
        'tutor_id': tutor.id,
        'is_favorite': is_favorite,
    })


@require_GET
def get_favorite_tutors_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to see your favorite tutors.'}, status=401)

    student_profile = StudentProfile.objects.filter(user=request.user).first()
    if not student_profile:
        return JsonResponse({'error': 'This User does not have an Student Profile, please create one first.'}, status=400)

    favorites = student_profile.get_favorite_tutors().order_by('id')
    data = []

    for tutor in favorites:
        tutor_profile = TutorProfile.objects.filter(user=tutor).first()
        data.append({
            'id': tutor.id,
            'first_name': tutor.first_name,
            'last_name': tutor.last_name,
            'email': tutor.email,
            'bio': tutor_profile.bio if tutor_profile else '',
            'average_rating': tutor_profile.display_tutor_rating,
        })

    return JsonResponse({'favorite_tutors': data})


MAX_STUDENT_COURSES = 10

def home_for(user):
    """Name of the home page for this user. 'Decide later' users count as student."""
    return 'tutor_home' if user.has_role('tutor') else 'student_home'

def register_page(request):
    if request.user.is_authenticated:
        return redirect(home_for(request.user))

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=data['email'],
                        password=data['password1'],
                        first_name=data['first_name'],
                        last_name=data['last_name'],
                        role=data['role'],
                    )
            except IntegrityError:
                form.add_error('email', 'An account with this email already exists.')
            else:
                auth_login(request, user)
                messages.success(request, 'Your account has been created.')
                return redirect('personalise')
    else:
        form = RegisterForm()

    return render(request, 'register.html', {
        'form': form,
        'site_name': 'tUtoR',
        'campus': 'University of Regina',
    })


@login_required
def personalise(request):
    user = request.user

    if user.has_role('tutor'):
        profile, _ = TutorProfile.objects.get_or_create(user=user)
        saved_courses = profile.courses_passed
        max_courses = None
    else:  # students, and "decide later" users, are treated as students
        profile, _ = StudentProfile.objects.get_or_create(user=user)
        saved_courses = profile.courses
        max_courses = MAX_STUDENT_COURSES

    selected_ids = list(saved_courses.values_list('pk', flat=True))

    if request.method == 'POST':
        if 'skip' in request.POST:
            return redirect(home_for(request.user))   

        form = CoursePickForm(request.POST, max_courses=max_courses)
        if form.is_valid():
            saved_courses.set(form.cleaned_data['courses'])
            return redirect(home_for(request.user))

        for error in form.errors.get('courses', []):
            messages.error(request, error)
        selected_ids = [int(v) for v in request.POST.getlist('courses') if v.isdigit()]

    return render(request, 'personalise.html', {
        'site_name': 'tUtoR',
        'campus': 'University of Regina',
        'is_tutor': user.has_role('tutor'),
        'max_courses': max_courses,
        'courses': list(
            Course.objects.order_by('course_code')
            .values('id', 'course_code', 'course_name', 'course_faculty')
        ),
        'selected_ids': selected_ids,
    })


def login_page(request):
    if request.user.is_authenticated:
        return redirect(home_for(request.user))

    next_url = request.POST.get('next') or request.GET.get('next') or ''
    context = {'site_name': 'tUtoR', 'campus': 'University of Regina', 'email': '', 'error': ''}

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        user = authenticate(request, username=email, password=password)

        if user is not None:
            auth_login(request, user)
            safe = url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure())
            return redirect(next_url if safe else home_for(request.user))   

        context['email'] = email
        context['error'] = 'Invalid email address or password.'
        return render(request, 'login.html', context, status=400)

    return render(request, 'login.html', context)

def _format_slot_for_student(window):
    """Add readable labels to one open window for the student home template.

    `window` comes from get_tutor_available_slots(): it is the part of a slot
    that is still free after bookings, with ISO start_time and end_time.
    """
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from django.utils.formats import date_format

    from bookings.models import Available_Slots
    
    data = dict(window)
    start = timezone.localtime(parse_datetime(window['start_time']))
    end = timezone.localtime(parse_datetime(window['end_time']))

    data['when_label'] = (
        f"{date_format(start, 'D M j, Y · g:i A')} – {date_format(end, 'g:i A')}"
    )
    data['location_label'] = dict(Available_Slots.LocationType.choices).get(
        window['location_type'],        
        window['location_type'],
    )
    return data


def _tutors_for_student(student_profile):
    """Build tutor list for the student home using existing booking services."""
    from bookings.services import get_tutor_available_slots, get_user_details

    tutor_profiles = TutorProfile.objects.select_related('user').prefetch_related(
        'courses_passed',
    )

    # Prefer tutors who teach at least one of the student's courses.
    if student_profile is not None:
        student_courses = student_profile.courses.all()
        if student_courses.exists():
            matched = tutor_profiles.filter(
                courses_passed__in=student_courses,
            ).distinct()
            if matched.exists():
                tutor_profiles = matched

    favorite_ids = set()
    if student_profile is not None:
        favorite_ids = set(
            student_profile.favorite_tutors.values_list('id', flat=True)
        )

    tutors = []
    for tutor_profile in tutor_profiles.order_by('user__first_name', 'user__last_name', 'user__id'):
        try:
            details = get_user_details(tutor_profile.user, User.Role.TUTOR)
        except ValueError:
            continue

        # Free windows only: a slot that is partly booked shows what is left.
        details['available_slots'] = [
            _format_slot_for_student(window)
            for window in get_tutor_available_slots(tutor_profile.user)

        ]
        details['is_favorite'] = tutor_profile.user_id in favorite_ids
        tutors.append(details)
    return tutors


#Home page/dashboard basic controllers set up for redirection from signup and login
def _student_home_bookings(dashboard):
    """Confirmed bookings shown on the student home booking list."""
    from django.utils import timezone
    from django.utils.formats import date_format
    from django.urls import reverse

    from bookings.models import Available_Slots

    bookings = []
    for booking in dashboard['booked_sessions']:
        start = booking.start_time
        end = booking.end_time
        if booking.time_slot_id is not None:
            if start is None:
                start = booking.time_slot.start_time
            if end is None:
                end = booking.time_slot.end_time

        start_label = ''
        if start is not None:
            start_label = date_format(
                timezone.localtime(start),
                'D M j, Y · g:i A',
            )

        location_label = ''
        if booking.location_type:
            location_label = dict(Available_Slots.LocationType.choices).get(
                booking.location_type,
                booking.location_type,
            )

        bookings.append({
            'id': booking.id,
            'tutor': booking.tutor,
            'course': str(booking.course) if booking.course else '',
            'session_price': str(booking.session_price),
            'start_label': start_label,
            'location_label': location_label,
            'cancel_url': reverse('cancel_booking', args=[booking.id]),
        })
    return bookings


def _student_home_overview(user, profile, courses):
    """Summary counts and booking list for the student overview home."""
    dashboard = get_student_dashboard(user)
    bookings = _student_home_bookings(dashboard)
    course_list = list(courses) if courses is not None else []
    favorite_count = 0
    if profile is not None:
        favorite_count = profile.favorite_tutors.count()

    return {
        'courses': course_list,
        'course_count': len(course_list),
        'bookings': bookings,
        'booked_count': len(bookings),
        'open_request_count': dashboard['open_requests'].count(),
        'favorite_count': favorite_count,
    }


@login_required
def student_home(request):
    if request.user.has_role('tutor'):
        return redirect('tutor_home')
    profile = StudentProfile.objects.filter(user=request.user).first()
    courses = profile.courses.order_by('course_code') if profile else []
    tutors = _tutors_for_student(profile)
    context = {
        'site_name': 'tUtoR',
        'campus': 'University of Regina',
        'tutors': tutors,
    }
    context.update(_student_home_overview(request.user, profile, courses))
    return render(request, 'student_home.html', context)


def _tutor_home_overview(user):
    """Summary data for the tutor overview page (not the sessions setup page)."""
    from django.utils import timezone
    from django.utils.formats import date_format

    from bookings.models import Available_Slots
    from bookings.rating_pages import count_sessions_to_rate

    profile = TutorProfile.objects.filter(user=user).first()
    courses = (
        list(profile.courses_passed.order_by('course_code'))
        if profile is not None
        else []
    )
    dashboard = get_tutor_dashboard(user)
    now = timezone.now()

    upcoming_slots = []
    for slot in dashboard['schedule']:
        if slot.status != Available_Slots.Status.AVAILABLE:
            continue
        if slot.start_time <= now:
            continue
        start = timezone.localtime(slot.start_time)
        end = timezone.localtime(slot.end_time)
        upcoming_slots.append({
            'id': slot.id,
            'when_label': (
                f"{date_format(start, 'D M j, Y · g:i A')} – "
                f"{date_format(end, 'g:i A')}"
            ),
            'location_label': dict(Available_Slots.LocationType.choices).get(
                slot.location_type,
                slot.location_type,
            ),
            'price_per_hour': str(slot.price_per_hour),
        })

    from django.urls import reverse

    recent_bookings = []
    for booking in dashboard['booked_sessions'][:5]:
        start_label = ''
        if booking.start_time is not None:
            start_label = date_format(
                timezone.localtime(booking.start_time),
                'D M j, Y · g:i A',
            )
        recent_bookings.append({
            'id': booking.id,
            'student': booking.student,
            'course': str(booking.course) if booking.course else '',
            'session_price': str(booking.session_price),
            'start_time': booking.start_time,
            'start_label': start_label,
            'cancel_url': reverse('cancel_booking', args=[booking.id]),
        })

    return {
        'courses': courses,
        'course_count': len(courses),
        'open_slot_count': len(upcoming_slots),
        'booked_count': dashboard['booked_sessions'].count(),
        'interest_count': dashboard['open_requests'].count(),
        'to_rate_count': count_sessions_to_rate(user),
        'upcoming_slots': upcoming_slots[:4],
        'recent_bookings': recent_bookings,
    }


@login_required
def tutor_home(request):
    """Tutor overview dashboard. Session setup lives on /tutor/sessions/."""
    if not request.user.has_role('tutor'):
        return redirect('student_home')

    context = {
        'site_name': 'tUtoR',
        'campus': 'University of Regina',
    }
    context.update(_tutor_home_overview(request.user))

    from bookings.request_pages import build_tutor_request_cards
    # Short preview on home; full list lives on /tutor/requests/.
    context['request_cards'] = build_tutor_request_cards(request.user, limit=4)

    return render(request, 'tutor_home.html', context)

@require_GET
def get_tutor_dashboard_view(request):
    error_response = check_role_access(
        request,
        User.Role.TUTOR,
    )

    if error_response is not None:
        return error_response

    dashboard = get_tutor_dashboard(request.user)
    data = serialize_tutor_dashboard(dashboard)

    return JsonResponse(data)

#     get My Profile()
#     update Student Profil()
#     update Tutor Profil()
#     Switch Role()

# Tutor Controller
#     get Tutor Profile
#     update Tutor Profile
#     get Tutor Dashboard
