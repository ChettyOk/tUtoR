from django.shortcuts import render
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

from .models import User, StudentProfile, TutorProfile
from .forms import AccountProfileForm, StudentProfileForm, TutorProfileForm

# Create your views here.
# functions that interact with the user

# ==========================================
# VON MIR (DJANGO DEFAULTS)
# ==========================================

# ==========================================
# VON EUCH (AUS DEM PDF - CONTROLLER)
# ==========================================

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
            return _update_student_profile(user, request.POST)

        if profile_type == 'tutor':
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

# Tutor Controller
#     get Tutor Profile
#     update Tutor Profile
#     get Tutor Dashboard
