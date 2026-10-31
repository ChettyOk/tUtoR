import json

from django.shortcuts import render

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
