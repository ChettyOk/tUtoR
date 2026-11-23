""" data for the tutor's "Past sessions" page (rate your students)."""
from django.utils import timezone
from django.utils.formats import date_format

from .models import Booking, Rating

MAX_COMMENT_LENGTH = 500


def _person_name(user):
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def _session_end(booking):
    if booking.end_time is not None:
        return booking.end_time
    if booking.time_slot_id:
        return booking.time_slot.end_time
    return None


def _session_start(booking):
    if booking.start_time is not None:
        return booking.start_time
    if booking.time_slot_id:
        return booking.time_slot.start_time
    return None


def build_past_sessions(tutor, now=None):
    """Sessions that have ended, split into 'to rate' and 'rated'.

    A confirmed booking whose end time has passed counts as "to rate": the
    page marks it completed (POST /bookings/<id>/complete/) and then saves the
    rating (POST /bookings/<id>/rate/) in one go, so the tutor never has to
    think about the completed status.
    """
    now = now or timezone.now()
    bookings = (
        Booking.objects
        .filter(tutor=tutor, status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED])
        .select_related('student', 'course', 'time_slot')
    )
    ratings = {
        r.booking_id: r
        for r in Rating.objects.filter(
            booking__in=bookings, rated_role=Rating.RatedRole.STUDENT,
        )
    }

    cards = []
    for booking in bookings:
        end = _session_end(booking)
        start = _session_start(booking)
        ended = booking.status == Booking.Status.COMPLETED or (end is not None and end <= now)
        if not ended:
            continue
        rating = ratings.get(booking.pk)
        when = ''
        if start is not None:
            when = date_format(timezone.localtime(start), 'D M j, Y · g:i A')
        cards.append({
            'id': booking.pk,
            'student_name': _person_name(booking.student),
            'course': str(booking.course) if booking.course else '',
            'when_label': when,
            'sort_key': start or end,
            'session_price': str(booking.session_price),
            'needs_complete': booking.status == Booking.Status.CONFIRMED,
            'rated': rating is not None,
            'stars': rating.rating_stars if rating else None,
            'comment': rating.rating_comment if rating else '',
        })

    cards.sort(key=lambda c: c['sort_key'] or now, reverse=True)
    return {
        'to_rate': [c for c in cards if not c['rated']],
        'rated': [c for c in cards if c['rated']],
    }


def count_sessions_to_rate(tutor):
    return len(build_past_sessions(tutor)['to_rate'])