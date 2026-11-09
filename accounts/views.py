from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.db import IntegrityError, transaction
from django.utils.http import url_has_allowed_host_and_scheme

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.forms import PasswordResetForm
from django.db import transaction
from decimal import Decimal

from .models import Course, User, StudentProfile, TutorProfile
from .forms import (
    AccountProfileForm,
    CoursePickForm,
    RegisterForm,
    StudentProfileForm,
    TutorProfileForm,
)

from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Course, User, StudentProfile, TutorProfile
from accounts.constants import FACULTIES

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
            return _update_student_profile(user, request.POST)

        if profile_type == 'tutor':
            return _update_tutor_profile(request)

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

def _update_tutor_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=401,
        )

    profile = TutorProfile.objects.filter(
        user=request.user,
    ).first()

    if profile is None:
        profile = TutorProfile(user=request.user)

    form = TutorProfileForm(
        data=request.POST,
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

#Home page/dashboard basic controllers set up for redirection from signup and login
@login_required
def student_home(request):
    if request.user.has_role('tutor'):
        return redirect('tutor_home')
    profile = StudentProfile.objects.filter(user=request.user).first()
    courses = profile.courses.order_by('course_code') if profile else []
    return render(request, 'student_home.html', {
        'site_name': 'tUtoR', 'campus': 'University of Regina', 'courses': courses})


@login_required
def tutor_home(request):
    if not request.user.has_role('tutor'):
        return redirect('student_home')
    profile = TutorProfile.objects.filter(user=request.user).first()
    courses = profile.courses_passed.order_by('course_code') if profile else []
    return render(request, 'tutor_home.html', {
        'site_name': 'tUtoR', 'campus': 'University of Regina', 'courses': courses})

#     get My Profile()
#     update Student Profil()
#     update Tutor Profil()
#     Switch Role()

# Tutor Controller
#     get Tutor Profile
#     update Tutor Profile
#     get Tutor Dashboard
