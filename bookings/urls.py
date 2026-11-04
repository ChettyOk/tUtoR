from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('bookings/<int:booking_id>/rate/', views.submit_rating_view, name='submit_rating'),
    path('tutors/<int:tutor_id>/ratings/', views.get_tutor_ratings_view, name='tutor_ratings'),
]