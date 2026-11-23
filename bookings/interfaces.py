from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class BookingEvent(Enum):
    """Events emitted during a booking's lifecycle."""

    REQUESTED = "requested"
    BOOKED = "booked"
    CANCELLED = "cancelled"
    REMINDER = "reminder"


class TutoringRequestEvent(Enum):
    """Events emitted during a tutoring request's lifecycle."""

    INTEREST_EXPRESSED = "interest_expressed"


# Descriptive aliases keep the event type easy to discover for callers.
BookingEventType = BookingEvent
EventType = BookingEvent


class BookingObserver(ABC):
    @abstractmethod
    def update(self, event: BookingEvent, booking: Any) -> None:
        """React to a booking event."""


class BookingSubject(ABC):
    @abstractmethod
    def attach(self, observer: BookingObserver) -> None:
        """Subscribe an observer."""

    @abstractmethod
    def detach(self, observer: BookingObserver) -> None:
        """Unsubscribe an observer."""

    @abstractmethod
    def notify(self, event: BookingEvent, booking: Any) -> None:
        """Notify all subscribed observers."""


class TutoringRequestObserver(ABC):
    @abstractmethod
    def update(self, event: TutoringRequestEvent, interest: Any) -> None:
        """React to a tutoring request event."""


class TutoringRequestSubject(ABC):
    @abstractmethod
    def attach(self, observer: TutoringRequestObserver) -> None:
        """Subscribe an observer."""

    @abstractmethod
    def detach(self, observer: TutoringRequestObserver) -> None:
        """Unsubscribe an observer."""

    @abstractmethod
    def notify(self, event: TutoringRequestEvent, interest: Any) -> None:
        """Notify all subscribed observers."""