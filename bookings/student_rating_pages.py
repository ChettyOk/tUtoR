"""data for the student's "Rate your tutors" and "My ratings" pages."""
from django.db.models import Avg
from django.utils import timezone
from django.utils.formats import date_format

from .models import Booking, Rating

MAX_COMMENT_LENGTH = 500


def _person_name(user):
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def _session_start(booking):
    if booking.start_time is not None:
        return booking.start_time
    if booking.time_slot_id:
        return booking.time_slot.start_time
    return None


def _session_end(booking):
    if booking.end_time is not None:
        return booking.end_time
    if booking.time_slot_id:
        return booking.time_slot.end_time
    return None


def _when_label(moment):
    if moment is None:
        return ''
    return date_format(timezone.localtime(moment), 'D M j, Y · g:i A')


def build_student_past_sessions(student, now=None):
    """Ended sessions split into 'to_rate' and 'rated' (the tutor is the one rated).

    A confirmed booking whose end time has passed is "to rate": the page marks
    it completed (POST /bookings/<id>/complete/) and then saves the rating
    (POST /bookings/<id>/rate/) in one go.
    """
    now = now or timezone.now()
    bookings = (
        Booking.objects
        .filter(student=student, status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED])
        .select_related('tutor', 'course', 'time_slot')
    )
    ratings = {
        r.booking_id: r
        for r in Rating.objects.filter(
            booking__in=bookings, rated_role=Rating.RatedRole.TUTOR,
        )
    }

    cards = []
    for booking in bookings:
        start = _session_start(booking)
        end = _session_end(booking)
        ended = booking.status == Booking.Status.COMPLETED or (end is not None and end <= now)
        if not ended:
            continue
        rating = ratings.get(booking.pk)
        cards.append({
            'id': booking.pk,
            'tutor_name': _person_name(booking.tutor),
            'course': str(booking.course) if booking.course else '',
            'when_label': _when_label(start),
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


def count_tutors_to_rate(student):
    return len(build_student_past_sessions(student)['to_rate'])


def build_my_ratings(student):
    """What tutors rated this student: average, 5-to-1 breakdown and reviews.

    Tutor names are left out on purpose, so tutors can be honest.
    """
    received = (
        Rating.objects
        .filter(student=student, rated_role=Rating.RatedRole.STUDENT)
        .select_related('booking', 'booking__course', 'booking__time_slot')
        .order_by('-rating_created_time', '-pk')
    )
    total = received.count()
    average = received.aggregate(avg=Avg('rating_stars'))['avg']

    counts = {n: 0 for n in range(1, 6)}
    reviews = []
    for r in received:
        counts[r.rating_stars] += 1
        booking = r.booking
        reviews.append({
            'stars': r.rating_stars,
            'comment': r.rating_comment,
            'course': str(booking.course) if booking.course else '',
            'when_label': _when_label(_session_start(booking)),
        })

    breakdown = [
        {
            'stars': n,
            'count': counts[n],
            'percent': round(100 * counts[n] / total) if total else 0,
        }
        for n in range(5, 0, -1)
    ]
    return {
        'total': total,
        'average': f"{average:.1f}" if average is not None else None,
        'average_whole': int(round(average)) if average is not None else 0,
        'breakdown': breakdown,
        'reviews': reviews,
    }