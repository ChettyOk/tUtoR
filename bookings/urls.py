from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('tutors/<int:tutor_id>/', views.get_tutor_details_view, name='tutor_details'),
    path('tutors/<int:tutor_id>/slots/', views.get_tutor_slots_view, name='tutor_slots'),
]