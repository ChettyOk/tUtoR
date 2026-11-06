from django.contrib import admin

from .models import Course, StudentProfile, TutorProfile, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'role', 'date_joined')
    list_filter = ('role',)
    search_fields = ('email', 'first_name', 'last_name')
    readonly_fields = ('password', 'last_login', 'date_joined')
    exclude = ('groups', 'user_permissions')


admin.site.register(Course)
admin.site.register(StudentProfile)
admin.site.register(TutorProfile)