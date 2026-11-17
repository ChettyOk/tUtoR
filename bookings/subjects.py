import logging
from typing import Any

from bookings.interfaces import BookingEvent, BookingObserver, BookingSubject


logger = logging.getLogger(__name__)


class BookingEventManager(BookingSubject):
    """Central subject for booking lifecycle events."""

    def __init__(self) -> None:
        self._observers: list[BookingObserver] = []

    def attach(self, observer: BookingObserver) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: BookingObserver) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, event: BookingEvent, booking: Any) -> None:
        for observer in tuple(self._observers):
            try:
                observer.update(event, booking)
            except Exception:
                logger.exception(
                    "Booking observer failed for event %s and booking %s",
                    event.value,
                    getattr(booking, "id", None),
                )


booking_event_manager = BookingEventManager()