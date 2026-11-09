from django.urls import path
from . import views
from accounts import views as account_views

urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('requests/create/', views.create_session_request_view, name='create_request'),
    path('requests/', views.get_session_request_view, name='incoming_requests'),
    path('requests/<int:booking_id>/accept/', views.accept_session_request_view, name='accept_request'),
    path('requests/<int:booking_id>/decline/', views.decline_session_request_view, name='decline_request'),
    path('bookings/<int:booking_id>/rate/', views.submit_rating_view, name='submit_rating'),
    path('tutors/<int:user_id>/ratings/', views.get_ratings_view, {'rated_role': 'tutor'}, name='tutor_ratings'),
    path('students/<int:user_id>/ratings/', views.get_ratings_view, {'rated_role': 'student'}, name='student_ratings'),
    path('tutors/<int:user_id>/', views.get_user_details_view, {'role': 'tutor'}, name='tutor_details'),
    path('students/<int:user_id>/', views.get_user_details_view, {'role': 'student'}, name='student_details'),    path('tutors/<int:tutor_id>/slots/', views.get_tutor_slots_view, name='tutor_slots'),
    path('favorites/', account_views.get_favorite_tutors_view, name='favorite_tutors'),
    path('favorites/<int:tutor_id>/toggle/', account_views.favorite_tutor_view, name='toggle_favorite_tutor'),
    path('bookings/', views.get_bookings, name='my_bookings'),
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking_view, name='cancel_booking'),
    path('tutor/slots/', views.get_tutor_schedule_view, name='tutor_schedule',),
    path('tutor/slots/create/', views.create_slot_view, name='create_slot',),
]