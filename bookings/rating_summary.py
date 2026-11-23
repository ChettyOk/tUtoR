"""Rating numbers shared by cards, home pages and the "My ratings" pages.

Every number here is calculated from the Rating rows, so cards, the badge and
the My ratings pages always agree with each other.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count
from django.utils import timezone
from django.utils.formats import date_format

from .models import Rating


def _one_decimal(value):
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _owner_field(rated_role):
    """Rating.tutor holds the tutor, Rating.student the student, for either role."""
    return 'tutor_id' if rated_role == Rating.RatedRole.TUTOR else 'student_id'


def stats_for_users(user_ids, rated_role):
    """{user_id: {'avg': '4.5' or None, 'count': n}} for many users in one query."""
    field = _owner_field(rated_role)
    rows = (
        Rating.objects
        .filter(rated_role=rated_role, **{f'{field}__in': list(user_ids)})
        .values(field)
        .annotate(avg=Avg('rating_stars'), n=Count('id'))
    )
    return {
        row[field]: {'avg': _one_decimal(row['avg']), 'count': row['n']}
        for row in rows
    }


def stats_for_user(user, rated_role):
    empty = {'avg': None, 'count': 0}
    return stats_for_users([user.pk], rated_role).get(user.pk, empty)


def _when_label(booking):
    start = booking.start_time
    if start is None and booking.time_slot_id:
        start = booking.time_slot.start_time
    if start is None:
        return ''
    return date_format(timezone.localtime(start), 'D M j, Y · g:i A')


def build_received_ratings(user, rated_role):
    """Average, 5-to-1 breakdown and reviews that `user` received in `rated_role`.

    Names of the people who rated are left out on purpose, so they can be honest.
    """
    field = _owner_field(rated_role).replace('_id', '')
    received = (
        Rating.objects
        .filter(rated_role=rated_role, **{field: user})
        .select_related('booking', 'booking__course', 'booking__time_slot')
        .order_by('-rating_created_time', '-pk')
    )
    total = received.count()
    average = received.aggregate(avg=Avg('rating_stars'))['avg']

    counts = {n: 0 for n in range(1, 6)}
    reviews = []
    for r in received:
        counts[r.rating_stars] += 1
        reviews.append({
            'stars': r.rating_stars,
            'comment': r.rating_comment,
            'course': str(r.booking.course) if r.booking.course else '',
            'when_label': _when_label(r.booking),
        })

    return {
        'total': total,
        'average': _one_decimal(average),
        'average_whole': int(round(average)) if average is not None else 0,
        'breakdown': [
            {
                'stars': n,
                'count': counts[n],
                'percent': round(100 * counts[n] / total) if total else 0,
            }
            for n in range(5, 0, -1)
        ],
        'reviews': reviews,
    }