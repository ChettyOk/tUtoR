from django.test import TestCase
from .models import Course
from django.urls import reverse
from django.db import IntegrityError, transaction
from django.core import mail
from django.test import override_settings
from urllib.parse import urlsplit

# user import
from django.test import SimpleTestCase, TestCase
from accounts.models import User, UserManager, StudentProfile
from .models import User

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

