import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.views import get_my_profile


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
    """Personal info page backed by get_my_profile."""
    context = _account_context(request, active_section="personal")

    if request.method != "POST":
        return render(request, "profile/personal_info.html", context)

    response = get_my_profile(request)
    context["account"].update({
        "first_name": request.POST.get("first_name", "").strip(),
        "last_name": request.POST.get("last_name", "").strip(),
        "phone": request.POST.get("phone", "").strip(),
    })

    if response.status_code == 200:
        request.user.refresh_from_db()
        context = _account_context(
            request,
            active_section="personal",
            success_message="Your personal info was saved.",
        )
        return render(request, "profile/personal_info.html", context)

    field_errors, form_error = _field_errors_from_response(response)
    context["field_errors"] = field_errors
    context["form_error"] = form_error
    return render(
        request,
        "profile/personal_info.html",
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
