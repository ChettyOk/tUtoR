"""Data for the student "My requests" page.

Plain functions so the view stays small and the logic is easy to test.
"""
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.formats import date_format

from accounts.models import Course, User
from .models import TutoringRequest, TutoringRequestInterest
from .search import _format_window
from .services import (
    get_interested_tutors,
    get_student_tutoring_requests,
    get_visible_tutoring_requests,
    get_tutor_available_slots,
    get_user_details,
)

# Open requests first, then the history.
STATUS_ORDER = {
    TutoringRequest.Status.OPEN: 0,
    TutoringRequest.Status.FULFILLED: 1,
    TutoringRequest.Status.WITHDRAWN: 2,
    TutoringRequest.Status.EXPIRED: 3,
}
LOCATION_LABELS = dict(TutoringRequest.LocationType.choices)


def _interested_tutor_cards(tutoring_request):
    """One dict per interested tutor, with their open times to book."""
    cards = []
    for interest in get_interested_tutors(tutoring_request=tutoring_request):
        try:
            details = get_user_details(interest.tutor, User.Role.TUTOR)
        except ValueError:
            continue
        windows = [
            _format_window(raw)
            for raw in get_tutor_available_slots(interest.tutor)
        ]
        windows.sort(key=lambda w: w['start'])
        details['windows'] = windows
        details['lowest_price'] = (
            min(w['price_per_hour'] for w in windows) if windows else None
        )
        cards.append(details)
    return cards


def _booked_label(tutoring_request):
    """Text like 'Alice Lee · Thu Nov 26, 2026 · 5:00 PM' for a fulfilled request."""
    booking = tutoring_request.fulfilled_booking
    if booking is None:
        return ''
    start = booking.start_time
    if start is None and booking.time_slot_id:
        start = booking.time_slot.start_time
    name = f'{booking.tutor.first_name} {booking.tutor.last_name}'.strip()
    name = name or booking.tutor.email
    if start is None:
        return name
    return f"{name} · {date_format(timezone.localtime(start), 'D M j, Y · g:i A')}"


def build_request_cards(student):
    """All of a student's requests, ready for the template."""
    requests = list(
        get_student_tutoring_requests(student)
        .select_related('fulfilled_booking__tutor', 'fulfilled_booking__time_slot')
    )
    requests.sort(key=lambda r: STATUS_ORDER.get(r.status, 9))

    cards = []
    for r in requests:
        is_open = r.status == TutoringRequest.Status.OPEN
        cards.append({
            'id': r.pk,
            'course': r.course,
            'description': r.description,
            'location_label': LOCATION_LABELS.get(r.location_type, r.location_type),
            'status': r.status,
            'status_label': r.get_status_display(),
            'is_open': is_open,
            'created': timezone.localtime(r.created_at),
            'tutors': _interested_tutor_cards(r) if is_open else [],
            'booked_label': _booked_label(r),
        })
    return cards


def guess_course(text):
    """Best course for a search text like 'cs 480' or 'compilers', or None.

    Used to pre-select the course on the request form when the student
    arrives from an empty search.
    """
    text = (text or '').strip()
    if not text:
        return None

    squashed = text.replace(' ', '').lower()
    for course in Course.objects.order_by('course_code'):
        if course.course_code.replace(' ', '').lower() == squashed:
            return course

    starts = [
        c for c in Course.objects.order_by('course_code')
        if c.course_code.replace(' ', '').lower().startswith(squashed)
    ]
    if starts:
        return starts[0]

    return Course.objects.filter(course_name__icontains=text).order_by(
        'course_code').first()


def build_tutor_request_cards(tutor, limit=30):
    """Open requests for the tutor home page.

    Only the student's first name is shown. Requests for courses the tutor
    teaches come first, then newest first.
    """
    my_course_ids = set()
    profile = tutor.tutor_profile if hasattr(tutor, 'tutor_profile') else None
    if profile is not None:
        my_course_ids = set(profile.courses_passed.values_list('id', flat=True))

    requests = list(get_visible_tutoring_requests(tutor=tutor))
    joined_ids = set(
        TutoringRequestInterest.objects
        .filter(tutor=tutor, tutoring_request__in=requests)
        .values_list('tutoring_request_id', flat=True)
    )
    counts = {}
    for row in (
        TutoringRequestInterest.objects
        .filter(tutoring_request__in=requests)
        .values_list('tutoring_request_id', flat=True)
    ):
        counts[row] = counts.get(row, 0) + 1

    cards = []
    for r in requests:
        cards.append({
            'id': r.pk,
            'course': r.course,
            'student_name': (r.student.first_name or 'A student').strip(),
            'description': r.description,
            'location_label': LOCATION_LABELS.get(r.location_type, r.location_type),
            'asked_ago': timesince(r.created_at, timezone.now()).split(',')[0],
            'matches': r.course_id in my_course_ids,
            'joined': r.pk in joined_ids,
            'interest_count': counts.get(r.pk, 0),
        })

    # Stable sort: requests for your courses first, newest first inside each group.
    cards.sort(key=lambda c: not c['matches'])
    return cards[:limit]