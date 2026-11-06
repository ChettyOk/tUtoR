from .models import Course
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
from .views import _update_tutor_profile


# tutor profile tests
from accounts.models import TutorProfile
from decimal import Decimal
from django.core.exceptions import ValidationError

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

# registration tests
class RegisterViewTests(TestCase):
    def test_register_creates_user(self):
        response = self.client.post(reverse("register"), {
            "email": "new@example.com",
            "password": "testpass123",
        })

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.check_password("testpass123"))

    def test_register_rejects_invalid_email(self):
        response = self.client.post(reverse("register"), {
            "email": "not-an-email",
            "password": "testpass123",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json()["errors"])

    def test_register_rejects_short_password(self):
        response = self.client.post(reverse("register"), {
            "email": "new@example.com",
            "password": "short",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json()["errors"])

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(
            email="existing@example.com",
            password="testpass123",
        )

        response = self.client.post(reverse("register"), {
            "email": "EXISTING@example.com",
            "password": "anotherpass123",
        })

        self.assertEqual(response.status_code, 409)

class AuthenticationViewTests(TestCase):
    def setUp(self):
        self.password = "testpass123"
        self.user = User.objects.create_user(
            email="test@example.com",
            password=self.password,
        )

    def test_login_creates_authenticated_session(self):
        response = self.client.post(reverse("login"), {
            "email": "test@example.com",
            "password": self.password,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.session.get("_auth_user_id"),
            str(self.user.pk),
        )

    def test_login_rejects_invalid_password(self):
        response = self.client.post(reverse("login"), {
            "email": "test@example.com",
            "password": "wrongpass123",
        })

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

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
        return _update_tutor_profile(request)

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

    def assert_account_unchanged(self):
        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, 'Marie')
        self.assertEqual(self.user.last_name, 'Example')
        self.assertEqual(self.user.phone, '123456')
        self.assertEqual(
            self.user.email,
            'cross-profile@example.com',
        )
        self.assertEqual(self.user.role, User.Role.STUDENT)
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
                'role': User.Role.TUTOR,
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

        self.assert_account_unchanged()
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

        self.assert_account_unchanged()
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
