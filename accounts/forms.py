from django import forms
from django.contrib.auth.password_validation import validate_password
from .models import Course, User, StudentProfile, TutorProfile


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

class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=254)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(
        choices=[('', 'Decide later')] + User.Role.choices,
        required=False,
    )

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1:
            candidate = User(email=cleaned.get('email', ''),
                             first_name=cleaned.get('first_name', ''),
                             last_name=cleaned.get('last_name', ''))
            try:
                validate_password(password1, candidate)
            except forms.ValidationError as error:
                self.add_error('password1', error)
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'The two passwords do not match.')
        return cleaned


class CoursePickForm(forms.Form):
    courses = forms.ModelMultipleChoiceField(queryset=Course.objects.all(), required=False)

    def __init__(self, *args, max_courses=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_courses = max_courses

    def clean_courses(self):
        courses = self.cleaned_data['courses']
        if self.max_courses is not None and len(courses) > self.max_courses:
            raise forms.ValidationError(f'Please pick at most {self.max_courses} courses.')
        return courses