from django.urls import path
from . import views
from accounts import views as account_views


urlpatterns = [
    path('search/', views.filter_courses, name='search'),
    path('tutors/<int:tutor_id>/', views.get_tutor_details_view, name='tutor_details'),
    path('tutors/<int:tutor_id>/slots/', views.get_tutor_slots_view, name='tutor_slots'),
    path('search/', views.filter_courses, name='search'),
    path('favorites/', account_views.get_favorite_tutors_view, name='favorite_tutors'),
    path('favorites/<int:tutor_id>/toggle/', account_views.favorite_tutor_view, name='toggle_favorite_tutor'),
]