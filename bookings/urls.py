from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('bookings/', views.get_bookings, name='my_bookings'),
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking_view, name='cancel_booking'),
]