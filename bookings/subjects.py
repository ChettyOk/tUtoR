from typing import Any

from bookings.interfaces import BookingEvent, BookingObserver, BookingSubject


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
            observer.update(event, booking)


booking_event_manager = BookingEventManager()