from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('requests/create/', views.create_session_request_view, name='create_request'),
    path('requests/', views.get_session_request_view, name='incoming_requests'),
    path('requests/<int:booking_id>/accept/', views.accept_session_request_view, name='accept_request'),
    path('requests/<int:booking_id>/decline/', views.decline_session_request_view, name='decline_request'),
]