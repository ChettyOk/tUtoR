from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.formats import date_format

from accounts.models import Course, TutorProfile, User
from .models import Available_Slots
from .pricing import MAX_PRICE, MIN_PRICE
from .services import get_tutor_available_slots, get_user_details

# Part of the day -> (first hour inclusive, last hour exclusive), local time.
DAY_PARTS = {
    'morning': (6, 12),
    'afternoon': (12, 17),
    'evening': (17, 24),
}
SORT_CHOICES = (
    ('soonest', 'Soonest time'),
    ('price', 'Lowest price'),
    ('rating', 'Highest rated'),
)
LOCATION_LABELS = dict(Available_Slots.LocationType.choices)


def clean_filters(params):
    """Turn request.GET into validated filters.

    Returns (filters, errors). A bad value never crashes the page: it is
    dropped and a readable message is added to errors (QLT-03.1).
    """
    errors = []
    filters = {
        'q': params.get('q', '').strip()[:100],
        'faculty': params.get('faculty', '').strip(),
        'location': params.get('location', '').strip(),
        'max_price': None,
        'date': None,
        'part': params.get('part', '').strip(),
        'sort': params.get('sort', 'soonest').strip(),
    }

    if filters['location'] not in LOCATION_LABELS:
        filters['location'] = ''

    if filters['part'] not in DAY_PARTS:
        filters['part'] = ''

    if filters['sort'] not in dict(SORT_CHOICES):
        filters['sort'] = 'soonest'

    raw_price = params.get('max_price', '').strip()
    if raw_price:
        try:
            price = Decimal(raw_price)
            if price < MIN_PRICE or price > MAX_PRICE:
                raise InvalidOperation
            filters['max_price'] = price
        except InvalidOperation:
            errors.append(
                f'Max price must be a number between ${MIN_PRICE} and ${MAX_PRICE}.'
            )

    raw_date = params.get('date', '').strip()
    if raw_date:
        parsed = None
        try:
            parsed = parse_date(raw_date)
        except ValueError:
            parsed = None
        if parsed is None:
            errors.append('Pick a valid date.')
        elif parsed < timezone.localdate():
            errors.append('That date has already passed.')
        else:
            filters['date'] = parsed

    return filters, errors


def _slot_matches(start, end, price, location, filters):
    """True if one open window satisfies the slot filters.

    start and end are timezone-aware datetimes.
    """
    start = timezone.localtime(start)
    end = timezone.localtime(end)

    if filters['location'] and location != filters['location']:
        return False

    if filters['max_price'] is not None and price > filters['max_price']:
        return False

    if filters['date'] is not None and start.date() != filters['date']:
        return False

    if filters['part']:
        first_hour, last_hour = DAY_PARTS[filters['part']]
        part_start = start.replace(hour=first_hour, minute=0, second=0, microsecond=0)
        if last_hour == 24:
            part_end = part_start.replace(hour=23, minute=59, second=59)
        else:
            part_end = start.replace(hour=last_hour, minute=0, second=0, microsecond=0)
        # The window must overlap the part of the day.
        if end <= part_start or start >= part_end:
            return False

    return True


def _format_window(window):
    start = timezone.localtime(parse_datetime(window['start_time']))
    end = timezone.localtime(parse_datetime(window['end_time']))
    return {
        'id': window['id'],
        'start': start,
        'price_per_hour': Decimal(window['price_per_hour']),
        'location_type': window['location_type'],
        'location_label': LOCATION_LABELS.get(
            window['location_type'], window['location_type']
        ),
        'when_label': (
            f"{date_format(start, 'D M j, Y · g:i A')} – {date_format(end, 'g:i A')}"
        ),
    }


def search_tutors(filters, viewer=None):
    """Return a list of tutor dicts (card data) matching the filters.

    A tutor is listed only if at least one open time matches the slot
    filters, so every card on the page can actually be booked.
    """
    profiles = TutorProfile.objects.select_related('user')

    if viewer is not None:
        profiles = profiles.exclude(user=viewer)

    if filters['faculty']:
        profiles = profiles.filter(
            courses_passed__course_faculty__iexact=filters['faculty']
        )

    q = filters['q']
    if q:
        profiles = profiles.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(courses_passed__course_code__icontains=q)
            | Q(courses_passed__course_name__icontains=q)
        )

    results = []
    for profile in profiles.distinct():
        try:
            details = get_user_details(profile.user, User.Role.TUTOR)
        except ValueError:
            continue

        windows = []
        for raw in get_tutor_available_slots(profile.user):
            if _slot_matches(
                parse_datetime(raw['start_time']),
                parse_datetime(raw['end_time']),
                Decimal(raw['price_per_hour']),
                raw['location_type'],
                filters,
            ):
                windows.append(_format_window(raw))

        if not windows:
            continue

        windows.sort(key=lambda w: w['start'])
        details['available_slots'] = windows
        details['lowest_price'] = min(w['price_per_hour'] for w in windows)
        details['first_start'] = windows[0]['start']
        details['rating_value'] = profile.average_rating
        results.append(details)

    sort = filters['sort']
    if sort == 'price':
        results.sort(key=lambda t: (t['lowest_price'], t['first_start']))
    elif sort == 'rating':
        # Unrated tutors go last.
        results.sort(key=lambda t: (
            t['rating_value'] is None,
            -(t['rating_value'] or 0),
            t['first_start'],
        ))
    else:
        results.sort(key=lambda t: t['first_start'])

    return results


def faculty_choices():
    """Faculties that at least one tutor has a passed course in."""
    return sorted(
        Course.objects.filter(tutor_profiles__isnull=False)
        .values_list('course_faculty', flat=True)
        .distinct()
    )