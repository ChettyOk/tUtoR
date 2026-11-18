import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.views import get_my_profile, switch_role as api_switch_role

from django.http import JsonResponse


ACCOUNT_SECTIONS = ("personal", "password", "role")
ACCOUNT_TEMPLATE = "profile/account.html"


def _account_section(value, default="personal"):
    if value in ACCOUNT_SECTIONS:
        return value
    return default


def register(request):
    """Show the sign-up page. POST still creates the account."""
    if request.method == "POST":
        from accounts.views import register as create_account

        return create_account(request)

    return render(request, "register.html", {
        "site_name": "tUtoR",
        "campus": "University of Regina",
    })


def forgot_password(request):
    """Show the reset request page. POST uses the existing reset function."""
    context = {
        "site_name": "tUtoR",
        "campus": "University of Regina",
        "email": "",
        "email_error": "",
    }
    if request.method != "POST":
        return render(request, "registration/password_reset_form.html", context)

    from accounts.views import request_forgotten_password

    response = request_forgotten_password(request)
    context["email"] = request.POST.get("email", "").strip()
    if response.status_code == 200:
        return render(request, "registration/password_reset_done.html", context)

    context["email_error"] = _reset_email_error(response)
    return render(
        request,
        "registration/password_reset_form.html",
        context,
        status=response.status_code,
    )


def _reset_email_error(response):
    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError:
        return "Enter the email address for your account."

    errors = payload.get("errors", {}).get("email") or []
    if not errors:
        return "Enter the email address for your account."

    first = errors[0]
    if isinstance(first, dict):
        return first.get("message") or "Enter a valid email address."
    return str(first)


def login(request):
    """Placeholder for the student and tutor sign-in page."""
    return render(request, "login.html", {
        "site_name": "tUtoR",
    })



def _account_context(request, **extra):
    user = request.user
    context = {
        "site_name": "tUtoR",
        "campus": "University of Regina",
        "account": {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
        },
        "field_errors": {},
        "form_error": "",
        "success_message": "",
        "active_section": "personal",
    }
    context.update(extra)
    return context


def _field_errors_from_response(response):
    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError:
        return {}, "Something went wrong. Please try again."

    if "error" in payload:
        return {}, payload["error"]

    raw_errors = payload.get("errors") or {}
    field_errors = {}
    for field, entries in raw_errors.items():
        if not entries:
            continue
        first = entries[0]
        if isinstance(first, dict):
            field_errors[field] = first.get("message") or "This field is invalid."
        else:
            field_errors[field] = str(first)
    return field_errors, ""


@login_required
def account_profile(request):
    """Single account page with personal / password / role sections."""
    section = _account_section(
        request.POST.get("section") or request.GET.get("section"),
        default="personal",
    )
    context = _account_context(
        request,
        active_section=section,
        form=PasswordChangeForm(user=request.user),
    )

    if request.method != "POST":
        return render(request, ACCOUNT_TEMPLATE, context)

    # Personal-info saves only; other sections POST to their own URLs.
    response = get_my_profile(request)
    context["account"].update({
        "first_name": request.POST.get("first_name", "").strip(),
        "last_name": request.POST.get("last_name", "").strip(),
        "phone": request.POST.get("phone", "").strip(),
    })
    context["active_section"] = "personal"

    if response.status_code == 200:
        request.user.refresh_from_db()
        context = _account_context(
            request,
            active_section="personal",
            form=PasswordChangeForm(user=request.user),
            success_message="Your personal info was saved.",
        )
        return render(request, ACCOUNT_TEMPLATE, context)

    field_errors, form_error = _field_errors_from_response(response)
    context["field_errors"] = field_errors
    context["form_error"] = form_error
    return render(
        request,
        ACCOUNT_TEMPLATE,
        context,
        status=response.status_code,
    )


@login_required
def account_password(request):
    """Change-password POST target; GET opens the account page password section."""
    if request.method != "POST":
        return redirect(f"{reverse('account_profile')}?section=password")

    form = PasswordChangeForm(user=request.user, data=request.POST)
    context = _account_context(
        request,
        active_section="password",
        form=form,
    )
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        context["success_message"] = "Your password was changed."
        context["form"] = PasswordChangeForm(user=request.user)
        return render(request, ACCOUNT_TEMPLATE, context)

    return render(request, ACCOUNT_TEMPLATE, context, status=400)


@login_required
def account_role(request):
    """Role-switch POST target; GET opens the account page role section."""
    if request.method != "POST":
        return redirect(f"{reverse('account_profile')}?section=role")

    response = api_switch_role(request)
    selected_role = request.POST.get("role", "")
    context = _account_context(
        request,
        active_section="role",
        form=PasswordChangeForm(user=request.user),
    )

    if response.status_code == 200:
        request.user.refresh_from_db()
        context = _account_context(
            request,
            active_section="role",
            form=PasswordChangeForm(user=request.user),
            success_message="Your active role was updated.",
        )
        return render(request, ACCOUNT_TEMPLATE, context)

    field_errors, form_error = _field_errors_from_response(response)
    context["field_errors"] = field_errors
    context["form_error"] = form_error
    context["account"]["role"] = selected_role or context["account"]["role"]
    return render(
        request,
        ACCOUNT_TEMPLATE,
        context,
        status=response.status_code,
    )


def landing(request):
    """Public landing page. No accounts or bookings are read here."""
    return render(request, "landing.html", {
        "site_name": "tUtoR",
        "campus": "University of Regina",
        "problems": [
            {
                "title": "A posting gets covered",
                "text": "The next flyer hides the one that mattered. The student who passed the course never sees the request.",
            },
            {
                "title": "Anyone can pin a note",
                "text": "A noticeboard cannot show who actually passed the course, or which hours they can teach.",
            },
            {
                "title": "Contact is a scrap of paper",
                "text": "A name and a number sit in public. There is no booking, no shared time, and no record of the session.",
            },
        ],
        "steps": [
            {
                "number": "01",
                "title": "Say which side you are on",
                "text": "A student names the course they need. A tutor offers a course they have already passed.",
            },
            {
                "number": "02",
                "title": "Match on course and time",
                "text": "Faculty, course, and free hours narrow the list, so both people see the same opening.",
            },
            {
                "number": "03",
                "title": "Book the session",
                "text": "The slot is confirmed first. Contact details are shared after that, not pinned in a hallway.",
            },
        ],
    })


def custom_403(request, exception=None):
    return JsonResponse({'error': '403 Forbidden: You have no permission to access this.'}, status=403)


def custom_404(request, exception=None):
    return JsonResponse({'error': '404 Not Found: The page or resource you want to visit does not exist (yet).'}, status=404)

def custom_500(request):
    return JsonResponse({'error': '500 Internal Server Error: We made a mistake. The problem is on our end'}, status=500)