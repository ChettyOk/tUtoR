from .models import Course, StudentProfile, TutorProfile, User
from django.urls import reverse
from django.db import IntegrityError, transaction
from django.core import mail
from django.test import override_settings
from urllib.parse import urlsplit

# user import
from django.test import SimpleTestCase, TestCase, RequestFactory
from accounts.models import User, UserManager, StudentProfile
from .forms import AccountProfileForm, StudentProfileForm, TutorProfileForm
import json
from .views import _update_tutor_profile, check_role_access
from django.contrib.auth.models import AnonymousUser


# tutor profile tests
from accounts.models import TutorProfile
from decimal import Decimal
from django.core.exceptions import ValidationError
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from bookings.models import Available_Slots, Booking, TutoringRequest, TutoringRequestInterest

#personalisation tests imports
from django.contrib.auth import get_user_model
from bookings.services import (
    get_tutor_dashboard,
    serialize_tutor_dashboard,
)

#imports for course load
from io import StringIO
from django.core.management import call_command
from .course_catalogue import parse_catalogue_lines, read_csv
from .models import Course


# courses tests
class test_course(TestCase):

    def test_course_code_validity(self):
        self.assertTrue(Course.check_course_code_spelling("CS 476"))
        self.assertTrue(Course.check_course_code_spelling("CS476"))
        self.assertTrue(Course.check_course_code_spelling("ENER 476"))
        self.assertTrue(Course.check_course_code_spelling("cs 476"))

        self.assertFalse(Course.check_course_code_spelling("xxx"))
        self.assertFalse(Course.check_course_code_spelling(""))
        self.assertFalse(Course.check_course_code_spelling("CS 47"))
        self.assertFalse(Course.check_course_code_spelling("MATHEMATICS 476"))
        self.assertFalse(Course.check_course_code_spelling("C 476"))

    def test_course_creation(self):  
        course = Course.create_course("CS 476", "Computer Science 476")  
        self.assertEqual(course.course_code, "CS 476")
        self.assertEqual(course.course_name, "Computer Science 476")
        self.assertEqual(course.course_faculty, "Science")
        self.assertTrue(Course.objects.filter(course_code='CS 476').exists())  

        # Test automatic faculty detection & space normalization
        course_auto = Course.create_course("MATH110", "Calculus I")
        self.assertEqual(course_auto.course_code, "MATH 110")
        self.assertEqual(course_auto.course_faculty, "Science")  
        
    def test_invalid_course_creation(self):
        with self.assertRaises(ValueError):
            Course.create_course("xxx", "Computer Science 476")

    def test_course_duplicate_prevention(self):
        created1 = Course.create_course("CS 476", "Computer Science 476")
        self.assertTrue(created1)
        with self.assertRaises(IntegrityError):
            Course.create_course("CS 476", "Computer Science 476")

# user tests
class user_email_validation_tests(SimpleTestCase):
    def test_accepts_valid_email_addresses(self):
        valid_emails = [
            "marie@example.com",
            "marie.hartig@example.ca",
            "marie+study@example.com",
        ]

        for email in valid_emails:
            with self.subTest(email=email):
                user = User(email=email)
                self.assertTrue(user.check_email())

    def test_rejects_invalid_email_addresses(self):
        invalid_emails = [
            "",
            "marie",
            "marie.example.com",
            "@example.com",
            "marie@",
            "marie example@example.com",
        ]

        for email in invalid_emails:
            with self.subTest(email=email):
                user = User(email=email)
                self.assertFalse(user.check_email())

class user_role_tests(SimpleTestCase):
    def test_new_user_has_no_selected_role(self):
        user = User(email="marie@example.com")

        self.assertEqual(user.role, "")
        self.assertFalse(user.has_role(User.Role.STUDENT))
        self.assertFalse(user.has_role(User.Role.TUTOR))
        self.assertFalse(user.has_role(""))

    def test_has_role_checks_the_active_role(self):
        user = User(
            email="marie@example.com",
            role=User.Role.STUDENT,
        )

        self.assertTrue(user.has_role(User.Role.STUDENT))
        self.assertFalse(user.has_role(User.Role.TUTOR))
        self.assertFalse(user.has_role("admin"))

    def test_switch_role_changes_the_active_role(self):
        user = User(email="marie@example.com")

        user.switch_role(User.Role.STUDENT)
        self.assertTrue(user.has_role(User.Role.STUDENT))

        user.switch_role(User.Role.TUTOR)
        self.assertTrue(user.has_role(User.Role.TUTOR))
        self.assertFalse(user.has_role(User.Role.STUDENT))

    def test_switch_role_rejects_invalid_roles(self):
        user = User(
            email="marie@example.com",
            role=User.Role.STUDENT,
        )

        for invalid_role in ["admin", "", None]:
            with self.subTest(role=invalid_role):
                with self.assertRaises(ValueError):
                    user.switch_role(invalid_role)

                self.assertEqual(user.role, User.Role.STUDENT)

    def test_switch_role_does_not_grant_admin_permissions(self):
        user = User(email="marie@example.com")

        user.switch_role(User.Role.TUTOR)

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

class user_email_normalization_tests(SimpleTestCase):
    def test_normalizes_email_case_and_outer_spaces(self):
        email = UserManager.normalize_email("  Marie@EXAMPLE.COM  ")

        self.assertEqual(email, "marie@example.com")

    def test_normalization_preserves_plus_addressing(self):
        email = UserManager.normalize_email("Marie+Study@Example.com")

        self.assertEqual(email, "marie+study@example.com")

    def test_create_user_rejects_whitespace_only_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="   ", password="TestPassword")

class UserDatabaseTests(TestCase):
    def test_create_user_saves_normalized_email_and_password(self):
        password = "LocalTestPassword-42"

        user = User.objects.create_user(
            email="  Marie@Example.com  ",
            password=password,
            first_name="Marie",
            last_name="Beispiel",
            phone="+49 170 1234567",
        )

        saved_user = User.objects.get(pk=user.pk)

        self.assertEqual(saved_user.email, "marie@example.com")
        self.assertEqual(saved_user.first_name, "Marie")
        self.assertEqual(saved_user.last_name, "Beispiel")
        self.assertEqual(saved_user.phone, "+49 170 1234567")
        self.assertNotEqual(saved_user.password, password)
        self.assertTrue(saved_user.check_password(password))
        self.assertFalse(saved_user.check_password("WrongPassword"))
        self.assertIsNotNone(saved_user.date_joined)
        self.assertIsNotNone(saved_user.updated_at)

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            email="marie@example.com",
            password="LocalTestPassword-42",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    email="marie@example.com",
                    password="AnotherTestPassword-42",
                )

        self.assertEqual(User.objects.count(), 1)

    def test_database_rejects_email_with_different_letter_case(self):
        User.objects.create_user(
            email="marie@example.com",
            password="LocalTestPassword-42",
        )

        duplicate = User(email="MARIE@EXAMPLE.COM")
        duplicate.set_password("AnotherTestPassword-42")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

        self.assertEqual(User.objects.count(), 1)

    def test_account_lookup_ignores_email_letter_case(self):
        user = User.objects.create_user(
            email="marie@example.com",
            password="LocalTestPassword-42",
        )

        found_user = User.objects.get_by_natural_key(
            "  MARIE@EXAMPLE.COM  "
        )

        self.assertEqual(found_user.pk, user.pk)

    def test_role_change_is_persisted(self):
        user = User.objects.create_user(
            email="marie@example.com",
            password="LocalTestPassword-42",
        )

        self.assertEqual(user.role, "")

        user.switch_role(User.Role.TUTOR)
        user.save()
        user.refresh_from_db()

        self.assertTrue(user.has_role(User.Role.TUTOR))
        self.assertFalse(user.has_role(User.Role.STUDENT))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

class test_Student_Profile(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="example_student@uregina.ca", password="67676969")
        self.profile = StudentProfile.objects.create(user=self.user, major="CS", semester=1)
        self.course1 = Course.create_course("CS 476", "Software Development Project")
        self.course2 = Course.create_course("ENER 120", "Energy")

    def test_add_and_get_enrolled_courses(self):
        self.profile.add_course(self.course1)
        self.profile.add_course(self.course2)
        enrolled = self.profile.get_enrolled_courses()
        self.assertEqual(enrolled.count(), 2)
        self.assertIn(self.course1, enrolled)

    def test_remove_course(self):
        self.profile.add_course(self.course1)
        self.profile.remove_course(self.course1)
        self.assertEqual(self.profile.get_enrolled_courses().count(), 0)

    def test_update_profile(self):
        self.profile.update_profile(major="ENER", semester=4)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.major, "ENER")
        self.assertEqual(self.profile.semester, 4)
        with self.assertRaises(ValueError):
            self.profile.update_profile(major="ENER", semester=0)
        with self.assertRaises(ValueError):
            self.profile.update_profile(major="ENER", semester=-1)

class SuperuserCreationTests(TestCase):
    def test_create_superuser_sets_admin_flags_and_normalizes_email(self):
        password = "LocalTestPassword-42"

        admin = User.objects.create_superuser(
            email="  Admin@Example.com  ",
            password=password,
        )

        saved_admin = User.objects.get(pk=admin.pk)

        self.assertEqual(saved_admin.email, "admin@example.com")
        self.assertTrue(saved_admin.is_staff)
        self.assertTrue(saved_admin.is_superuser)
        self.assertTrue(saved_admin.is_active)
        self.assertNotEqual(saved_admin.password, password)
        self.assertTrue(saved_admin.check_password(password))

    def test_superuser_has_no_student_or_tutor_role(self):
        admin = User.objects.create_superuser(
            email="admin@example.com",
            password="LocalTestPassword-42",
        )

        self.assertEqual(admin.role, "")
        self.assertFalse(admin.has_role(User.Role.STUDENT))
        self.assertFalse(admin.has_role(User.Role.TUTOR))

    def test_create_superuser_rejects_is_staff_false(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="LocalTestPassword-42",
                is_staff=False,
            )

        self.assertEqual(User.objects.count(), 0)

    def test_create_superuser_rejects_is_superuser_false(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="LocalTestPassword-42",
                is_superuser=False,
            )

        self.assertEqual(User.objects.count(), 0)

    def test_create_user_does_not_create_admin(self):
        user = User.objects.create_user(
            email="marie@example.com",
            password="LocalTestPassword-42",
        )

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_duplicate_superuser_email_is_rejected(self):
        User.objects.create_superuser(
            email="admin@example.com",
            password="LocalTestPassword-42",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_superuser(
                    email="ADMIN@example.com",
                    password="AnotherTestPassword-42",
                )

        self.assertEqual(User.objects.count(), 1)



class AuthenticationViewTests(TestCase):
    def setUp(self):
        self.password = "testpass123"
        self.user = User.objects.create_user(
            email="test@example.com",
            password=self.password,
        )

    def test_logout_clears_authenticated_session(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.old_password = "Original-Password-928!"
        self.user = User.objects.create_user(
            email="reset@example.com",
            password=self.old_password,
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_request_sends_email_and_reset_link_changes_password(self):
        response = self.client.post(
            reverse("request_forgotten_password"),
            {"email": self.user.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        email_body = mail.outbox[0].body
        reset_url = next(
            line for line in email_body.splitlines()
            if "/password-reset/confirm/" in line
        )
        reset_path = urlsplit(reset_url).path

        # The first visit validates the token and redirects to a clean URL.
        response = self.client.get(reset_path, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "registration/password_reset_confirm.html",
        )

        confirm_path = urlsplit(response.redirect_chain[-1][0]).path
        new_password = "Brand-New-Password-837!"

        response = self.client.post(
            confirm_path,
            {
                "new_password1": new_password,
                "new_password2": new_password,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "registration/password_reset_complete.html",
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.user.check_password(self.old_password))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_unknown_email_gets_same_response_without_sending_email(self):
        response = self.client.post(
            reverse("request_forgotten_password"),
            {"email": "unknown@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_reset_token_shows_invalid_link_message(self):
        response = self.client.get(
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": "invalid", "token": "invalid"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This password reset link is invalid or has expired.",
        )

#tutor profile tests
class TutorProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='tutor@example.com',
            password='TutorTestPassword123!',
        )

    def test_create_tutor_profile_with_bio(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            bio='I offer tutoring for computer science courses.',
        )

        profile.refresh_from_db()

        self.assertEqual(profile.user, self.user)
        self.assertEqual(
            profile.bio,
            'I offer tutoring for computer science courses.',
        )
        self.assertEqual(self.user.tutor_profile, profile)

    def test_bio_is_empty_by_default(self):
        profile = TutorProfile.objects.create(user=self.user)

        profile.refresh_from_db()

        self.assertEqual(profile.bio, '')
        self.assertEqual(self.user.tutor_profile, profile)
    def test_profile_can_have_multiple_passed_courses(self):
        profile = TutorProfile.objects.create(user=self.user)
        course_one = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )
        course_two = Course.create_course(
            'CS 202',
            'Data Structures',
        )

        profile.courses_passed.add(course_one, course_two)

        self.assertCountEqual(
            profile.courses_passed.all(),
            [course_one, course_two],
        )

    def test_course_can_belong_to_multiple_tutor_profiles(self):
        profile = TutorProfile.objects.create(user=self.user)
        other_user = User.objects.create_user(
            email='other-tutor@example.com',
            password='TutorTestPassword123!',
        )
        other_profile = TutorProfile.objects.create(user=other_user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )

        profile.courses_passed.add(course)
        other_profile.courses_passed.add(course)

        self.assertCountEqual(
            course.tutor_profiles.all(),
            [profile, other_profile],
        )

    def test_adding_same_course_does_not_duplicate_relation(self):
        profile = TutorProfile.objects.create(user=self.user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )

        profile.courses_passed.add(course)
        profile.courses_passed.add(course)

        self.assertEqual(profile.courses_passed.count(), 1)

    def test_removing_passed_course_keeps_course_record(self):
        profile = TutorProfile.objects.create(user=self.user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )
        profile.courses_passed.add(course)

        profile.courses_passed.remove(course)

        self.assertFalse(profile.courses_passed.exists())
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())
    def test_average_rating_is_none_by_default(self):
        profile = TutorProfile.objects.create(user=self.user)

        profile.refresh_from_db()

        self.assertIsNone(profile.average_rating)

    def test_average_rating_accepts_valid_values(self):
        profile = TutorProfile.objects.create(user=self.user)

        for rating in (
            Decimal('1.00'),
            Decimal('4.25'),
            Decimal('5.00'),
        ):
            with self.subTest(rating=rating):
                profile.average_rating = rating

                profile.full_clean()
                profile.save()
                profile.refresh_from_db()

                self.assertEqual(profile.average_rating, rating)

    def test_average_rating_rejects_values_outside_range(self):
        profile = TutorProfile.objects.create(user=self.user)

        for rating in (
            Decimal('0.99'),
            Decimal('5.01'),
        ):
            with self.subTest(rating=rating):
                profile.average_rating = rating

                with self.assertRaises(ValidationError) as context:
                    profile.full_clean()

                self.assertIn(
                    'average_rating',
                    context.exception.message_dict,
                )

    def test_user_cannot_have_multiple_tutor_profiles(self):
        profile = TutorProfile.objects.create(user=self.user)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TutorProfile.objects.create(user=self.user)

        self.assertEqual(
            TutorProfile.objects.filter(user=self.user).count(),
            1,
        )
        self.assertTrue(
            TutorProfile.objects.filter(pk=profile.pk).exists(),
        )

    def test_deleting_user_deletes_profile_but_keeps_course(self):
        profile = TutorProfile.objects.create(user=self.user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )
        profile.courses_passed.add(course)
        profile_id = profile.pk

        self.user.delete()

        self.assertFalse(
            TutorProfile.objects.filter(pk=profile_id).exists(),
        )
        self.assertTrue(
            Course.objects.filter(pk=course.pk).exists(),
        )
        self.assertFalse(course.tutor_profiles.exists())

    def test_deleting_profile_keeps_user_and_course(self):
        profile = TutorProfile.objects.create(user=self.user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )
        profile.courses_passed.add(course)
        profile_id = profile.pk

        profile.delete()

        self.assertFalse(
            TutorProfile.objects.filter(pk=profile_id).exists(),
        )
        self.assertTrue(
            User.objects.filter(pk=self.user.pk).exists(),
        )
        self.assertTrue(
            Course.objects.filter(pk=course.pk).exists(),
        )
        self.assertFalse(course.tutor_profiles.exists())

    def test_switching_role_keeps_tutor_profile_and_courses(self):
        self.user.switch_role(User.Role.TUTOR)
        self.user.save()

        profile = TutorProfile.objects.create(user=self.user)
        course = Course.create_course(
            'CS 101',
            'Introduction to Computer Science',
        )
        profile.courses_passed.add(course)

        self.user.switch_role(User.Role.STUDENT)
        self.user.save()
        self.user.refresh_from_db()

        self.assertEqual(self.user.role, User.Role.STUDENT)
        self.assertEqual(self.user.tutor_profile.pk, profile.pk)
        self.assertTrue(
            self.user.tutor_profile.courses_passed.filter(
                pk=course.pk,
            ).exists(),
        )

    def test_display_tutor_rating_without_rating(self):
        profile = TutorProfile.objects.create(user=self.user)

        self.assertEqual(
            profile.display_tutor_rating,
            "No rating yet",
        )

    def test_display_tutor_rating_with_rating(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            average_rating=Decimal("4.25"),
        )

        self.assertEqual(
            profile.display_tutor_rating,
            "4.25",
        )

    def test_display_tutor_rating_uses_two_decimal_places(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            average_rating=Decimal("4.5"),
        )

        self.assertEqual(
            profile.display_tutor_rating,
            "4.50",
        )

# profile controller tests
class AccountProfileFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='profile@example.com',
            password='ProfileTestPassword123!',
            first_name='Marie',
            last_name='Example',
            phone='123456',
        )

    def test_form_contains_only_editable_account_fields(self):
        form = AccountProfileForm(instance=self.user)

        self.assertEqual(
            list(form.fields),
            ['first_name', 'last_name', 'phone'],
        )

    def test_valid_form_updates_existing_user(self):
        form = AccountProfileForm(
            data={
                'first_name': 'Alex',
                'last_name': 'Updated',
                'phone': '+1 306 555 0123',
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_user = form.save()
        self.user.refresh_from_db()

        self.assertEqual(saved_user.pk, self.user.pk)
        self.assertEqual(self.user.first_name, 'Alex')
        self.assertEqual(self.user.last_name, 'Updated')
        self.assertEqual(self.user.phone, '+1 306 555 0123')
        self.assertEqual(self.user.email, 'profile@example.com')

    def test_phone_can_be_empty(self):
        form = AccountProfileForm(
            data={
                'first_name': 'Marie',
                'last_name': 'Example',
                'phone': '',
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_phone_exceeding_model_length_is_invalid(self):
        form = AccountProfileForm(
            data={
                'first_name': 'Marie',
                'last_name': 'Example',
                'phone': '1' * 31,
            },
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)


class ProfileControllerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='profile@example.com',
            password='ProfileTestPassword123!',
            first_name='Marie',
            last_name='Example',
            phone='123456',
            role=User.Role.STUDENT,
        )
        self.url = reverse('profile')

    def test_anonymous_user_cannot_get_profile(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)
        self.assertIn('error', response.json())

    def test_authenticated_user_gets_own_account_data(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'account': {
                    'id': self.user.pk,
                    'first_name': 'Marie',
                    'last_name': 'Example',
                    'email': 'profile@example.com',
                    'phone': '123456',
                    'role': User.Role.STUDENT,
                },
                'student_profile': None,
                'tutor_profile': None,
            },
        )

    def test_user_id_parameter_does_not_select_another_account(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='OtherTestPassword123!',
        )
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {'user_id': other_user.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['account']['id'],
            self.user.pk,
        )

    def test_profile_endpoint_rejects_put(self):
        self.client.force_login(self.user)

        response = self.client.put(self.url)

        self.assertEqual(response.status_code, 405)

    def test_valid_post_updates_own_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'first_name': 'Alex',
                'last_name': 'Updated',
                'phone': '+1 306 555 0123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Alex')
        self.assertEqual(self.user.last_name, 'Updated')
        self.assertEqual(self.user.phone, '+1 306 555 0123')

    def test_invalid_post_does_not_save_account_changes(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'first_name': 'Changed',
                'last_name': 'Updated',
                'phone': '1' * 31,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('phone', response.json()['errors'])

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Marie')
        self.assertEqual(self.user.last_name, 'Example')
        self.assertEqual(self.user.phone, '123456')

    def test_anonymous_user_cannot_update_account(self):
        response = self.client.post(
            self.url,
            {
                'first_name': 'Changed',
                'last_name': 'Updated',
                'phone': '',
            },
        )

        self.assertEqual(response.status_code, 401)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Marie')

    def test_post_ignores_other_user_and_protected_fields(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='OtherTestPassword123!',
            first_name='Other',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'first_name': 'Alex',
                'last_name': 'Updated',
                'phone': '',
                'user_id': other_user.pk,
                'email': 'changed@example.com',
                'role': User.Role.TUTOR,
                'is_staff': 'true',
                'is_superuser': 'true',
            },
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        other_user.refresh_from_db()

        self.assertEqual(self.user.first_name, 'Alex')
        self.assertEqual(self.user.email, 'profile@example.com')
        self.assertEqual(self.user.role, User.Role.STUDENT)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(other_user.first_name, 'Other')

class StudentProfileFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='student-profile@example.com',
            password='StudentTestPassword123!',
        )
        self.profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=1,
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )

    def test_form_contains_only_editable_student_fields(self):
        form = StudentProfileForm(instance=self.profile)

        self.assertEqual(
            list(form.fields),
            ['major', 'semester', 'courses'],
        )

    def test_valid_form_updates_profile_and_courses(self):
        form = StudentProfileForm(
            data={
                'major': 'ENER',
                'semester': '3',
                'courses': [str(self.course.pk)],
            },
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_profile = form.save()
        self.profile.refresh_from_db()

        self.assertEqual(saved_profile.pk, self.profile.pk)
        self.assertEqual(self.profile.major, 'ENER')
        self.assertEqual(self.profile.semester, 3)
        self.assertQuerySetEqual(
            self.profile.courses.all(),
            [self.course],
        )

    def test_invalid_major_is_rejected(self):
        form = StudentProfileForm(
            data={
                'major': 'NOT_A_MAJOR',
                'semester': '1',
                'courses': [],
            },
            instance=self.profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('major', form.errors)

    def test_invalid_semester_is_rejected(self):
        for semester in ('0', '-1', 'abc'):
            with self.subTest(semester=semester):
                form = StudentProfileForm(
                    data={
                        'major': 'CS',
                        'semester': semester,
                        'courses': [],
                    },
                    instance=self.profile,
                )

                self.assertFalse(form.is_valid())
                self.assertIn('semester', form.errors)

    def test_unknown_course_is_rejected(self):
        unknown_course_id = self.course.pk + 1

        form = StudentProfileForm(
            data={
                'major': 'CS',
                'semester': '1',
                'courses': [str(unknown_course_id)],
            },
            instance=self.profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('courses', form.errors)

    def test_empty_course_selection_removes_previous_courses(self):
        self.profile.courses.add(self.course)

        form = StudentProfileForm(
            data={
                'major': 'CS',
                'semester': '1',
                'courses': [],
            },
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertFalse(self.profile.courses.exists())
        self.assertTrue(
            Course.objects.filter(pk=self.course.pk).exists(),
        )

class StudentProfileControllerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='student-controller@example.com',
            password='StudentTestPassword123!',
            first_name='Marie',
            phone='123456',
            role=User.Role.STUDENT,

        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.url = reverse('profile')

    def test_valid_post_creates_student_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'CS',
                'semester': '2',
                'courses': [str(self.course.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(profile.major, 'CS')
        self.assertEqual(profile.semester, 2)
        self.assertTrue(
            profile.courses.filter(pk=self.course.pk).exists(),
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Marie')
        self.assertEqual(self.user.phone, '123456')

    def test_valid_post_updates_existing_profile(self):
        profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=1,
        )
        profile.courses.add(self.course)
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'ENER',
                'semester': '3',
                'courses': [],
            },
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.major, 'ENER')
        self.assertEqual(profile.semester, 3)
        self.assertFalse(profile.courses.exists())
        self.assertEqual(
            StudentProfile.objects.filter(user=self.user).count(),
            1,
        )

    def test_invalid_post_does_not_create_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'CS',
                'semester': '0',
                'courses': [],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('semester', response.json()['errors'])
        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )

    def test_invalid_post_preserves_existing_profile(self):
        profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=1,
        )
        profile.courses.add(self.course)
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'ENER',
                'semester': '0',
                'courses': [],
            },
        )

        self.assertEqual(response.status_code, 400)
        profile.refresh_from_db()
        self.assertEqual(profile.major, 'CS')
        self.assertEqual(profile.semester, 1)
        self.assertTrue(
            profile.courses.filter(pk=self.course.pk).exists(),
        )

    def test_anonymous_user_cannot_create_student_profile(self):
        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'CS',
                'semester': '1',
                'courses': [],
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(StudentProfile.objects.exists())

    def test_unknown_profile_type_does_not_change_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'unknown',
                'first_name': 'Changed',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Marie')

    def test_get_returns_student_profile_data(self):
        profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=2,
        )
        profile.courses.add(self.course)
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['student_profile'],
            {
                'major': 'CS',
                'semester': 2,
                'courses': [self.course.pk],
                'average_rating': None,
            },
        )

    def test_get_without_student_profile_does_not_create_one(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['student_profile'])
        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )

    def test_get_does_not_return_another_users_student_profile(self):
        other_user = User.objects.create_user(
            email='other-student@example.com',
            password='OtherStudentPassword123!',
        )
        StudentProfile.objects.create(
            user=other_user,
            major='ENER',
            semester=4,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {'user_id': other_user.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['account']['id'],
            self.user.pk,
        )
        self.assertIsNone(response.json()['student_profile'])


class RoleSwitchControllerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='role-switch@example.com',
            password='RoleSwitchPassword123!',
            role=User.Role.STUDENT,
        )
        self.url = reverse('switch_role')

    def test_authenticated_user_can_switch_between_roles(self):
        self.client.force_login(self.user)

        for role in (User.Role.TUTOR, User.Role.STUDENT):
            with self.subTest(role=role):
                response = self.client.post(
                    self.url,
                    {'role': role},
                )

                self.assertEqual(response.status_code, 200)
                self.user.refresh_from_db()
                self.assertEqual(self.user.role, role)
                self.assertEqual(response.json()['role'], role)

    def test_invalid_or_missing_role_is_rejected(self):
        self.client.force_login(self.user)

        for data in ({}, {'role': ''}, {'role': 'admin'}):
            with self.subTest(data=data):
                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertIn('role', response.json()['errors'])

                self.user.refresh_from_db()
                self.assertEqual(
                    self.user.role,
                    User.Role.STUDENT,
                )

    def test_anonymous_user_cannot_switch_role(self):
        response = self.client.post(
            self.url,
            {'role': User.Role.TUTOR},
        )

        self.assertEqual(response.status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.STUDENT)

    def test_get_does_not_switch_role(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {'role': User.Role.TUTOR},
        )

        self.assertEqual(response.status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.STUDENT)

    def test_role_switch_preserves_student_profile_and_courses(self):
        profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=2,
        )
        course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        profile.courses.add(course)
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {'role': User.Role.TUTOR},
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.user_id, self.user.pk)
        self.assertEqual(profile.major, 'CS')
        self.assertEqual(profile.semester, 2)
        self.assertTrue(
            profile.courses.filter(pk=course.pk).exists(),
        )

    def test_user_id_does_not_select_another_account(self):
        other_user = User.objects.create_user(
            email='other-role@example.com',
            password='OtherRolePassword123!',
            role=User.Role.STUDENT,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'role': User.Role.TUTOR,
                'user_id': other_user.pk,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        other_user.refresh_from_db()

        self.assertEqual(self.user.role, User.Role.TUTOR)
        self.assertEqual(other_user.role, User.Role.STUDENT)

class TutorProfileFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='tutor-form@example.com',
            password='TutorFormPassword123!',
        )
        self.profile = TutorProfile.objects.create(
            user=self.user,
            bio='Original bio.',
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )

    def test_form_contains_only_editable_tutor_fields(self):
        form = TutorProfileForm(instance=self.profile)

        self.assertEqual(
            list(form.fields),
            ['bio', 'courses_passed'],
        )

    def test_valid_form_updates_bio_and_passed_courses(self):
        form = TutorProfileForm(
            data={
                'bio': 'I offer tutoring for computer science courses.',
                'courses_passed': [str(self.course.pk)],
            },
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_profile = form.save()
        self.profile.refresh_from_db()

        self.assertEqual(saved_profile.pk, self.profile.pk)
        self.assertEqual(
            self.profile.bio,
            'I offer tutoring for computer science courses.',
        )
        self.assertTrue(
            self.profile.courses_passed.filter(
                pk=self.course.pk,
            ).exists(),
        )

    def test_unknown_course_is_rejected(self):
        form = TutorProfileForm(
            data={
                'bio': 'Updated bio.',
                'courses_passed': [str(self.course.pk + 1)],
            },
            instance=self.profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('courses_passed', form.errors)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, 'Original bio.')
        self.assertFalse(self.profile.courses_passed.exists())

    def test_empty_fields_clear_bio_and_course_relations(self):
        self.profile.courses_passed.add(self.course)

        form = TutorProfileForm(
            data={
                'bio': '',
                'courses_passed': [],
            },
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.bio, '')
        self.assertFalse(self.profile.courses_passed.exists())
        self.assertTrue(
            Course.objects.filter(pk=self.course.pk).exists(),
        )

    def test_form_does_not_change_owner_or_rating(self):
        other_user = User.objects.create_user(
            email='other-tutor-form@example.com',
            password='OtherTutorPassword123!',
        )

        form = TutorProfileForm(
            data={
                'bio': 'Updated bio.',
                'courses_passed': [],
                'user': str(other_user.pk),
                'average_rating': '5.00',
            },
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.user_id, self.user.pk)
        self.assertIsNone(self.profile.average_rating)

class TutorProfileUpdateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email='tutor-update@example.com',
            password='TutorUpdatePassword123!',
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )

    def submit(self, data):
        request = self.factory.post('/', data=data)
        request.user = self.user
        return _update_tutor_profile(request.user, request.POST)

    def test_valid_request_creates_profile(self):
        response = self.submit({
            'bio': 'I offer computer science tutoring.',
            'courses_passed': [str(self.course.pk)],
        })

        self.assertEqual(response.status_code, 200)

        profile = TutorProfile.objects.get(user=self.user)
        self.assertEqual(
            profile.bio,
            'I offer computer science tutoring.',
        )
        self.assertEqual(
            list(profile.courses_passed.all()),
            [self.course],
        )

    def test_valid_request_updates_existing_profile(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            bio='Original bio.',
        )

        response = self.submit({
            'bio': 'Updated bio.',
            'courses_passed': [str(self.course.pk)],
        })

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()

        self.assertEqual(profile.bio, 'Updated bio.')
        self.assertEqual(
            TutorProfile.objects.filter(user=self.user).count(),
            1,
        )
        self.assertTrue(
            profile.courses_passed.filter(
                pk=self.course.pk,
            ).exists(),
        )

    def test_invalid_request_does_not_create_profile(self):
        response = self.submit({
            'bio': 'Invalid request.',
            'courses_passed': ['not-a-course-id'],
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

        body = json.loads(response.content)
        self.assertIn('courses_passed', body['errors'])

    def test_invalid_request_preserves_existing_profile(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            bio='Original bio.',
        )
        profile.courses_passed.add(self.course)

        response = self.submit({
            'bio': 'Must not be saved.',
            'courses_passed': ['not-a-course-id'],
        })

        self.assertEqual(response.status_code, 400)
        profile.refresh_from_db()

        self.assertEqual(profile.bio, 'Original bio.')
        self.assertEqual(
            list(profile.courses_passed.all()),
            [self.course],
        )

    def test_empty_fields_clear_existing_profile_data(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            bio='Original bio.',
        )
        profile.courses_passed.add(self.course)

        response = self.submit({
            'bio': '',
            'courses_passed': [],
        })

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()

        self.assertEqual(profile.bio, '')
        self.assertFalse(profile.courses_passed.exists())
        self.assertTrue(
            Course.objects.filter(pk=self.course.pk).exists(),
        )

    def test_submitted_owner_and_rating_are_ignored(self):
        other_user = User.objects.create_user(
            email='other-tutor-update@example.com',
            password='OtherTutorPassword123!',
        )
        original_role = self.user.role

        response = self.submit({
            'bio': 'My tutor bio.',
            'courses_passed': [],
            'user': str(other_user.pk),
            'average_rating': '5.00',
            'role': User.Role.TUTOR,
        })

        self.assertEqual(response.status_code, 200)

        profile = TutorProfile.objects.get(user=self.user)
        self.assertEqual(profile.user_id, self.user.pk)
        self.assertIsNone(profile.average_rating)
        self.assertFalse(
            TutorProfile.objects.filter(user=other_user).exists(),
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, original_role)

class TutorProfileGetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='tutor-get@example.com',
            password='TutorGetPassword123!',
            role=User.Role.STUDENT,
        )
        self.course1 = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.course2 = Course.create_course(
            'MATH 110',
            'Calculus I',
        )
        self.url = reverse('profile')

    def test_get_returns_own_tutor_profile_data(self):
        profile = TutorProfile.objects.create(
            user=self.user,
            bio='I offer tutoring for computer science.',
        )
        profile.courses_passed.add(
            self.course2,
            self.course1,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['tutor_profile'],
            {
                'bio': 'I offer tutoring for computer science.',
                'courses_passed': sorted([
                    self.course1.pk,
                    self.course2.pk,
                ]),
                'average_rating': None,
            },
        )

    def test_get_without_tutor_profile_does_not_create_one(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['tutor_profile'])
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

    def test_get_does_not_return_another_users_tutor_profile(self):
        other_user = User.objects.create_user(
            email='other-tutor-get@example.com',
            password='OtherTutorGetPassword123!',
        )
        other_profile = TutorProfile.objects.create(
            user=other_user,
            bio='Another tutor bio.',
        )
        other_profile.courses_passed.add(self.course1)
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {'user_id': other_user.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['account']['id'],
            self.user.pk,
        )
        self.assertIsNone(response.json()['tutor_profile'])
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

    def test_get_returns_rating_as_decimal_string(self):
        TutorProfile.objects.create(
            user=self.user,
            bio='Rated tutor.',
            average_rating=Decimal('4.25'),
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['tutor_profile']['average_rating'],
            '4.25',
        )

    def test_get_returns_both_profiles_regardless_of_active_role(self):
        student_profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=2,
        )
        student_profile.courses.add(self.course1)

        tutor_profile = TutorProfile.objects.create(
            user=self.user,
            bio='Student and tutor.',
        )
        tutor_profile.courses_passed.add(self.course2)

        self.client.force_login(self.user)

        for role in (User.Role.STUDENT, User.Role.TUTOR):
            with self.subTest(role=role):
                self.user.role = role
                self.user.save(update_fields=['role'])

                response = self.client.get(self.url)

                self.assertEqual(response.status_code, 200)
                body = response.json()

                self.assertEqual(body['account']['role'], role)
                self.assertEqual(
                    body['student_profile'],
                    {
                        'major': 'CS',
                        'semester': 2,
                        'courses': [self.course1.pk],
                        'average_rating': None,
                    },
                )
                self.assertEqual(
                    body['tutor_profile'],
                    {
                        'bio': 'Student and tutor.',
                        'courses_passed': [self.course2.pk],
                        'average_rating': None,
                    },
                )

class CrossProfileRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='cross-profile@example.com',
            password='CrossProfilePassword123!',
            first_name='Marie',
            last_name='Example',
            phone='123456',
            role=User.Role.STUDENT,
        )

        self.student_course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.tutor_course = Course.create_course(
            'MATH 110',
            'Calculus I',
        )
        self.new_course = Course.create_course(
            'ENER 120',
            'Energy',
        )

        self.student_profile = StudentProfile.objects.create(
            user=self.user,
            major='CS',
            semester=2,
            average_rating=Decimal('4.00'),
        )
        self.student_profile.courses.add(self.student_course)

        self.tutor_profile = TutorProfile.objects.create(
            user=self.user,
            bio='Original tutor bio.',
            average_rating=Decimal('4.25'),
        )
        self.tutor_profile.courses_passed.add(self.tutor_course)

        self.profile_url = reverse('profile')
        self.role_url = reverse('switch_role')

    def assert_account_unchanged(self, expected_role=User.Role.STUDENT):
        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, 'Marie')
        self.assertEqual(self.user.last_name, 'Example')
        self.assertEqual(self.user.phone, '123456')
        self.assertEqual(
            self.user.email,
            'cross-profile@example.com',
        )
        self.assertEqual(self.user.role, expected_role)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def assert_student_profile_unchanged(self):
        self.student_profile.refresh_from_db()

        self.assertEqual(
            self.student_profile.user_id,
            self.user.pk,
        )
        self.assertEqual(self.student_profile.major, 'CS')
        self.assertEqual(self.student_profile.semester, 2)
        self.assertEqual(
            self.student_profile.average_rating,
            Decimal('4.00'),
        )
        self.assertEqual(
            set(
                self.student_profile.courses.values_list(
                    'pk',
                    flat=True,
                )
            ),
            {self.student_course.pk},
        )

    def assert_tutor_profile_unchanged(self):
        self.tutor_profile.refresh_from_db()

        self.assertEqual(
            self.tutor_profile.user_id,
            self.user.pk,
        )
        self.assertEqual(
            self.tutor_profile.bio,
            'Original tutor bio.',
        )
        self.assertEqual(
            self.tutor_profile.average_rating,
            Decimal('4.25'),
        )
        self.assertEqual(
            set(
                self.tutor_profile.courses_passed.values_list(
                    'pk',
                    flat=True,
                )
            ),
            {self.tutor_course.pk},
        )

    def test_role_switch_preserves_both_profiles_and_courses(self):
        self.client.force_login(self.user)

        for role in (User.Role.TUTOR, User.Role.STUDENT):
            with self.subTest(role=role):
                response = self.client.post(
                    self.role_url,
                    {'role': role},
                )

                self.assertEqual(response.status_code, 200)
                self.user.refresh_from_db()
                self.assertEqual(self.user.role, role)

                self.assert_student_profile_unchanged()
                self.assert_tutor_profile_unchanged()

                self.assertEqual(
                    StudentProfile.objects.filter(
                        user=self.user,
                    ).count(),
                    1,
                )
                self.assertEqual(
                    TutorProfile.objects.filter(
                        user=self.user,
                    ).count(),
                    1,
                )

    def test_tutor_post_updates_only_tutor_fields(self):
        self.user.switch_role(User.Role.TUTOR)
        self.user.save(update_fields=['role'])

        self.client.force_login(self.user)

        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'tutor',
                'bio': 'Updated tutor bio.',
                'courses_passed': [str(self.new_course.pk)],
                'first_name': 'Must not change',
                'phone': '999999',
                'major': 'ENER',
                'semester': '9',
                'courses': [str(self.new_course.pk)],
                'average_rating': '1.00',
                'role': User.Role.STUDENT,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.tutor_profile.refresh_from_db()

        self.assertEqual(
            self.tutor_profile.bio,
            'Updated tutor bio.',
        )
        self.assertEqual(
            set(
                self.tutor_profile.courses_passed.values_list(
                    'pk',
                    flat=True,
                )
            ),
            {self.new_course.pk},
        )
        self.assertEqual(
            self.tutor_profile.average_rating,
            Decimal('4.25'),
        )
        self.assertEqual(
            self.tutor_profile.user_id,
            self.user.pk,
        )
        self.assertEqual(
            TutorProfile.objects.filter(user=self.user).count(),
            1,
        )

        self.assert_account_unchanged(expected_role=User.Role.TUTOR)
        self.assert_student_profile_unchanged()

    def test_student_post_preserves_account_and_tutor_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'student',
                'major': 'ENER',
                'semester': '3',
                'courses': [str(self.new_course.pk)],
                'bio': 'Must not change tutor bio.',
                'courses_passed': [str(self.new_course.pk)],
                'average_rating': '1.00',
                'first_name': 'Must not change',
                'role': User.Role.TUTOR,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.student_profile.refresh_from_db()

        self.assertEqual(self.student_profile.major, 'ENER')
        self.assertEqual(self.student_profile.semester, 3)
        self.assertEqual(
            set(
                self.student_profile.courses.values_list(
                    'pk',
                    flat=True,
                )
            ),
            {self.new_course.pk},
        )
        self.assertEqual(
            self.student_profile.average_rating,
            Decimal('4.00'),
        )

        self.assert_account_unchanged()
        self.assert_tutor_profile_unchanged()

    def test_invalid_tutor_post_preserves_all_profile_data(self):
        self.user.switch_role(User.Role.TUTOR)
        self.user.save(update_fields=['role'])
        self.client.force_login(self.user)

        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'tutor',
                'bio': 'Must not be saved.',
                'courses_passed': ['not-a-course-id'],
                'first_name': 'Must not change',
                'major': 'ENER',
                'semester': '9',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'courses_passed',
            response.json()['errors'],
        )

        self.assert_account_unchanged(expected_role=User.Role.TUTOR)
        self.assert_student_profile_unchanged()
        self.assert_tutor_profile_unchanged()

    def test_anonymous_tutor_post_does_not_create_profile(self):
        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'tutor',
                'bio': 'Anonymous tutor bio.',
                'courses_passed': [str(self.new_course.pk)],
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(TutorProfile.objects.count(), 1)

        self.assert_account_unchanged()
        self.assert_student_profile_unchanged()
        self.assert_tutor_profile_unchanged()

    def test_student_cannot_change_existing_tutor_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'tutor',
                'bio': 'Must not be saved.',
                'courses_passed': [str(self.new_course.pk)],
                'role': User.Role.TUTOR,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())

        self.assert_account_unchanged()
        self.assert_student_profile_unchanged()
        self.assert_tutor_profile_unchanged()

    def test_user_without_role_cannot_change_role_specific_profiles(self):
        self.user.role = ''
        self.user.save(update_fields=['role'])
        self.client.force_login(self.user)

        payloads = (
            {
                'profile_type': 'student',
                'major': 'ENER',
                'semester': '3',
                'courses': [str(self.new_course.pk)],
            },
            {
                'profile_type': 'tutor',
                'bio': 'Must not be saved.',
                'courses_passed': [str(self.new_course.pk)],
            },
        )

        for data in payloads:
            with self.subTest(profile_type=data['profile_type']):
                response = self.client.post(self.profile_url, data)

                self.assertEqual(response.status_code, 403)
                self.assertIn('error', response.json())

                self.assert_account_unchanged(expected_role='')
                self.assert_student_profile_unchanged()
                self.assert_tutor_profile_unchanged()

    def test_tutor_update_is_allowed_after_switching_active_role(self):
        self.client.force_login(self.user)

        data = {
            'profile_type': 'tutor',
            'bio': 'Updated after role switch.',
            'courses_passed': [str(self.new_course.pk)],
        }

        response = self.client.post(self.profile_url, data)

        self.assertEqual(response.status_code, 403)
        self.assert_account_unchanged()
        self.assert_student_profile_unchanged()
        self.assert_tutor_profile_unchanged()

        response = self.client.post(
            self.role_url,
            {'role': User.Role.TUTOR},
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.TUTOR)
        self.assert_student_profile_unchanged()
        self.assert_tutor_profile_unchanged()

        response = self.client.post(self.profile_url, data)

        self.assertEqual(response.status_code, 200)

        self.tutor_profile.refresh_from_db()
        self.assertEqual(
            self.tutor_profile.bio,
            'Updated after role switch.',
        )
        self.assertEqual(
            set(
                self.tutor_profile.courses_passed.values_list(
                    'pk',
                    flat=True,
                )
            ),
            {self.new_course.pk},
        )
        self.assertEqual(
            self.tutor_profile.average_rating,
            Decimal('4.25'),
        )

        self.assert_account_unchanged(
            expected_role=User.Role.TUTOR,
        )
        self.assert_student_profile_unchanged()

# role access tests
class RoleAccessCheckTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def make_request(self, user):
        request = self.factory.post('/accounts/profile/')
        request.user = user
        return request

    def test_anonymous_user_receives_401(self):
        request = self.make_request(AnonymousUser())

        response = check_role_access(request, User.Role.TUTOR)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.content),
            {'error': 'Authentication required.'},
        )

    def test_matching_active_role_is_allowed(self):
        for role in (User.Role.STUDENT, User.Role.TUTOR):
            with self.subTest(role=role):
                user = User(
                    email='role-check@example.com',
                    role=role,
                )
                request = self.make_request(user)

                response = check_role_access(request, role)

                self.assertIsNone(response)

    def test_wrong_active_role_receives_403(self):
        role_pairs = (
            (User.Role.STUDENT, User.Role.TUTOR),
            (User.Role.TUTOR, User.Role.STUDENT),
        )

        for active_role, required_role in role_pairs:
            with self.subTest(
                active_role=active_role,
                required_role=required_role,
            ):
                user = User(
                    email='role-check@example.com',
                    role=active_role,
                )
                request = self.make_request(user)

                response = check_role_access(request, required_role)

                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    json.loads(response.content),
                    {
                        'error': (
                            'Your active role does not allow this action.'
                        ),
                    },
                )

    def test_user_without_active_role_receives_403(self):
        user = User(email='role-check@example.com')
        request = self.make_request(user)

        for required_role in (User.Role.STUDENT, User.Role.TUTOR):
            with self.subTest(required_role=required_role):
                response = check_role_access(request, required_role)

                self.assertEqual(response.status_code, 403)

class ProfileRoleAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='profile-role-access@example.com',
            password='ProfileRolePassword123!',
            role=User.Role.STUDENT,
        )
        self.url = reverse('profile')

    def test_student_cannot_update_tutor_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'tutor',
                'bio': 'I offer tutoring for computer science.',
                'courses_passed': [],
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

    def test_tutor_cannot_update_student_profile(self):
        self.user.switch_role(User.Role.TUTOR)
        self.user.save(update_fields=['role'])
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                'profile_type': 'student',
                'major': 'CS',
                'semester': '1',
                'courses': [],
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())
        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )

class ProfileAccessWithoutRoleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='no-role-profile@example.com',
            password='NoRoleProfilePassword123!',
            first_name='Marie',
            last_name='Example',
            phone='123456',
        )
        self.profile_url = reverse('profile')
        self.role_url = reverse('switch_role')
        self.client.force_login(self.user)

    def test_user_without_role_can_read_own_profile(self):
        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data['account']['id'], self.user.pk)
        self.assertEqual(data['account']['role'], '')
        self.assertIsNone(data['student_profile'])
        self.assertIsNone(data['tutor_profile'])

        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

    def test_user_without_role_can_update_account(self):
        response = self.client.post(
            self.profile_url,
            {
                'first_name': 'Alex',
                'last_name': 'Updated',
                'phone': '987654',
            },
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Alex')
        self.assertEqual(self.user.last_name, 'Updated')
        self.assertEqual(self.user.phone, '987654')
        self.assertEqual(self.user.role, '')
        self.assertEqual(
            self.user.email,
            'no-role-profile@example.com',
        )

        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )
        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

    def test_user_without_role_can_choose_role_and_create_tutor_profile(self):
        response = self.client.post(
            self.role_url,
            {'role': User.Role.TUTOR},
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.TUTOR)

        self.assertFalse(
            TutorProfile.objects.filter(user=self.user).exists(),
        )

        response = self.client.post(
            self.profile_url,
            {
                'profile_type': 'tutor',
                'bio': 'I offer tutoring for computer science.',
                'courses_passed': [],
            },
        )

        self.assertEqual(response.status_code, 200)

        profile = TutorProfile.objects.get(user=self.user)
        self.assertEqual(
            profile.bio,
            'I offer tutoring for computer science.',
        )
        self.assertFalse(profile.courses_passed.exists())
        self.assertFalse(
            StudentProfile.objects.filter(user=self.user).exists(),
        )
class test_favorite_tutors(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='student@uregina.ca',
            password='676767jkhHH!',
            first_name='Max',
            last_name='Peter',
        )
        self.tutor = User.objects.create_user(
            email='tutor@uregina.ca',
            password='6767fjhhHH!',
            first_name='Hallo',
            last_name='Welt',
        )
        self.tutor_profile = TutorProfile.objects.create(
            user=self.tutor,
            bio='Bitte buch mich ich bin so gut',
            average_rating=Decimal('1.80'),
        )

    def test_addrm_fav_tutor(self):
        profile = StudentProfile.objects.create(user=self.student)
        profile.add_favorite_tutor(self.tutor)
        self.assertIn(self.tutor, profile.get_favorite_tutors())
        profile.remove_favorite_tutor(self.tutor)
        self.assertNotIn(self.tutor, profile.get_favorite_tutors())


    def test_addrm_fav_tutor_view(self):
        StudentProfile.objects.create(user=self.student)
        self.client.force_login(self.student)

        url = reverse('toggle_favorite_tutor', kwargs={'tutor_id': self.tutor.id})
        list_url = reverse('favorite_tutors')

        list_added = self.client.post(url)
        self.assertEqual(list_added.status_code, 200)
        self.assertTrue(list_added.json()['is_favorite'])

        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, 200)
        favs = res_list.json()['favorite_tutors']
        self.assertEqual(len(favs), 1)
        self.assertEqual(favs[0]['id'], self.tutor.id)
        self.assertEqual(favs[0]['average_rating'], '1.80')

        list_removed = self.client.post(url)
        self.assertEqual(list_removed.status_code, 200)
        self.assertFalse(list_removed.json()['is_favorite'])

        list_empty = self.client.get(list_url)
        self.assertEqual(len(list_empty.json()['favorite_tutors']), 0)

    def test_fav_tutor_no_studenttutor_profile(self):
        self.client.force_login(self.student)
        url = reverse('toggle_favorite_tutor', kwargs={'tutor_id': self.tutor.id})
        fav_list = self.client.post(url)
        self.assertEqual(fav_list.status_code, 400)

        StudentProfile.objects.create(user=self.student)
        url_self = reverse('toggle_favorite_tutor', kwargs={'tutor_id': self.student.id})
        fav_list2 = self.client.post(url_self)
        self.assertEqual(fav_list2.status_code, 400)

#***********************************************************************************************************************************************
#------------------------------------------ Tests for personalise, updates made on register and login-------------------------------------------
#----------------------------------------------------------------------------------Update if it causing troubles to other tests-----------------
#***********************************************************************************************************************************************

User = get_user_model()


def make_courses(count=30):
    return [
        Course.create_course(f'CS {100 + i}', f'Sample course {i}')
        for i in range(count)
    ]


class RegisterPageTests(TestCase):
    good = {
        'first_name': 'Ana',
        'last_name': 'Bo',
        'email': 'Ana@Example.com',
        'password1': 'correct-horse-91',
        'password2': 'correct-horse-91',
        'role': 'tutor',
    }

    def test_get_shows_the_form(self):
        response = self.client.get(reverse('register'))
        self.assertContains(response, 'Create your account')

    def test_valid_signup_creates_user_logs_in_and_goes_to_personalise(self):
        response = self.client.post(reverse('register'), self.good)

        self.assertRedirects(
            response, reverse('personalise'), fetch_redirect_response=False,
        )
        user = User.objects.get(email='ana@example.com')   # stored lowercase
        self.assertEqual(
            (user.first_name, user.last_name, user.role),
            ('Ana', 'Bo', 'tutor'),
        )
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_password_is_hashed(self):
        self.client.post(reverse('register'), self.good)
        user = User.objects.get(email='ana@example.com')
        self.assertNotEqual(user.password, self.good['password1'])
        self.assertTrue(user.check_password(self.good['password1']))

    def test_role_can_be_left_empty(self):
        self.client.post(reverse('register'), {**self.good, 'role': ''})
        self.assertEqual(User.objects.get().role, '')

    def test_missing_required_fields(self):
        response = self.client.post(reverse('register'), {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, 'is-invalid')

    def test_mismatched_passwords(self):
        data = {**self.good, 'password2': 'different-pass-91'}
        response = self.client.post(reverse('register'), data)
        self.assertContains(response, 'The two passwords do not match.')
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_is_rejected(self):
        data = {**self.good, 'password1': '12345678', 'password2': '12345678'}
        response = self.client.post(reverse('register'), data)
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, 'is-invalid')

    def test_duplicate_email_ignores_case(self):
        User.objects.create_user(email='ana@example.com', password='whatever-123')
        response = self.client.post(reverse('register'), self.good)
        self.assertContains(response, 'An account with this email already exists.')
        self.assertEqual(User.objects.count(), 1)

    def test_form_keeps_what_was_typed_after_an_error(self):
        data = {**self.good, 'password2': 'different-pass-91'}
        response = self.client.post(reverse('register'), data)
        self.assertContains(response, 'value="Ana"')
        self.assertContains(response, 'value="tutor" checked')

    def test_signed_in_user_is_sent_away_from_register(self):
        user = User.objects.create_user(email='in@x.ca', password='pw-12345-xyz')
        self.client.force_login(user)
        response = self.client.get(reverse('register'))
        self.assertRedirects(
            response, reverse('student_home'), fetch_redirect_response=False,
        )


class PersonaliseTests(TestCase):
    def setUp(self):
        self.courses = make_courses(30)
        self.ids = [course.pk for course in self.courses]

    def sign_in(self, role):
        user = User.objects.create_user(
            email=f"{role or 'later'}@x.ca", password='pw-12345-xyz', role=role,
        )
        self.client.force_login(user)
        return user

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse('personalise'))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('personalise')}",
            fetch_redirect_response=False,
        )

    def test_student_page_has_the_limit_of_ten(self):
        self.sign_in('student')
        response = self.client.get(reverse('personalise'))
        self.assertContains(response, 'data-max="10"')
        self.assertContains(response, 'Which courses do you need help with?')

    def test_tutor_page_has_no_limit(self):
        self.sign_in('tutor')
        response = self.client.get(reverse('personalise'))
        self.assertContains(response, 'data-max=""')
        self.assertContains(response, 'Which courses can you tutor?')

    def test_decide_later_counts_as_student(self):
        user = self.sign_in('')
        response = self.client.get(reverse('personalise'))
        self.assertContains(response, 'data-max="10"')
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    def test_student_saves_ten_courses(self):
        user = self.sign_in('student')
        response = self.client.post(reverse('personalise'), {'courses': self.ids[:10]})
        self.assertRedirects(response, reverse('student_home'), fetch_redirect_response=False)
        self.assertEqual(user.student_profile.courses.count(), 10)

    def test_student_cannot_save_eleven(self):
        user = self.sign_in('student')
        response = self.client.post(reverse('personalise'), {'courses': self.ids[:11]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please pick at most 10 courses.')
        self.assertEqual(user.student_profile.courses.count(), 0)

    def test_picks_survive_an_error(self):
        self.sign_in('student')
        response = self.client.post(reverse('personalise'), {'courses': self.ids[:11]})
        self.assertEqual(response.context['selected_ids'], self.ids[:11])

    def test_tutor_saves_more_than_ten_to_courses_passed(self):
        user = self.sign_in('tutor')
        response = self.client.post(reverse('personalise'), {'courses': self.ids[:25]})
        self.assertRedirects(response, reverse('tutor_home'), fetch_redirect_response=False)
        self.assertEqual(user.tutor_profile.courses_passed.count(), 25)

    def test_unknown_course_id_is_rejected(self):
        user = self.sign_in('student')
        response = self.client.post(reverse('personalise'), {'courses': [self.ids[0], 99999]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.student_profile.courses.count(), 0)

    def test_skip_saves_nothing(self):
        user = self.sign_in('student')
        response = self.client.post(
            reverse('personalise'), {'skip': '1', 'courses': self.ids[:3]},
        )
        self.assertRedirects(response, reverse('student_home'), fetch_redirect_response=False)
        self.assertEqual(user.student_profile.courses.count(), 0)

    def test_saving_replaces_the_old_choice(self):
        user = self.sign_in('student')
        self.client.post(reverse('personalise'), {'courses': self.ids[:3]})
        self.client.post(reverse('personalise'), {'courses': self.ids[5:7]})
        self.assertEqual(
            sorted(user.student_profile.courses.values_list('pk', flat=True)),
            self.ids[5:7],
        )

    def test_page_preselects_saved_courses(self):
        self.sign_in('student')
        self.client.post(reverse('personalise'), {'courses': self.ids[:2]})
        response = self.client.get(reverse('personalise'))
        self.assertEqual(response.context['selected_ids'], self.ids[:2])

class LoginPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='ana@example.com', password='correct-horse-91')
        self.url = reverse('login')

    def test_get_renders_login_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')

    def test_valid_login_redirects_to_student_home(self):
        response = self.client.post(self.url, {'email': 'ana@example.com', 'password': 'correct-horse-91'})
        self.assertRedirects(response, reverse('student_home'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_email_is_case_insensitive(self):
        response = self.client.post(self.url, {'email': '  ANA@Example.com ', 'password': 'correct-horse-91'})
        self.assertEqual(response.status_code, 302)

    def test_wrong_password_shows_error_and_keeps_email(self):
        response = self.client.post(self.url, {'email': 'ana@example.com', 'password': 'nope'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Invalid email address or password.', status_code=400)
        self.assertContains(response, 'value="ana@example.com"', status_code=400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_email_gets_same_error(self):
        response = self.client.post(self.url, {'email': 'who@example.com', 'password': 'x'})
        self.assertContains(response, 'Invalid email address or password.', status_code=400)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {'email': 'ana@example.com', 'password': 'correct-horse-91'})
        self.assertEqual(response.status_code, 400)

    def test_next_is_followed_when_safe(self):
        response = self.client.post(self.url + '?next=/personalise/',
                                    {'email': 'ana@example.com', 'password': 'correct-horse-91'})
        self.assertRedirects(response, '/personalise/', fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        response = self.client.post(self.url + '?next=https://evil.example/',
                                    {'email': 'ana@example.com', 'password': 'correct-horse-91'})
        self.assertRedirects(response, reverse('student_home'), fetch_redirect_response=False)

    def test_signed_in_user_is_redirected_away(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.url), reverse('student_home'), fetch_redirect_response=False)

#************************************************************************************************************************************************
#------------------------------------------END OF TESTS FOR PERSONALISE, UPDATED REGISTER AND LOGIN----------------------------------------------
#************************************************************************************************************************************************


#************************************************************************************************************************************************
#-------------------------------------------TESTS FOR HOME/DASHBOARD PAGES-----------------------------------------------------------------------
#************************************************************************************************************************************************

class HomePageTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='s@example.com', password='pw-12345-xyz', first_name='Sam', role='student')
        self.tutor = User.objects.create_user(
            email='t@example.com', password='pw-12345-xyz', first_name='Tess', role='tutor')
        self.undecided = User.objects.create_user(email='u@example.com', password='pw-12345-xyz')
        self.course = Course.create_course('CS 110', 'Intro to Computer Science')

    def test_anonymous_users_are_sent_to_login(self):
        for name in ('student_home', 'tutor_home'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, f"{reverse('login')}?next={reverse(name)}",
                                     fetch_redirect_response=False)

    def test_student_sees_student_home_with_courses(self):
        StudentProfile.objects.create(user=self.student).courses.add(self.course)
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_home.html')
        self.assertContains(response, 'Welcome, Sam')
        self.assertContains(response, 'CS 110')

    def test_student_home_includes_matching_tutors_and_slots(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from bookings.models import Available_Slots

        student_profile = StudentProfile.objects.create(user=self.student)
        student_profile.courses.add(self.course)
        TutorProfile.objects.create(
            user=self.tutor,
            bio='Passed CS 110 with notes to share.',
        ).courses_passed.add(self.course)

        start = timezone.now() + timedelta(days=1)
        Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start,
            end_time=start + timedelta(hours=1),
            price_per_hour=Decimal('25.00'),
            location_type=Available_Slots.LocationType.ONLINE,
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse('student_home'))

        self.assertEqual(response.status_code, 200)
        tutors = response.context['tutors']
        self.assertEqual(len(tutors), 1)
        self.assertEqual(tutors[0]['id'], self.tutor.id)
        self.assertEqual(tutors[0]['bio'], 'Passed CS 110 with notes to share.')
        self.assertFalse(tutors[0]['is_favorite'])
        self.assertEqual(len(tutors[0]['available_slots']), 1)
        self.assertEqual(tutors[0]['available_slots'][0]['price_per_hour'], '25.00')
        self.assertEqual(tutors[0]['available_slots'][0]['location_type'], 'online')
        self.assertContains(response, 'Tess')
        self.assertContains(response, 'Passed CS 110 with notes to share.')
        self.assertContains(response, 'Courses passed')
        self.assertContains(response, 'Available times')
        self.assertContains(response, 'Online')
        self.assertContains(response, '$25.00/hour')
        self.assertContains(response, '1 open')
        self.assertContains(response, '1 tutor')
        self.assertContains(response, 'Favourite')
        self.assertContains(response, 'Favourites only')
        self.assertContains(response, reverse('toggle_favorite_tutor', kwargs={'tutor_id': self.tutor.id}))

        student_profile.add_favorite_tutor(self.tutor)
        favorited = self.client.get(reverse('student_home'))
        self.assertTrue(favorited.context['tutors'][0]['is_favorite'])
        self.assertContains(favorited, 'Favourited')
        self.assertContains(favorited, 'data-favorites-filter')
        self.assertContains(favorited, 'data-is-favorite="true"')
        self.assertContains(favorited, 'Show all tutors')
        self.assertContains(favorited, 'Remove from favourites')
        self.assertContains(response, 'Add to favourites')

    def test_student_without_courses_is_offered_the_picker(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_home'))
        self.assertContains(response, reverse('personalise'))

    def test_tutor_sees_tutor_home_with_courses(self):
        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.course)
        self.client.force_login(self.tutor)
        response = self.client.get(reverse('tutor_home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tutor_home.html')
        self.assertContains(response, 'CS 110')
        self.assertContains(response, 'Tutor overview')
        self.assertContains(response, 'Courses you teach')
        self.assertContains(response, reverse('tutor_sessions'))
        self.assertNotContains(response, 'name="price_per_hour"')
        self.assertNotContains(response, 'id="slot-start"')

    def test_tutor_home_shows_overview_stats_and_upcoming_slots(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from bookings.models import Available_Slots

        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.course)
        start = timezone.now() + timedelta(days=2)
        Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start,
            end_time=start + timedelta(hours=1),
            price_per_hour=Decimal('30.00'),
            location_type=Available_Slots.LocationType.ONLINE,
        )

        self.client.force_login(self.tutor)
        response = self.client.get(reverse('tutor_home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['course_count'], 1)
        self.assertEqual(response.context['open_slot_count'], 1)
        self.assertEqual(response.context['booked_count'], 0)
        self.assertEqual(len(response.context['upcoming_slots']), 1)
        self.assertContains(response, 'Upcoming open slots')
        self.assertContains(response, '$30.00/hour')
        self.assertContains(response, 'Online')
        self.assertContains(response, 'Set up tutoring sessions')

    def test_tutor_home_shows_bookings_with_cancel_button(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from bookings.models import Available_Slots, Booking

        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.course)
        start = timezone.now() + timedelta(days=2)
        slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start,
            end_time=start + timedelta(hours=1),
            price_per_hour=Decimal('25.00'),
        )
        booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            time_slot=slot,
            start_time=start,
            end_time=start + timedelta(hours=1),
            session_price=Decimal('25.00'),
            status=Booking.Status.CONFIRMED,
        )

        self.client.force_login(self.tutor)
        response = self.client.get(reverse('tutor_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirmed bookings')
        self.assertContains(response, 'Cancel')
        self.assertContains(response, 'js-cancel-booking')
        self.assertContains(
            response,
            reverse('cancel_booking', kwargs={'booking_id': booking.id}),
        )
        self.assertContains(response, 'js/bookings-home.js')
        self.assertEqual(response.context['booked_count'], 1)
        self.assertEqual(len(response.context['recent_bookings']), 1)
        self.assertEqual(
            response.context['recent_bookings'][0]['cancel_url'],
            reverse('cancel_booking', kwargs={'booking_id': booking.id}),
        )

    def test_student_home_shows_bookings_with_cancel_button(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from bookings.models import Available_Slots, Booking

        StudentProfile.objects.create(user=self.student)
        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.course)
        start = timezone.now() + timedelta(days=2)
        slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start,
            end_time=start + timedelta(hours=1),
            price_per_hour=Decimal('25.00'),
        )
        booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            time_slot=slot,
            start_time=start,
            end_time=start + timedelta(hours=1),
            session_price=Decimal('25.00'),
            status=Booking.Status.CONFIRMED,
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse('student_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your bookings')
        self.assertContains(response, 'Tess')
        self.assertContains(response, 'Cancel')
        self.assertContains(response, 'js-cancel-booking')
        self.assertContains(
            response,
            reverse('cancel_booking', kwargs={'booking_id': booking.id}),
        )
        self.assertContains(response, 'js/bookings-home.js')
        self.assertContains(response, 'id="cancel-deadline-modal"')
        self.assertContains(response, 'Too late to cancel')

    def test_student_cancel_after_deadline_returns_readable_error(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from bookings.models import Available_Slots, Booking

        start = timezone.now() + timedelta(hours=1)
        slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start,
            end_time=start + timedelta(hours=1),
            price_per_hour=Decimal('25.00'),
        )
        booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            time_slot=slot,
            start_time=start,
            end_time=start + timedelta(hours=1),
            session_price=Decimal('25.00'),
            status=Booking.Status.CONFIRMED,
        )

        self.client.force_login(self.student)
        response = self.client.post(
            reverse('cancel_booking', kwargs={'booking_id': booking.id}),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Cancellation deadline has passed',
            response.json()['error'],
        )
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_tutor_is_redirected_away_from_student_home(self):
        self.client.force_login(self.tutor)
        self.assertRedirects(self.client.get(reverse('student_home')),
                             reverse('tutor_home'), fetch_redirect_response=False)

    def test_student_is_redirected_away_from_tutor_home(self):
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(reverse('tutor_home')),
                             reverse('student_home'), fetch_redirect_response=False)

    def test_decide_later_user_gets_student_home(self):
        self.client.force_login(self.undecided)
        self.assertEqual(self.client.get(reverse('student_home')).status_code, 200)
        self.assertRedirects(self.client.get(reverse('tutor_home')),
                             reverse('student_home'), fetch_redirect_response=False)

    def test_login_sends_each_role_to_its_own_home(self):
        for user, name in ((self.student, 'student_home'), (self.tutor, 'tutor_home')):
            with self.subTest(role=user.role):
                self.client.logout()
                response = self.client.post(reverse('login'),
                                            {'email': user.email, 'password': 'pw-12345-xyz'})
                self.assertRedirects(response, reverse(name), fetch_redirect_response=False)

#************************************************************************************************************************************************
#------------------------------------------------------- END OF HOME TESTS ----------------------------------------------------------------------
#************************************************************************************************************************************************

# tutor dashboard tests
class TutorDashboardViewTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='dashboard-tutor@example.com',
            password='DashboardTestPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='dashboard-other-tutor@example.com',
            password='DashboardTestPassword123!',
            role=User.Role.TUTOR,
        )
        self.student = User.objects.create_user(
            email='dashboard-student@example.com',
            password='DashboardTestPassword123!',
            role=User.Role.STUDENT,
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.start = (
            timezone.now() + timedelta(days=3)
        ).replace(microsecond=0)
        self.url = reverse('tutor_dashboard')
        self.client.force_login(self.tutor)

    def _get_dashboard(self, params=None):
        response = self.client.get(self.url, params or {})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def _slot(self, **overrides):
        values = {
            'tutor': self.tutor,
            'start_time': self.start,
            'end_time': self.start + timedelta(hours=3),
            'price_per_hour': Decimal('20.00'),
            'location_type': Available_Slots.LocationType.ONLINE,
            'status': Available_Slots.Status.AVAILABLE,
        }
        values.update(overrides)
        return Available_Slots.objects.create(**values)

    def _booking(self, **overrides):
        values = {
            'student': self.student,
            'tutor': self.tutor,
            'course': self.course,
            'status': Booking.Status.CONFIRMED,
            'session_price': Decimal('20.00'),
        }
        values.update(overrides)
        return Booking.objects.create(**values)

    def _request(self, interested=False, **overrides):
        values = {
            'student': self.student,
            'course': self.course,
            'description': 'Help with software development.',
            'status': TutoringRequest.Status.OPEN,
            'visibility': TutoringRequest.Visibility.ALL_TUTORS,
        }
        values.update(overrides)
        tutoring_request = TutoringRequest.objects.create(**values)

        if interested:
            TutoringRequestInterest.objects.create(
                tutoring_request=tutoring_request,
                tutor=self.tutor,
            )

        return tutoring_request

    def _request_ids(self):
        return [
            item['request_id']
            for item in self._get_dashboard()['open_requests']
        ]

    def _post_action(self, name, request_id, data=None, status=200):
        response = self.client.post(
            reverse(name, kwargs={'request_id': request_id}),
            data or {},
        )
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def _domain_snapshot(self):
        models = (
            User,
            StudentProfile,
            TutorProfile,
            Available_Slots,
            Booking,
            TutoringRequest,
            TutoringRequestInterest,
        )
        return {
            model._meta.label: list(
                model.objects.order_by('pk').values()
            )
            for model in models
        }

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)
        self.assertIn('error', response.json())

    def test_requires_active_tutor_role_even_with_tutor_profile(self):
        TutorProfile.objects.get_or_create(user=self.student)
        self.client.force_login(self.student)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())

    def test_rejects_non_get_methods(self):
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)
                self.assertEqual(response.status_code, 405)

    def test_empty_dashboard_has_three_empty_lists(self):
        self.assertEqual(
            self._get_dashboard(),
            {
                'booked_sessions': [],
                'open_requests': [],
                'schedule': [],
            },
        )

    def test_only_own_confirmed_tutor_bookings_are_returned(self):
        own = self._booking()

        for status in Booking.Status.values:
            if status != Booking.Status.CONFIRMED:
                self._booking(status=status)

        self._booking(tutor=self.other_tutor)
        self._booking(
            student=self.tutor,
            tutor=self.other_tutor,
        )

        data = self._get_dashboard(
            {'tutor_id': self.other_tutor.pk}
        )

        self.assertEqual(
            [item['id'] for item in data['booked_sessions']],
            [own.pk],
        )

    def test_booking_contract_uses_stored_session_details(self):
        slot = self._slot()
        session_start = self.start + timedelta(hours=1)
        session_end = session_start + timedelta(minutes=45)

        booking = self._booking(
            time_slot=slot,
            start_time=session_start,
            end_time=session_end,
            price_per_hour=Decimal('20.00'),
            session_price=Decimal('15.00'),
            location_type=Available_Slots.LocationType.ONLINE,
            student_note='Focus on testing.',
        )

        Available_Slots.objects.filter(pk=slot.pk).update(
            price_per_hour=Decimal('25.00'),
            location_type=Available_Slots.LocationType.IN_PERSON,
        )

        data = self._get_dashboard()

        self.assertEqual(
            set(data),
            {'booked_sessions', 'open_requests', 'schedule'},
        )
        self.assertEqual(
            data['booked_sessions'],
            [{
                'id': booking.pk,
                'student_id': self.student.pk,
                'student_email': self.student.email,
                'course': str(self.course),
                'student_note': 'Focus on testing.',
                'status': Booking.Status.CONFIRMED,
                'request_time': booking.request_time.isoformat(),
                'time_slot_id': slot.pk,
                'start_time': session_start.isoformat(),
                'end_time': session_end.isoformat(),
                'price_per_hour': '20.00',
                'session_price': '15.00',
                'location_type': 'online',
            }],
        )
        self.assertEqual(
            data['schedule'],
            [{
                'id': slot.pk,
                'start_time': self.start.isoformat(),
                'end_time': (
                    self.start + timedelta(hours=3)
                ).isoformat(),
                'price_per_hour': '25.00',
                'location_type': 'in_person',
                'status': Available_Slots.Status.AVAILABLE,
            }],
        )

    def test_legacy_bookings_keep_missing_details_null(self):
        slot = self._slot()
        without_slot = self._booking(course=None)
        with_slot = self._booking(time_slot=slot)

        sessions = {
            item['id']: item
            for item in self._get_dashboard()['booked_sessions']
        }

        for booking in (without_slot, with_slot):
            with self.subTest(booking_id=booking.pk):
                item = sessions[booking.pk]
                self.assertEqual(
                    item['time_slot_id'],
                    booking.time_slot_id,
                )
                for field in (
                    'start_time',
                    'end_time',
                    'price_per_hour',
                    'location_type',
                ):
                    self.assertIsNone(item[field])
                self.assertEqual(item['session_price'], '20.00')

        self.assertIsNone(sessions[without_slot.pk]['course'])

    def test_booking_order_uses_request_time_then_descending_id(self):
        older = self._booking()
        tied_first = self._booking()
        tied_second = self._booking()
        timestamp = timezone.now().replace(microsecond=0)

        Booking.objects.filter(pk=older.pk).update(
            request_time=timestamp - timedelta(days=1),
        )
        Booking.objects.filter(
            pk__in=[tied_first.pk, tied_second.pk],
        ).update(request_time=timestamp)

        self.assertEqual(
            [
                item['id']
                for item in self._get_dashboard()['booked_sessions']
            ],
            [tied_second.pk, tied_first.pk, older.pk],
        )

    def test_schedule_keeps_own_statuses_and_deterministic_order(self):
        later = self._slot(
            start_time=self.start + timedelta(days=1),
            end_time=self.start + timedelta(days=1, hours=3),
        )
        earlier = [
            self._slot(status=status)
            for status in Available_Slots.Status.values
        ]
        self._slot(tutor=self.other_tutor)

        data = self._get_dashboard(
            {'tutor_id': self.other_tutor.pk}
        )
        schedule = data['schedule']

        self.assertEqual(
            [item['id'] for item in schedule],
            [slot.pk for slot in earlier] + [later.pk],
        )
        self.assertEqual(
            {item['status'] for item in schedule},
            set(Available_Slots.Status.values),
        )

    def test_requests_require_own_interest_and_exclude_hidden_entries(self):
        included = self._request(interested=True)
        self._request()

        other_interest = self._request()
        TutoringRequestInterest.objects.create(
            tutoring_request=other_interest,
            tutor=self.other_tutor,
        )

        # Several interested tutors must not duplicate the request.
        TutoringRequestInterest.objects.create(
            tutoring_request=included,
            tutor=self.other_tutor,
        )

        self._request(interested=True, student=self.tutor)
        self._request(
            interested=True,
            status=TutoringRequest.Status.WITHDRAWN,
        )
        self._request(
            interested=True,
            status=TutoringRequest.Status.FULFILLED,
        )
        self._request(
            interested=True,
            visibility=TutoringRequest.Visibility.COURSE_FACULTY,
        )

        data = self._get_dashboard(
            {'tutor_id': self.other_tutor.pk}
        )

        self.assertEqual(
            data['open_requests'],
            [{
                'request_id': included.pk,
                'course_id': self.course.pk,
                'course': str(self.course),
                'description': included.description,
                'location_type': included.location_type,
                'visibility': TutoringRequest.Visibility.ALL_TUTORS,
                'status': TutoringRequest.Status.OPEN,
                'fulfilled_booking_id': None,
                'created_at': included.created_at.isoformat(),
                'has_expressed_interest': True,
            }],
        )

    def test_request_order_uses_creation_time_then_descending_id(self):
        older = self._request(interested=True)
        tied_first = self._request(interested=True)
        tied_second = self._request(interested=True)
        timestamp = timezone.now().replace(microsecond=0)

        TutoringRequest.objects.filter(pk=older.pk).update(
            created_at=timestamp - timedelta(days=1),
        )
        TutoringRequest.objects.filter(
            pk__in=[tied_first.pk, tied_second.pk],
        ).update(created_at=timestamp)

        self.assertEqual(
            self._request_ids(),
            [tied_second.pk, tied_first.pk, older.pk],
        )

    def test_interest_lifecycle_adds_and_removes_dashboard_request(self):
        tutoring_request = self._request()

        self.assertEqual(self._request_ids(), [])

        self._post_action(
            'express_tutoring_request_interest',
            tutoring_request.pk,
            status=201,
        )
        self.assertEqual(
            self._request_ids(),
            [tutoring_request.pk],
        )

        # Repeating the action is idempotent.
        self._post_action(
            'express_tutoring_request_interest',
            tutoring_request.pk,
        )
        self.assertEqual(
            self._request_ids(),
            [tutoring_request.pk],
        )

        self._post_action(
            'withdraw_tutoring_request_interest',
            tutoring_request.pk,
        )
        self.assertEqual(self._request_ids(), [])
        self.assertEqual(Booking.objects.count(), 0)

    def test_student_withdrawal_removes_interested_request(self):
        tutoring_request = self._request(interested=True)
        self.assertEqual(
            self._request_ids(),
            [tutoring_request.pk],
        )

        self.client.force_login(self.student)
        self._post_action(
            'withdraw_tutoring_request',
            tutoring_request.pk,
        )

        self.client.force_login(self.tutor)
        self.assertEqual(self._request_ids(), [])
        self.assertEqual(Booking.objects.count(), 0)

    def test_fulfillment_adds_session_only_to_selected_tutor(self):
        tutoring_request = self._request(interested=True)
        TutoringRequestInterest.objects.create(
            tutoring_request=tutoring_request,
            tutor=self.other_tutor,
        )
        slot = self._slot()
        session_start = self.start + timedelta(hours=1)
        session_end = session_start + timedelta(hours=1)

        for tutor in (self.tutor, self.other_tutor):
            self.client.force_login(tutor)
            self.assertEqual(
                self._request_ids(),
                [tutoring_request.pk],
            )

        self.client.force_login(self.student)
        result = self._post_action(
            'fulfill_tutoring_request',
            tutoring_request.pk,
            {
                'slot_id': slot.pk,
                'start_time': session_start.isoformat(),
                'end_time': session_end.isoformat(),
            },
            status=201,
        )

        tutoring_request.refresh_from_db()
        self.assertEqual(
            tutoring_request.status,
            TutoringRequest.Status.FULFILLED,
        )
        self.assertEqual(
            tutoring_request.fulfilled_booking_id,
            result['booking_id'],
        )

        self.client.force_login(self.tutor)
        own_data = self._get_dashboard()

        self.assertEqual(own_data['open_requests'], [])
        self.assertEqual(
            [item['id'] for item in own_data['booked_sessions']],
            [result['booking_id']],
        )
        self.assertEqual(
            own_data['booked_sessions'][0]['status'],
            Booking.Status.CONFIRMED,
        )
        self.assertEqual(
            own_data['booked_sessions'][0]['start_time'],
            session_start.isoformat(),
        )
        self.assertEqual(
            own_data['booked_sessions'][0]['session_price'],
            '20.00',
        )

        self.client.force_login(self.other_tutor)
        other_data = self._get_dashboard()

        self.assertEqual(other_data['open_requests'], [])
        self.assertEqual(other_data['booked_sessions'], [])

    def test_dashboard_get_does_not_modify_domain_data(self):
        slot = self._slot()
        self._booking(time_slot=slot)
        self._request(interested=True)

        before = self._domain_snapshot()

        self._get_dashboard()
        self._get_dashboard({'tutor_id': self.other_tutor.pk})

        self.assertEqual(self._domain_snapshot(), before)
#************************************************************************************************************************************************
#------------------------------------------------ TESTS FOR LOAD COURSES -----------------------------------------------------------------------
#************************************************************************************************************************************************

class ParseCatalogueTests(SimpleTestCase):
    def parse(self, text):
        return dict(parse_catalogue_lines(text.split('\n')))

    def test_reads_code_and_name(self):
        text = 'CS 110 - Programming and Problem Solving\nA first course.\n3 Credit Hours'
        self.assertEqual(self.parse(text), {'CS 110': 'Programming and Problem Solving'})

    def test_joins_a_title_that_wrapped_onto_two_lines(self):
        text = ('ACAD 100 - Academic Discourse: Writing, Research, and Learning\n'
                'Strategies\nThis course provides first-year students with tools.')
        self.assertEqual(self.parse(text)['ACAD 100'],
                         'Academic Discourse: Writing, Research, and Learning Strategies')

    def test_does_not_join_the_description_line(self):
        text = ('ACSC 041 - Actuarial Science Internship Term 1\n'
                'First four month term of Actuarial Science Internship Program.')
        self.assertEqual(self.parse(text)['ACSC 041'], 'Actuarial Science Internship Term 1')

    def test_skips_codes_with_a_letter_suffix(self):
        text = 'ACSC 390AA - Canadian Pension Plan Review\nA review.'
        self.assertEqual(self.parse(text), {})

    def test_removes_the_aa_zz_series_tag(self):
        text = 'ENGL 310 - Studies in Literature - an AA-ZZ series.\nTopics vary.'
        self.assertEqual(self.parse(text)['ENGL 310'], 'Studies in Literature')

    def test_a_code_inside_another_title_is_not_a_new_course(self):
        text = ("EDAC 050 - Expériences d'apprentissage hors campus (formerly\n"
                'EFLD 050 - Bac section only)\nOrganiser des expériences.\n'
                '0 Lab Hours per Week\n'
                'EFLD 050 - OCRE (Off-Campus Residential Experience)\nAn off-campus experience.')
        courses = self.parse(text)
        self.assertEqual(courses['EFLD 050'], 'OCRE (Off-Campus Residential Experience)')
        self.assertIn('Bac section only', courses['EDAC 050'])

    def test_a_course_listed_twice_keeps_the_first_name(self):
        text = 'CS 110 - First name\nText.\nCS 110 - Second name\nText.'
        self.assertEqual(self.parse(text), {'CS 110': 'First name'})

    def test_prerequisite_lines_are_not_courses(self):
        text = 'CS 210 - Data Structures\nText.\n***Prerequisite: CS 110 - Programming***'
        self.assertEqual(list(self.parse(text)), ['CS 210'])

    def test_ligatures_are_turned_into_normal_letters(self):
        self.assertEqual(self.parse('CS 110 - Scientiﬁc Computing\nText.')['CS 110'], 'Scientific Computing')


class SavedCatalogueTests(SimpleTestCase):
    def test_saved_csv_has_the_courses_the_project_needs(self):
        courses = dict(read_csv())
        self.assertGreater(len(courses), 4000)
        for code in ('CS 110', 'CS 210', 'CS 476', 'MATH 110', 'STAT 100'):
            self.assertIn(code, courses)

    def test_every_code_is_valid_and_unique(self):
        rows = read_csv()
        codes = [code for code, _name in rows]
        self.assertEqual(len(codes), len(set(codes)))
        for code, name in rows:
            self.assertTrue(Course.check_course_code_spelling(code), code)
            self.assertTrue(name and len(name) <= 200, code)


class LoadCoursesCommandTests(TestCase):
    def run_command(self):
        out = StringIO()
        call_command('load_courses', stdout=out)
        return out.getvalue()

    def test_loads_courses_with_the_right_faculty(self):
        self.run_command()
        self.assertGreater(Course.objects.count(), 4000)
        cs = Course.objects.get(course_code='CS 110')
        self.assertEqual(cs.course_faculty, Course.FACULTIES['CS'])

    def test_running_twice_adds_nothing_new(self):
        self.run_command()
        count = Course.objects.count()
        output = self.run_command()
        self.assertEqual(Course.objects.count(), count)
        self.assertIn('0 added', output)

    def test_keeps_existing_course_ids_and_fixes_changed_names(self):
        old = Course.create_course('CS 110', 'Old name')
        self.run_command()
        old.refresh_from_db()
        self.assertEqual(old.course_name, 'Programming and Problem Solving')
        self.assertEqual(Course.objects.filter(course_code='CS 110').count(), 1)

#************************************************************************************************************************************************
#------------------------------------------------------- END OF LOAD COURSES TESTS ------------------------------------------------------------
#************************************************************************************************************************************************

