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
from bookings.pricing import calc_price_suggestion, custom_pricing

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
#     get My Profile()
#     update Student Profil()
#     update Tutor Profil()
#     Switch Role()


# Tutor Controller

@require_http_methods(["GET"])
def get_tutor_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    profile = TutorProfile.objects.filter(user=request.user).first()

    if profile is None:
        return JsonResponse(
            {"error": "Tutor profile not found."},
            status=404,
        )

    standard_price = calc_price_suggestion(request.user)
    current_price = profile.custom_price or standard_price

    return JsonResponse({
        "id": profile.id,
        "bio": profile.bio,
        "courses_passed": list(
            profile.courses_passed.values_list("id", flat=True)
        ),
        "average_rating": (
            str(profile.average_rating)
            if profile.average_rating is not None
            else None
        ),
        "price": str(current_price),
        "standard_price": str(standard_price),
        "uses_custom_price": profile.custom_price is not None,
    })


@require_http_methods(["POST", "PUT"])
def update_tutor_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    profile, _ = TutorProfile.objects.get_or_create(
        user=request.user
    )

    bio = request.POST.get("bio")
    price = request.POST.get("custom_price")

    if bio is not None:
        profile.bio = bio

    if price == "":
        profile.custom_price = None
    elif price is not None:
        try:
            profile.custom_price = custom_pricing(price)
        except ValueError as error:
            return JsonResponse(
                {"errors": {"custom_price": [str(error)]}},
                status=400,
            )

    profile.save()

    return JsonResponse({
        "message": "Tutor profile updated.",
        "price": str(
            profile.custom_price
            or calc_price_suggestion(request.user)
        ),
        "uses_custom_price": profile.custom_price is not None,
    })


#     get Tutor Dashboard
