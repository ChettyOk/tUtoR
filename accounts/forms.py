from django import forms

from .models import User, StudentProfile, TutorProfile


class AccountProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone']

class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = ['major', 'semester', 'courses']

    def clean_semester(self):
        semester = self.cleaned_data['semester']

        if semester < 1:
            raise forms.ValidationError(
                'Semester must be at least 1.',
            )

        return semester

class TutorProfileForm(forms.ModelForm):
    class Meta:
        model = TutorProfile
        fields = ['bio', 'courses_passed']
