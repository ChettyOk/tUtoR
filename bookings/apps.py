from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = 'bookings'

    def ready(self):
        from bookings.observers import (
            CancellationMailObserver,
            ConfirmationMailObserver,
            ReminderMailObserver,
        )
        from interactions.observers import (
            TutoringRequestInterestNotificationObserver,
            WebsiteNotificationObserver,
        )
        from bookings.subjects import (
            booking_event_manager,
            tutoring_request_event_manager,
        )

        booking_event_manager.attach(CancellationMailObserver())
        booking_event_manager.attach(ConfirmationMailObserver())
        booking_event_manager.attach(ReminderMailObserver())
        booking_event_manager.attach(WebsiteNotificationObserver())
        tutoring_request_event_manager.attach(
            TutoringRequestInterestNotificationObserver()
        )
