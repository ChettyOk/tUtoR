from django.contrib import admin

from .models import Course, User, StudentProfile
# Register your models here.

admin.site.register(Course)
admin.site.register(User)
admin.site.register(StudentProfile)
