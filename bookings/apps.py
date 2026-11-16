from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = 'bookings'

    def ready(self):
        from bookings.observers import (
            CancellationMailObserver,
            ConfirmationMailObserver,
            ReminderMailObserver,
        )
        from bookings.subjects import booking_event_manager

        booking_event_manager.attach(CancellationMailObserver())
        booking_event_manager.attach(ConfirmationMailObserver())
        booking_event_manager.attach(ReminderMailObserver())
