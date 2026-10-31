"""
URL configuration for tUtoR project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.urls import path
from django.urls import include, path, reverse_lazy

from accounts.views import (
    login,
    logout,
)
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('bookings.urls')),
    path('', views.landing, name='landing'),
    path('login/', views.login, name='login'),
    path('logout/', logout, name='logout'),
    path('register/', views.register, name='register'),
    path('password-reset/', views.forgot_password, name='request_forgotten_password'),
    path(
    'password-reset/confirm/<uidb64>/<token>/',
    auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ),
    name='password_reset_confirm',
),
path(
    'password-reset/complete/',
    auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ),
    name='password_reset_complete',
),
    
]



