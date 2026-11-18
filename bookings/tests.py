import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.db import connection, OperationalError
from django.test import Client, TestCase, TransactionTestCase, override_settings, RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.middleware.csrf import get_token
from django.core.exceptions import ValidationError

from accounts.models import Course, StudentProfile, TutorProfile, User
from bookings.models import Available_Slots, Booking, CancellationDeadlinePassedError, TutoringRequest, Rating, TutoringRequestInterest
from bookings.pricing import (
    DEFAULT_PRICE_GRAD,
    DEFAULT_PRICE_UNDERGRAD,
    MAX_PRICE,
    MIN_PRICE,
    calc_price_suggestion,
    custom_pricing,
)
from bookings.services import (
    DoubleBookingError,
    create_booking_request,
    get_tutor_available_slots,
    get_user_bookings,
    get_tutor_schedule,
    serialize_slot,
)
from tUtoR.views import custom_403, custom_500
from bookings.search import clean_filters, search_tutors

class Dummy_Slot: 
    objects = MagicMock()

class test_filter_courses_system(TestCase):
    
    def setUp(self):
        self.client = Client()
        self.course1 = Course.create_course('CS 101', 'Introduction to Computer Science')
        self.course2 = Course.create_course('CS 202', 'Data Structures')
        self.course3 = Course.create_course('ENER 101', 'Energy Systems')
        self.course4 = Course.create_course('CS476', 'Software Development Project')

    def test_search_query_all_courses(self):
        response = self.client.get(reverse('search'))
        self.assertEqual(response.status_code, 200) 
        self.assertEqual(response.context['courses'].count(), 4)
        available_faculties = response.context['available_faculties']
        self.assertIn('Science', available_faculties)
        self.assertIn('Engineering', available_faculties)

    def test_search_query_selcect_subject(self):
        response = self.client.get(reverse('search'), {'q': 'CS'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 3)
    
    def test_search_query_selcect_course(self):
        response = self.client.get(reverse('search'), {'q': 'CS 476'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 1) 
        self.assertEqual(response.context['courses'][0].course_code, "CS 476")   

    def test_search_course_name(self):
        response = self.client.get(reverse('search'), {'q': 'Software Development Project'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 1) 
        self.assertEqual(response.context['courses'][0].course_name, "Software Development Project")  

    def test_filter_faculty(self):
        response = self.client.get(reverse('search'), {'faculty': 'Science'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 3) 
        available_subjects = response.context['available_subjects']
        self.assertNotIn('ENER', available_subjects)
        self.assertIn('CS', available_subjects)

    def test_faculty_and_search_query(self):
        response = self.client.get(reverse('search'), {'faculty': 'Science', 'q': '476'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 1)
        self.assertEqual(response.context['courses'][0].course_code, "CS 476")

    def test_no_search_results(self):
        response = self.client.get(reverse('search'), {'q': '676767676767'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['courses'].count(), 0)

class Latency_tests(TestCase): 
    @classmethod
    def setUp(self):
        self.client = Client()
        courses = [Course(
                course_code=f"TEST {i:04d}",
                course_name=f"WoooooHOoooo {i}",
                course_faculty="Science" if i % 2 == 0 else "Engineering"
            )
            for i in range(1, 5001)
        ]
        Course.objects.bulk_create(courses)

    def test_search_latency(self):
   
        start_time = time.perf_counter()

        response = self.client.get(reverse('search'), {'q': 'CS', 'faculty': 'Science'})

        response_time = time.perf_counter() - start_time

        self.assertEqual(response.status_code, 200)
        self.assertLess(response_time, 1.0)

    def test_filter_latency(self):
        start_time = time.perf_counter()

        response = self.client.get(reverse('search'), {'faculty': 'Science'})

        response_time = time.perf_counter() - start_time

        self.assertEqual(response.status_code, 200)
        self.assertLess(response_time, 1.0)

class Test_pricing(TestCase):
    def setUp(self):
        self.undergrad_tutor = User.objects.create_user(email="ugrad@uregina.ca",password="67676AjdA!"
        )
        self.grad_tutor = User.objects.create_user(email="grad@uregina.ca",password="69ss69lH!"
        )
        self.grad_tutor.is_graduate = True

        # Available_Slots.objects.create(tutor=self.undergrad_tutor, session_price=Decimal('20.00'))
        # Available_Slots.objects.create(tutor=self.undergrad_tutor, session_price=Decimal('30.00'))

    def test_default_undergrad(self):
        price = calc_price_suggestion(self.undergrad_tutor)
        self.assertEqual(price, DEFAULT_PRICE_UNDERGRAD)

    def test_default_grad(self):
        price = calc_price_suggestion(self.grad_tutor)
        self.assertEqual(price, DEFAULT_PRICE_GRAD)

    def test_mean_calc(self):
        for days, price in ((2, '20.00'), (3, '30.00')):
            start = timezone.now() + timedelta(days=days)
            Available_Slots.create_slot(
                tutor=self.undergrad_tutor,
                start_time=start,
                end_time=start + timedelta(hours=1),
                price_per_hour=Decimal(price),
            )
        price = calc_price_suggestion(self.undergrad_tutor)
        self.assertEqual(price, Decimal('25.00'))

    def test_min_price(self):
        with self.assertRaises(ValueError) as ctx:
            custom_pricing('1.00')
        self.assertIn("Minimum price is $15.70/hour", str(ctx.exception))

    def test_max_price(self):
        with self.assertRaises(ValueError) as ctx:
            custom_pricing('151.00')
        self.assertIn("Maximum price is $150.00/hour", str(ctx.exception))

    def test_custom_pricing_valid(self):
        self.assertEqual(custom_pricing('25.50'), Decimal('25.50'))
        self.assertEqual(custom_pricing(25.5), Decimal('25.50'))
        with self.assertRaises(ValueError) as ctx:
            custom_pricing('xxx')
        self.assertIn("Price must be a valid number", str(ctx.exception))
        
User = get_user_model()      
class test_booking_model(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(email="student@uregina.ca", password="6767677jd!")
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="6767677jd!")
        self.course = Course.create_course("CS 476", "Software Engineering")

    def create_booking(self, status=Booking.Status.PENDING):
        return Booking.objects.create(student=self.student, tutor=self.tutor, course=self.course, student_note="WoHOOOOW", session_price=Decimal('30.00'), status=status)

    def test_booking_creation(self):
        booking = self.create_booking()
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.session_price, Decimal('30.00'))
        self.assertIsNotNone(booking.request_time)
        self.assertIn("student@uregina.ca", str(booking))
        self.assertIn("tutor@uregina.ca", str(booking))
        self.assertEqual(booking.course, self.course)

    def test_confirm(self):
        booking = self.create_booking()
        booking.confirm()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        with self.assertRaises(ValueError):
            booking.confirm()

    def test_cancel_student(self):
        booking = self.create_booking()
        booking.cancel(cancelled_by='student', reason='Fortnite')
        self.assertEqual(booking.status, Booking.Status.CANCELLED_STUDENT)
        self.assertEqual(booking.cancellation_reason, 'Fortnite')
        self.assertIsNotNone(booking.cancel_time)

    def test_cancel_after_deadline(self):
        booking = self.create_booking()

        start_time = timezone.now() + timedelta(hours=3)

        slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
            price_per_hour=Decimal('25.00'),
        )

        booking.time_slot = slot
        booking.save(update_fields=['time_slot'])

        with self.assertRaises(CancellationDeadlinePassedError):
            booking.cancel(
                cancelled_by='student',
                reason='Cannot attend.',
            )

        booking.refresh_from_db()
        slot.refresh_from_db()

        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertIsNone(booking.cancel_time)
        self.assertEqual(
            slot.status,
            Available_Slots.Status.AVAILABLE,
        )

    def test_cancel_tutor(self):
        booking = self.create_booking()
        booking.cancel(cancelled_by='tutor', reason='kein bock')
        self.assertEqual(booking.status, Booking.Status.CANCELLED_TUTOR)
        self.assertEqual(booking.cancellation_reason, 'kein bock')

    def test_cancel_error(self):
        booking = self.create_booking()
        booking.cancel(cancelled_by='student')
        with self.assertRaises(ValueError):
            booking.cancel(cancelled_by='tutor')
        booking2 = self.create_booking()
        with self.assertRaises(ValueError):
            booking2.cancel(cancelled_by='grandma')

    def test_completed(self):
        booking = self.create_booking()
        with self.assertRaises(ValueError):
            booking.completed()
        booking.confirm()
        booking.completed()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)
        self.assertIsNotNone(booking.complete_time)

    def test_calc_price_per_session(self):
        start_time = datetime(2026, 11, 1, 14, 0, 0)
        end_time = datetime(2026, 11, 1, 15, 30, 0) # = 1,5h
        price = Booking.calc_price_per_session(Decimal('20.00'), start_time, end_time)
        self.assertEqual(price, Decimal('30.00'))
        with self.assertRaises(ValueError):
            Booking.calc_price_per_session(Decimal('20.00'), end_time, start_time)

    def test_unblock_booking(self):
        booking = self.create_booking()
        booking.unblock_booking()  

class test_create_booking(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(email="student@uregina.ca", password="67676767!jffhH")
        self.student2 = User.objects.create_user(email="student2@uregina.ca", password="676767jjJJ!")
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="67676767!jffhH")
        self.course1 = Course.create_course("ENER 202", "Energy")
        self.course2 = Course.create_course("CS 476", "SW-Project")
        self.course3 = Course.create_course("CS 477", "SW-Project2")
        # can be replaced with actual available_slot funciton once available
        self.mock_slot = Dummy_Slot()
        self.mock_slot.id = 1
        self.mock_slot.status = 'available'
        self.mock_slot.price_per_hour = Decimal('20.00')
        self.mock_slot.start_time = datetime(2026, 11, 1, 14, 0, 0)
        self.mock_slot.end_time = datetime(2026, 11, 1, 15, 30, 0) #1,5h
        self.mock_slot.save = MagicMock()
        Dummy_Slot.objects.select_for_update.return_value.get.return_value = self.mock_slot 

    def test_create_booking(self):
        booking = create_booking_request(
            student=self.student,
            tutor=self.tutor,
            slot=self.mock_slot,
            course=self.course1,
            student_note="Hilfeeeeeeeeeeeeeeeee wipfi kann nicht erklären")
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.session_price, Decimal('30.00'))
        self.assertEqual(self.mock_slot.status, 'booked')
        self.mock_slot.save.assert_called_once()

    def test_double_booking_protection(self):
        self.mock_slot.status = 'booked'
        with self.assertRaises(DoubleBookingError):
            create_booking_request(
                student=self.student,
                tutor=self.tutor,
                slot=self.mock_slot,
                course=self.course1,
                student_note="Hilfeeeeeeeeeeeeeeeee wipfi kann nicht erklären")
    
    def test_get_user_bookings(self):
        Booking.objects.create(student=self.student, tutor=self.tutor, course=self.course1, session_price=Decimal('20.00'))
        Booking.objects.create(student=self.student, tutor=self.tutor, course=self.course2, session_price=Decimal('25.00'))
        Booking.objects.create(student=self.tutor, tutor=self.student, course=self.course3, session_price=Decimal('30.00'))

        user_bookings = get_user_bookings(self.student)
        self.assertEqual(user_bookings['student_bookings'].count(), 2)
        self.assertEqual(user_bookings['tutor_bookings'].count(), 1)
        self.assertEqual(user_bookings['all_bookings'].count(), 3)
        self.assertEqual(user_bookings['tutor_bookings'].first().course, self.course3)

class test_ratings_system(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='student@uregina.ca',
            password='676767hhG!',
            first_name='Tim',
            last_name='Peter',
        )
        self.tutor = User.objects.create_user(
            email='tutor@uregina.ca',
            password='676767hhG!',
            first_name='Sara',
            last_name='kkdfjh',
        )
        self.other_user = User.objects.create_user(
            email='stranger@uregina.ca',
            password='676767hhG!',
        )
        self.tutor_profile = TutorProfile.objects.create(
            user=self.tutor,
            bio='jaaaaa',
        )
        self.course = Course.create_course('CS 476', 'sw dev Project')

        self.completed_booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            session_price=Decimal('25.00'),
            status=Booking.Status.COMPLETED,
        )
        self.pending_booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            session_price=Decimal('25.00'),
            status=Booking.Status.PENDING,
        )

    def test_submit_rating(self):
        self.client.force_login(self.student)
        url = reverse('submit_rating', kwargs={'booking_id': self.completed_booking.id})
        response = self.client.post(url, {'stars': 5, 'comment': 'tolllllll!'})
        self.assertEqual(response.status_code, 201)

        booking2 = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            session_price=Decimal('25.00'),
            status=Booking.Status.COMPLETED,
        )
        url2 = reverse('submit_rating', kwargs={'booking_id': booking2.id})
        self.client.post(url2, {'stars': 4, 'comment': 'Sehr gut'})

        self.tutor_profile.refresh_from_db()
        self.assertEqual(self.tutor_profile.average_rating, Decimal('4.50'))

        list_url = reverse('tutor_ratings', kwargs={'user_id': self.tutor.id})
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, 200)
        data = list_res.json()
        self.assertEqual(data['average_rating'], '4.50')
        self.assertEqual(len(data['ratings']), 2)

    def test_rate_incomplete_booking(self):
        self.client.force_login(self.student)
        url = reverse('submit_rating', kwargs={'booking_id': self.pending_booking.id})
        response = self.client.post(url, {'stars': 5})
        self.assertEqual(response.status_code, 400)

    def test_rate_twice(self):
        self.client.force_login(self.student)
        url = reverse('submit_rating', kwargs={'booking_id': self.completed_booking.id})
        self.client.post(url, {'stars': 5})
        response_second = self.client.post(url, {'stars': 3})
        self.assertEqual(response_second.status_code, 400)

    def test_stars_onetofive(self):
        self.client.force_login(self.student)
        url = reverse('submit_rating', kwargs={'booking_id': self.completed_booking.id})
        response = self.client.post(url, {'stars': 6})
        self.assertEqual(response.status_code, 400)

    def test_stranger_rateiong(self):
        self.client.force_login(self.other_user)
        url = reverse('submit_rating', kwargs={'booking_id': self.completed_booking.id})
        response = self.client.post(url, {'stars': 1})
        self.assertEqual(response.status_code, 403)

    def test_rate_student(self):
        student_profile = StudentProfile.objects.create(user=self.student)
        self.client.force_login(self.tutor)
        url = reverse('submit_rating', kwargs={'booking_id': self.completed_booking.id})
        response = self.client.post(url, {'stars': 5, 'comment': 'Subba student!'})
        self.assertEqual(response.status_code, 201)

        student_profile.refresh_from_db()
        self.assertEqual(student_profile.average_rating, Decimal('5.00'))

        list_url = reverse('student_ratings', kwargs={'user_id': self.student.id})
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()['average_rating'], '5.00')
        self.assertEqual(len(list_res.json()['ratings']), 1)

@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class test_custom_error_handler(TestCase):
    def test_404_html(self):
        response = self.client.get('/this-url-does-not-exist-12345/')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'404', response.content)

    def test_404_json(self):
        response = self.client.get(
            '/this-url-does-not-exist-12345/',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.json())

    def test_403_json(self):
        response = custom_403(None)
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'403', response.content)

    def test_500_json(self):
        response = custom_500(None)
        self.assertEqual(response.status_code, 500)
        self.assertIn(b'500', response.content)

class test_tutor_details(TestCase):
    def setUp(self):
        self.tutor_user = User.objects.create_user(
            email='tutor@uregina.ca',
            password='676767hhH""!',
            first_name='Dieter',
            last_name='Smith',
        )
        self.normal_user = User.objects.create_user(
            email='student@uregina.ca',
            password='Password1d23!',
            first_name='Bob',
            last_name='Maier',
        )
        self.course_with_tutor = Course.create_course('CS 476', 'Software Development Project')
        self.course_without_tutor = Course.create_course('Ener 258', 'energie I')

        self.tutor_profile = TutorProfile.objects.create(
            user=self.tutor_user,
            bio='Wat is Elektrotechnik',
            average_rating=Decimal('1.00'),
        )
        self.tutor_profile.courses_passed.add(self.course_with_tutor)

    def test_filter_courses_with_tutor(self):
        response = self.client.get(reverse('search'), {'has_tutor': 'true'})
        self.assertEqual(response.status_code, 200)
        courses = list(response.context['courses'])
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0].course_code, 'CS 476')

    def test_get_tutor_details_view(self):
        url = reverse('tutor_details', kwargs={'user_id': self.tutor_user.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()['tutor']
        self.assertEqual(data['first_name'], 'Dieter')
        self.assertEqual(data['bio'], 'Wat is Elektrotechnik')
        self.assertEqual(data['average_rating'], '1.00')
        self.assertEqual(len(data['courses_passed']), 1)
        self.assertEqual(data['courses_passed'][0]['course_code'], 'CS 476')

    def test_get_student_details_view(self):
        student_profile = StudentProfile.objects.create(user=self.normal_user, major='CS', semester=3,average_rating=Decimal('4.50'),)
        student_profile.courses.add(self.course_with_tutor)
        url = reverse('student_details', kwargs={'user_id': self.normal_user.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()['student']
        self.assertEqual(data['first_name'], 'Bob')
        self.assertEqual(data['major'], 'CS')
        self.assertEqual(data['semester'], 3)
        self.assertEqual(data['average_rating'], '4.50')
        self.assertEqual(len(data['courses']), 1)

    def test_get_tutor_details_error(self):
        url = reverse('tutor_details', kwargs={'user_id': self.normal_user.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_get_tutor_slots_view(self):
        url = reverse('tutor_slots', kwargs={'tutor_id': self.tutor_user.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tutor_id'], self.tutor_user.id)
        self.assertEqual(data['available_slots'], [])

class test_booking_views(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User.objects.create_user(email="student@uregina.ca", password="676767jdUUh!")
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="6767ihihsIHGH!")
        self.course = Course.create_course("CS 476", "SW dev")
        self.booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            session_price=Decimal('25.00'),
            status=Booking.Status.CONFIRMED,
        )

    def test_get_bookings_no_login(self):
        response = self.client.get(reverse('my_bookings'))
        self.assertEqual(response.status_code, 401)

    def test_get_bookings(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('my_bookings'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['student_bookings']), 1)
        self.assertEqual(data['student_bookings'][0]['id'], self.booking.id)

    def test_cancel_booking_student(self):
        self.client.force_login(self.student)
        url = reverse('cancel_booking', kwargs={'booking_id': self.booking.id})
        response = self.client.post(url, {'reason': 'Kein bock mehr auf leben'})
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED_STUDENT)
        self.assertEqual(self.booking.cancellation_reason, 'Kein bock mehr auf leben')

class test_available_slots_model(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="67676767jdUU!")
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)

    def create_slot(self, **kwargs):
        data = {
            'tutor': self.tutor,
            'start_time': self.start,
            'end_time': self.end,
            'price_per_hour': Decimal('20.00'),
        }
        data.update(kwargs)
        return Available_Slots.create_slot(**data)

    def test_create_slot(self):
        slot = self.create_slot()
        self.assertEqual(slot.status, Available_Slots.Status.AVAILABLE)
        self.assertEqual(slot.location_type, Available_Slots.LocationType.ONLINE)
        self.assertEqual(slot.price_per_hour, Decimal('20.00'))
        self.assertEqual(Available_Slots.objects.count(), 1)

    def test_create_slot_in_person(self):
        slot = self.create_slot(location_type=Available_Slots.LocationType.IN_PERSON)
        self.assertEqual(slot.location_type, 'in_person')

    def test_create_slot_invalid_location(self):
        with self.assertRaises(ValueError):
            self.create_slot(location_type='mars')
        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_create_slot_missing_price(self):
        with self.assertRaises(ValueError):
            self.create_slot(price_per_hour=None)

    def test_is_available(self):
        slot = self.create_slot()
        self.assertTrue(slot.is_available())

    def test_is_available_booked(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.BOOKED
        self.assertFalse(slot.is_available())

    def test_is_available_cancelled(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.CANCELLED
        self.assertFalse(slot.is_available())

    def test_is_available_started(self):
        slot = self.create_slot()
        slot.start_time = timezone.now() - timedelta(hours=2)
        slot.end_time = timezone.now() - timedelta(hours=1)
        self.assertFalse(slot.is_available())

    def test_update_slot(self):
        slot = self.create_slot()
        new_end = self.end + timedelta(hours=1)
        slot.update_slot(end_time=new_end, price_per_hour=Decimal('25.00'))
        slot.refresh_from_db()
        self.assertEqual(slot.end_time, new_end)
        self.assertEqual(slot.price_per_hour, Decimal('25.00'))

    def test_update_slot_location(self):
        slot = self.create_slot()
        slot.update_slot(location_type=Available_Slots.LocationType.IN_PERSON)
        slot.refresh_from_db()
        self.assertEqual(slot.location_type, Available_Slots.LocationType.IN_PERSON)

    def test_update_slot_booked(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.BOOKED
        slot.save()
        with self.assertRaises(ValueError):
            slot.update_slot(price_per_hour=Decimal('30.00'))
        slot.refresh_from_db()
        self.assertEqual(slot.price_per_hour, Decimal('20.00'))

    def test_update_slot_cancelled(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.CANCELLED
        slot.save()
        with self.assertRaises(ValueError):
            slot.update_slot(price_per_hour=Decimal('30.00'))

    def test_update_slot_status_not_allowed(self):
        slot = self.create_slot()
        with self.assertRaises(ValueError):
            slot.update_slot(status=Available_Slots.Status.BOOKED)
        slot.refresh_from_db()
        self.assertEqual(slot.status, Available_Slots.Status.AVAILABLE)

    def test_update_slot_invalid_value_keeps_old_values(self):
        slot = self.create_slot()
        with self.assertRaises(ValueError):
            slot.update_slot(location_type='mars')
        self.assertEqual(slot.location_type, Available_Slots.LocationType.ONLINE)
        slot.refresh_from_db()
        self.assertEqual(slot.location_type, Available_Slots.LocationType.ONLINE)

    def test_cancel_slot(self):
        slot = self.create_slot()
        slot.cancel_slot()
        slot.refresh_from_db()
        self.assertEqual(slot.status, Available_Slots.Status.CANCELLED)
        self.assertFalse(slot.is_available())

    def test_cancel_slot_twice(self):
        slot = self.create_slot()
        slot.cancel_slot()
        with self.assertRaises(ValueError):
            slot.cancel_slot()

    def test_cancel_slot_booked(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.BOOKED
        slot.save()
        with self.assertRaises(ValueError):
            slot.cancel_slot()
        slot.refresh_from_db()
        self.assertEqual(slot.status, Available_Slots.Status.BOOKED)

    def test_create_slot_end_before_start(self):
        with self.assertRaises(ValueError) as ctx:
            self.create_slot(end_time=self.start - timedelta(hours=1))
        self.assertIn("End time must be after start time.", str(ctx.exception))
        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_create_slot_end_equals_start(self):
        with self.assertRaises(ValueError) as ctx:
            self.create_slot(end_time=self.start)
        self.assertIn("End time must be after start time.", str(ctx.exception))

    def test_create_slot_start_in_past(self):
        start = timezone.now() - timedelta(hours=2)
        with self.assertRaises(ValueError) as ctx:
            self.create_slot(start_time=start, end_time=start + timedelta(hours=1))
        self.assertIn("Start time must be in the future.", str(ctx.exception))
        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_create_slot_naive_datetimes(self):
        start = timezone.make_naive(timezone.now() + timedelta(days=2))
        slot = self.create_slot(start_time=start, end_time=start + timedelta(hours=1))
        self.assertTrue(timezone.is_aware(slot.start_time))
        self.assertTrue(timezone.is_aware(slot.end_time))

    def test_create_slot_invalid_start_time(self):
        with self.assertRaises(ValueError):
            self.create_slot(start_time='not a date')

    def test_create_slot_missing_end_time(self):
        with self.assertRaises(ValueError):
            self.create_slot(end_time=None)

    def test_overlap_same_time(self):
        first = self.create_slot()
        with self.assertRaises(ValueError) as ctx:
            self.create_slot()
        self.assertIn("overlaps with another of your slots", str(ctx.exception))
        self.assertIn(timezone.localtime(first.start_time).strftime('%Y-%m-%d %H:%M'), str(ctx.exception))
        self.assertEqual(Available_Slots.objects.count(), 1)

    def test_overlap_new_slot_starts_inside(self):
        self.create_slot()
        with self.assertRaises(ValueError):
            self.create_slot(start_time=self.start + timedelta(minutes=30), end_time=self.end + timedelta(minutes=30))

    def test_overlap_new_slot_ends_inside(self):
        self.create_slot()
        with self.assertRaises(ValueError):
            self.create_slot(start_time=self.start - timedelta(minutes=30), end_time=self.end - timedelta(minutes=30))

    def test_overlap_new_slot_inside_existing(self):
        self.create_slot()
        with self.assertRaises(ValueError):
            self.create_slot(start_time=self.start + timedelta(minutes=15), end_time=self.end - timedelta(minutes=15))

    def test_overlap_new_slot_surrounds_existing(self):
        self.create_slot()
        with self.assertRaises(ValueError):
            self.create_slot(start_time=self.start - timedelta(minutes=30), end_time=self.end + timedelta(minutes=30))

    def test_adjacent_slots_allowed(self):
        self.create_slot()
        self.create_slot(start_time=self.end, end_time=self.end + timedelta(hours=1))
        self.create_slot(start_time=self.start - timedelta(hours=1), end_time=self.start)
        self.assertEqual(Available_Slots.objects.count(), 3)

    def test_overlap_other_tutor_allowed(self):
        other_tutor = User.objects.create_user(email="tutor2@uregina.ca", password="67676767jdUU!")
        self.create_slot()
        self.create_slot(tutor=other_tutor)
        self.assertEqual(Available_Slots.objects.count(), 2)

    def test_overlap_cancelled_slot_allowed(self):
        slot = self.create_slot()
        slot.cancel_slot()
        self.create_slot()
        self.assertEqual(Available_Slots.objects.count(), 2)

    def test_overlap_booked_slot_blocks(self):
        slot = self.create_slot()
        slot.status = Available_Slots.Status.BOOKED
        slot.save()
        with self.assertRaises(ValueError):
            self.create_slot()

    def test_update_slot_does_not_overlap_itself(self):
        slot = self.create_slot()
        new_end = self.end + timedelta(minutes=30)
        slot.update_slot(end_time=new_end)
        slot.refresh_from_db()
        self.assertEqual(slot.end_time, new_end)

    def test_update_slot_move_to_free_time(self):
        slot = self.create_slot()
        new_start = self.start + timedelta(days=1)
        slot.update_slot(start_time=new_start, end_time=new_start + timedelta(hours=1))
        slot.refresh_from_db()
        self.assertEqual(slot.start_time, new_start)

    def test_update_slot_into_other_slot_fails(self):
        self.create_slot()
        second = self.create_slot(start_time=self.end, end_time=self.end + timedelta(hours=1))
        with self.assertRaises(ValueError) as ctx:
            second.update_slot(start_time=self.start + timedelta(minutes=30))
        self.assertIn("overlaps with another of your slots", str(ctx.exception))
        self.assertEqual(second.start_time, self.end)
        second.refresh_from_db()
        self.assertEqual(second.start_time, self.end)

    def test_update_slot_into_cancelled_slot_time_allowed(self):
        cancelled = self.create_slot()
        cancelled.cancel_slot()
        other = self.create_slot(start_time=self.end + timedelta(hours=2), end_time=self.end + timedelta(hours=3))
        other.update_slot(start_time=self.start, end_time=self.end)
        other.refresh_from_db()
        self.assertEqual(other.start_time, self.start)

    def test_update_slot_end_before_start(self):
        slot = self.create_slot()
        with self.assertRaises(ValueError) as ctx:
            slot.update_slot(end_time=self.start - timedelta(minutes=1))
        self.assertIn("End time must be after start time.", str(ctx.exception))
        self.assertEqual(slot.end_time, self.end)

    def test_update_slot_start_in_past(self):
        slot = self.create_slot()
        with self.assertRaises(ValueError) as ctx:
            slot.update_slot(start_time=timezone.now() - timedelta(hours=1))
        self.assertIn("Start time must be in the future.", str(ctx.exception))
        slot.refresh_from_db()
        self.assertEqual(slot.start_time, self.start)

    def test_update_slot_naive_datetime(self):
        slot = self.create_slot()
        new_start = timezone.make_naive(self.start + timedelta(days=1))
        slot.update_slot(start_time=new_start, end_time=new_start + timedelta(hours=1))
        self.assertTrue(timezone.is_aware(slot.start_time))
        self.assertTrue(timezone.is_aware(slot.end_time))

class test_available_slots_interfaces(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="67676767jdUU!")
        self.other_tutor = User.objects.create_user(email="tutor2@uregina.ca", password="67676767jdUU!")
        self.student = User.objects.create_user(email="student@uregina.ca", password="67676767jdUU!")
        TutorProfile.objects.create(user=self.tutor, bio='WoooW')

    def create_slot(self, tutor=None, days=2, **kwargs):
        start = timezone.now() + timedelta(days=days)
        data = {
            'tutor': tutor or self.tutor,
            'start_time': start,
            'end_time': start + timedelta(hours=1),
            'price_per_hour': Decimal('20.00'),
        }
        data.update(kwargs)
        return Available_Slots.create_slot(**data)

    def test_status_values(self):
        self.assertEqual(Available_Slots.Status.AVAILABLE, 'available')
        self.assertEqual(Available_Slots.Status.BOOKED, 'booked')
        self.assertEqual(Available_Slots.Status.CANCELLED, 'cancelled')

    def test_tutor_related_name(self):
        self.create_slot()
        self.create_slot(days=3)
        self.assertEqual(self.tutor.available_slots.count(), 2)
        self.assertEqual(self.other_tutor.available_slots.count(), 0)

    def test_get_tutor_available_slots(self):
        later = self.create_slot(days=5)
        sooner = self.create_slot(days=2)
        later.refresh_from_db()
        sooner.refresh_from_db()

        slots = get_tutor_available_slots(self.tutor)

        self.assertEqual(len(slots), 2)
        self.assertEqual([slot['id'] for slot in slots], [sooner.id, later.id])
        self.assertEqual(slots[0]['start_time'], sooner.start_time.isoformat())
        self.assertEqual(slots[0]['end_time'], sooner.end_time.isoformat())
        self.assertEqual(slots[0]['price_per_hour'], '20.00')
        self.assertEqual(slots[0]['status'], 'available')

    def test_get_tutor_available_slots_hides_booked_and_cancelled(self):
        free = self.create_slot(days=2)
        booked = self.create_slot(days=3)
        cancelled = self.create_slot(days=4)
        booked.status = Available_Slots.Status.BOOKED
        booked.save()
        cancelled.cancel_slot()

        slots = get_tutor_available_slots(self.tutor)

        self.assertEqual([slot['id'] for slot in slots], [free.id])

    def test_get_tutor_available_slots_other_tutor(self):
        self.create_slot(tutor=self.other_tutor)
        self.assertEqual(get_tutor_available_slots(self.tutor), [])

    def test_tutor_slots_view(self):
        slot = self.create_slot()
        response = self.client.get(reverse('tutor_slots', kwargs={'tutor_id': self.tutor.id}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tutor_id'], self.tutor.id)
        self.assertEqual(len(data['available_slots']), 1)
        self.assertEqual(data['available_slots'][0]['id'], slot.id)

    def test_create_booking_request_with_real_slot(self):
        slot = self.create_slot()
        booking = create_booking_request(student=self.student, tutor=self.tutor, slot=slot)
        slot.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.session_price, Decimal('20.00'))
        self.assertEqual(slot.status, Available_Slots.Status.BOOKED)
        with self.assertRaises(DoubleBookingError):
            create_booking_request(student=self.student, tutor=self.tutor, slot=slot)

class test_tutor_schedule_services(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='schedule-tutor@uregina.ca',
            password='ScheduleTestPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-schedule-tutor@uregina.ca',
            password='ScheduleTestPassword123!',
            role=User.Role.TUTOR,
        )
        self.start = timezone.now() + timedelta(days=2)

    def create_slot(self, **kwargs):
        data = {
            'tutor': self.tutor,
            'start_time': self.start,
            'end_time': self.start + timedelta(hours=1),
            'price_per_hour': Decimal('25.50'),
            'location_type': Available_Slots.LocationType.IN_PERSON,
        }
        data.update(kwargs)
        return Available_Slots.create_slot(**data)

    def test_serialize_slot(self):
        slot = self.create_slot()
        slot.refresh_from_db()

        data = serialize_slot(slot)

        self.assertEqual(data, {
            'id': slot.id,
            'start_time': slot.start_time.isoformat(),
            'end_time': slot.end_time.isoformat(),
            'price_per_hour': '25.50',
            'location_type': Available_Slots.LocationType.IN_PERSON,
            'status': Available_Slots.Status.AVAILABLE,
        })

    def test_serialize_slot_preserves_timezone_information(self):
        slot = self.create_slot()

        data = serialize_slot(slot)
        parsed_start = datetime.fromisoformat(data['start_time'])
        parsed_end = datetime.fromisoformat(data['end_time'])

        self.assertTrue(timezone.is_aware(parsed_start))
        self.assertTrue(timezone.is_aware(parsed_end))
        self.assertEqual(parsed_start, slot.start_time)
        self.assertEqual(parsed_end, slot.end_time)

    def test_get_tutor_schedule_empty(self):
        slots = get_tutor_schedule(self.tutor)

        self.assertEqual(list(slots), [])

    def test_get_tutor_schedule_only_own_slots(self):
        own_slot = self.create_slot()
        self.create_slot(tutor=self.other_tutor)

        slots = get_tutor_schedule(self.tutor)

        self.assertEqual(list(slots), [own_slot])

    def test_get_tutor_schedule_ordered_by_start_time(self):
        later_slot = self.create_slot(
            start_time=self.start + timedelta(days=1),
            end_time=self.start + timedelta(days=1, hours=1),
        )
        earlier_slot = self.create_slot()

        slots = get_tutor_schedule(self.tutor)

        self.assertEqual(list(slots), [earlier_slot, later_slot])

    def test_get_tutor_schedule_includes_all_statuses(self):
        available_slot = self.create_slot()

        booked_slot = self.create_slot(
            start_time=self.start + timedelta(hours=2),
            end_time=self.start + timedelta(hours=3),
        )
        booked_slot.status = Available_Slots.Status.BOOKED
        booked_slot.save(update_fields=['status'])

        cancelled_slot = self.create_slot(
            start_time=self.start + timedelta(hours=4),
            end_time=self.start + timedelta(hours=5),
        )
        cancelled_slot.cancel_slot()

        slots = get_tutor_schedule(self.tutor)

        self.assertEqual(
            list(slots),
            [available_slot, booked_slot, cancelled_slot],
        )

    def test_get_tutor_schedule_same_start_ordered_by_id(self):
        cancelled_slot = self.create_slot()
        cancelled_slot.cancel_slot()
        available_slot = self.create_slot()

        slots = get_tutor_schedule(self.tutor)

        self.assertEqual(
            list(slots),
            [cancelled_slot, available_slot],
        )

class test_tutor_schedule_view(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='schedule-view-tutor@uregina.ca',
            password='ScheduleViewPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-schedule-view-tutor@uregina.ca',
            password='ScheduleViewPassword123!',
            role=User.Role.TUTOR,
        )
        self.student = User.objects.create_user(
            email='schedule-view-student@uregina.ca',
            password='ScheduleViewPassword123!',
            role=User.Role.STUDENT,
        )
        self.url = reverse('tutor_schedule')
        self.start = timezone.now() + timedelta(days=2)

    def create_slot(self, **kwargs):
        data = {
            'tutor': self.tutor,
            'start_time': self.start,
            'end_time': self.start + timedelta(hours=1),
            'price_per_hour': Decimal('25.50'),
            'location_type': Available_Slots.LocationType.ONLINE,
        }
        data.update(kwargs)
        return Available_Slots.create_slot(**data)

    def test_get_schedule_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {'error': 'Authentication required.'},
        )

    def test_student_cannot_get_schedule(self):
        self.client.force_login(self.student)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {'error': 'Your active role does not allow this action.'},
        )

    def test_user_without_role_cannot_get_schedule(self):
        self.tutor.role = ''
        self.tutor.save(update_fields=['role'])
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())

    def test_get_schedule_returns_own_slots(self):
        own_slot = self.create_slot()
        self.create_slot(tutor=self.other_tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        slots = response.json()['slots']
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['id'], own_slot.id)
        self.assertEqual(slots[0]['price_per_hour'], '25.50')
        self.assertEqual(
            slots[0]['location_type'],
            Available_Slots.LocationType.ONLINE,
        )
        self.assertEqual(
            slots[0]['status'],
            Available_Slots.Status.AVAILABLE,
        )
        self.assertEqual(
            datetime.fromisoformat(slots[0]['start_time']),
            own_slot.start_time,
        )
        self.assertEqual(
            datetime.fromisoformat(slots[0]['end_time']),
            own_slot.end_time,
        )

    def test_get_schedule_empty_without_tutor_profile(self):
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'slots': []})

    def test_get_schedule_ignores_tutor_id_parameter(self):
        own_slot = self.create_slot()
        self.create_slot(tutor=self.other_tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(
            self.url,
            {'tutor_id': self.other_tutor.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [slot['id'] for slot in response.json()['slots']],
            [own_slot.id],
        )

    def test_post_schedule_not_allowed(self):
        self.client.force_login(self.tutor)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'GET')

class test_create_slot_view(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='create-slot-tutor@uregina.ca',
            password='CreateSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-create-slot-tutor@uregina.ca',
            password='CreateSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.url = reverse('create_slot')
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)
        self.data = {
            'start_time': self.start.isoformat(),
            'end_time': self.end.isoformat(),
            'price_per_hour': '25.50',
            'location_type': Available_Slots.LocationType.IN_PERSON,
        }
        self.client.force_login(self.tutor)

    def test_get_returns_form_metadata(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data['suggested_price'],
            str(calc_price_suggestion(self.tutor)),
        )
        self.assertEqual(data['min_price'], str(MIN_PRICE))
        self.assertEqual(data['max_price'], str(MAX_PRICE))
        self.assertEqual(
            data['location_types'],
            [
                {'value': value, 'label': label}
                for value, label in Available_Slots.LocationType.choices
            ],
        )
        self.assertEqual(
            data['timezone'],
            timezone.get_current_timezone_name(),
        )
        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_create_slot(self):
        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, 201)
        slot = Available_Slots.objects.get()
        self.assertEqual(slot.tutor, self.tutor)
        self.assertEqual(slot.start_time, self.start)
        self.assertEqual(slot.end_time, self.end)
        self.assertEqual(slot.price_per_hour, Decimal('25.50'))
        self.assertEqual(
            slot.location_type,
            Available_Slots.LocationType.IN_PERSON,
        )
        self.assertEqual(slot.status, Available_Slots.Status.AVAILABLE)
        self.assertEqual(response.json()['slot']['id'], slot.id)

    def test_create_slot_defaults_to_online(self):
        data = self.data.copy()
        del data['location_type']

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Available_Slots.objects.get().location_type,
            Available_Slots.LocationType.ONLINE,
        )

    def test_missing_required_fields(self):
        for field in ('start_time', 'end_time', 'price_per_hour'):
            with self.subTest(field=field):
                data = self.data.copy()
                del data[field]

                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['error'])
                self.assertEqual(Available_Slots.objects.count(), 0)

    def test_empty_fields(self):
        for field in self.data:
            with self.subTest(field=field):
                data = {**self.data, field: ' '}

                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['error'])
                self.assertEqual(Available_Slots.objects.count(), 0)

    def test_invalid_datetime(self):
        for value in ('not-a-date', '2026-02-30T12:00'):
            with self.subTest(value=value):
                data = {**self.data, 'start_time': value}

                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertIn('start_time', response.json()['error'])
                self.assertEqual(Available_Slots.objects.count(), 0)

    def test_invalid_prices(self):
        for value in ('abc', 'NaN', 'Infinity', '1.00', '151.00'):
            with self.subTest(value=value):
                data = {**self.data, 'price_per_hour': value}

                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.assertEqual(Available_Slots.objects.count(), 0)

    def test_invalid_location_type(self):
        data = {**self.data, 'location_type': 'somewhere'}

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 400)
        self.assertIn('location_type', response.json()['error'])
        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_invalid_time_rules(self):
        cases = (
            {
                'end_time': (self.start - timedelta(minutes=1)).isoformat(),
            },
            {
                'start_time': (
                    timezone.now() - timedelta(hours=1)
                ).isoformat(),
            },
        )

        for changes in cases:
            with self.subTest(changes=changes):
                response = self.client.post(
                    self.url,
                    {**self.data, **changes},
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.assertEqual(Available_Slots.objects.count(), 0)

    def test_overlapping_slot_rejected(self):
        Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.start,
            end_time=self.end,
            price_per_hour=Decimal('25.50'),
        )

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, 400)
        self.assertIn('overlaps', response.json()['error'])
        self.assertEqual(Available_Slots.objects.count(), 1)

    def test_naive_times_use_current_timezone(self):
        naive_start = timezone.make_naive(self.start)
        naive_end = timezone.make_naive(self.end)
        data = {
            **self.data,
            'start_time': naive_start.isoformat(),
            'end_time': naive_end.isoformat(),
        }

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 201)
        slot = Available_Slots.objects.get()
        self.assertEqual(slot.start_time, self.start)
        self.assertEqual(slot.end_time, self.end)

    def test_client_cannot_set_owner_or_status(self):
        data = {
            **self.data,
            'tutor_id': self.other_tutor.id,
            'tutor': self.other_tutor.id,
            'status': Available_Slots.Status.BOOKED,
        }

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 201)
        slot = Available_Slots.objects.get()
        self.assertEqual(slot.tutor, self.tutor)
        self.assertEqual(slot.status, Available_Slots.Status.AVAILABLE)

    def test_requires_login(self):
        self.client.logout()

        for method in ('get', 'post'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url, self.data)

                self.assertEqual(response.status_code, 401)

        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_requires_tutor_role(self):
        for role in (User.Role.STUDENT, ''):
            self.tutor.role = role
            self.tutor.save(update_fields=['role'])

            for method in ('get', 'post'):
                with self.subTest(role=role, method=method):
                    response = getattr(self.client, method)(
                        self.url,
                        self.data,
                    )

                    self.assertEqual(response.status_code, 403)

        self.assertEqual(Available_Slots.objects.count(), 0)

    def test_delete_method_not_allowed(self):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 405)


class test_update_slot_view(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='update-slot-tutor@uregina.ca',
            password='UpdateSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-update-slot-tutor@uregina.ca',
            password='UpdateSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)

        self.slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.start,
            end_time=self.end,
            price_per_hour=Decimal('25.50'),
            location_type=Available_Slots.LocationType.ONLINE,
        )
        self.url = reverse(
            'update_slot',
            kwargs={'slot_id': self.slot.id},
        )
        self.client.force_login(self.tutor)

    def assert_slot_unchanged(self):
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.tutor_id, self.tutor.id)
        self.assertEqual(self.slot.start_time, self.start)
        self.assertEqual(self.slot.end_time, self.end)
        self.assertEqual(self.slot.price_per_hour, Decimal('25.50'))
        self.assertEqual(
            self.slot.location_type,
            Available_Slots.LocationType.ONLINE,
        )
        self.assertEqual(
            self.slot.status,
            Available_Slots.Status.AVAILABLE,
        )

    def test_get_returns_slot_and_metadata(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slot']['id'], self.slot.id)
        self.assertEqual(data['slot']['price_per_hour'], '25.50')
        self.assertEqual(data['min_price'], str(MIN_PRICE))
        self.assertEqual(data['max_price'], str(MAX_PRICE))
        self.assertEqual(
            data['location_types'],
            [
                {'value': value, 'label': label}
                for value, label in Available_Slots.LocationType.choices
            ],
        )
        self.assertEqual(
            data['timezone'],
            timezone.get_current_timezone_name(),
        )
        self.assert_slot_unchanged()

    def test_update_price_preserves_other_fields(self):
        response = self.client.post(
            self.url,
            {'price_per_hour': '30.00'},
        )

        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.price_per_hour, Decimal('30.00'))
        self.assertEqual(self.slot.start_time, self.start)
        self.assertEqual(self.slot.end_time, self.end)
        self.assertEqual(
            self.slot.location_type,
            Available_Slots.LocationType.ONLINE,
        )
        self.assertEqual(
            response.json()['slot']['price_per_hour'],
            '30.00',
        )

    def test_update_times_and_location(self):
        new_start = self.start + timedelta(days=1)
        new_end = new_start + timedelta(hours=2)

        response = self.client.post(self.url, {
            'start_time': new_start.isoformat(),
            'end_time': new_end.isoformat(),
            'location_type': Available_Slots.LocationType.IN_PERSON,
        })

        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time, new_start)
        self.assertEqual(self.slot.end_time, new_end)
        self.assertEqual(
            self.slot.location_type,
            Available_Slots.LocationType.IN_PERSON,
        )
        self.assertEqual(self.slot.price_per_hour, Decimal('25.50'))

    def test_empty_update_rejected(self):
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 400)
        self.assertIn('at least one', response.json()['error'])
        self.assert_slot_unchanged()

    def test_empty_fields_rejected(self):
        for field in Available_Slots.UPDATABLE_FIELDS:
            with self.subTest(field=field):
                response = self.client.post(
                    self.url,
                    {field: ''},
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['error'])
                self.assert_slot_unchanged()

    def test_invalid_price_rejected(self):
        for value in ('abc', 'NaN', 'Infinity', '1.00', '151.00'):
            with self.subTest(value=value):
                response = self.client.post(
                    self.url,
                    {'price_per_hour': value},
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.assert_slot_unchanged()

    def test_invalid_datetime_rejected(self):
        response = self.client.post(
            self.url,
            {'start_time': 'not-a-date'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('start_time', response.json()['error'])
        self.assert_slot_unchanged()

    def test_invalid_location_rejected(self):
        response = self.client.post(
            self.url,
            {'location_type': 'somewhere'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('location_type', response.json()['error'])
        self.assert_slot_unchanged()

    def test_invalid_time_rules_rejected(self):
        cases = (
            {
                'end_time': (self.start - timedelta(minutes=1)).isoformat(),
            },
            {
                'start_time': (
                    timezone.now() - timedelta(hours=1)
                ).isoformat(),
            },
        )

        for changes in cases:
            with self.subTest(changes=changes):
                response = self.client.post(self.url, changes)

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.assert_slot_unchanged()

    def test_overlapping_update_rejected(self):
        other_start = self.end + timedelta(hours=1)
        Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=other_start,
            end_time=other_start + timedelta(hours=1),
            price_per_hour=Decimal('20.00'),
        )

        response = self.client.post(self.url, {
            'end_time': (other_start + timedelta(minutes=30)).isoformat(),
            'price_per_hour': '30.00',
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('overlaps', response.json()['error'])
        self.assert_slot_unchanged()

    def test_booked_and_cancelled_slots_cannot_be_updated(self):
        for status in (
            Available_Slots.Status.BOOKED,
            Available_Slots.Status.CANCELLED,
        ):
            with self.subTest(status=status):
                self.slot.status = status
                self.slot.save(update_fields=['status'])

                response = self.client.post(
                    self.url,
                    {'price_per_hour': '30.00'},
                )

                self.assertEqual(response.status_code, 400)
                self.slot.refresh_from_db()
                self.assertEqual(self.slot.status, status)
                self.assertEqual(
                    self.slot.price_per_hour,
                    Decimal('25.50'),
                )

    def test_other_tutor_cannot_read_or_update_slot(self):
        self.client.force_login(self.other_tutor)

        for method in ('get', 'post'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {'price_per_hour': '30.00'},
                )

                self.assertEqual(response.status_code, 403)
                self.assertIn('error', response.json())
                self.assert_slot_unchanged()

    def test_unknown_slot_returns_json_404(self):
        missing_id = self.slot.id
        self.slot.delete()
        url = reverse('update_slot', kwargs={'slot_id': missing_id})

        for method in ('get', 'post'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    {'price_per_hour': '30.00'},
                )

                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    response.json(),
                    {'error': 'Slot not found.'},
                )

    def test_requires_login(self):
        self.client.logout()

        for method in ('get', 'post'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {'price_per_hour': '30.00'},
                )

                self.assertEqual(response.status_code, 401)

        self.assert_slot_unchanged()

    def test_requires_tutor_role(self):
        for role in (User.Role.STUDENT, ''):
            self.tutor.role = role
            self.tutor.save(update_fields=['role'])

            for method in ('get', 'post'):
                with self.subTest(role=role, method=method):
                    response = getattr(self.client, method)(
                        self.url,
                        {'price_per_hour': '30.00'},
                    )

                    self.assertEqual(response.status_code, 403)

        self.assert_slot_unchanged()

    def test_client_cannot_change_owner_or_status(self):
        response = self.client.post(self.url, {
            'price_per_hour': '30.00',
            'tutor_id': self.other_tutor.id,
            'tutor': self.other_tutor.id,
            'status': Available_Slots.Status.BOOKED,
        })

        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.price_per_hour, Decimal('30.00'))
        self.assertEqual(self.slot.tutor_id, self.tutor.id)
        self.assertEqual(
            self.slot.status,
            Available_Slots.Status.AVAILABLE,
        )

    def test_delete_method_not_allowed(self):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 405)
        self.assert_slot_unchanged()

class test_delete_slot_view(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='delete-slot-tutor@uregina.ca',
            password='DeleteSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-delete-slot-tutor@uregina.ca',
            password='DeleteSlotPassword123!',
            role=User.Role.TUTOR,
        )
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)

        self.slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.start,
            end_time=self.end,
            price_per_hour=Decimal('25.50'),
            location_type=Available_Slots.LocationType.ONLINE,
        )
        self.url = reverse(
            'delete_slot',
            kwargs={'slot_id': self.slot.id},
        )
        self.client.force_login(self.tutor)

    def assert_slot_status(self, expected_status):
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, expected_status)

    def test_cancel_available_slot(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['message'],
            'Slot cancelled successfully.',
        )
        self.assertEqual(
            response.json()['slot']['id'],
            self.slot.id,
        )
        self.assertEqual(
            response.json()['slot']['status'],
            Available_Slots.Status.CANCELLED,
        )

        self.assert_slot_status(Available_Slots.Status.CANCELLED)
        self.assertEqual(Available_Slots.objects.count(), 1)
        self.assertEqual(self.slot.tutor_id, self.tutor.id)
        self.assertEqual(self.slot.start_time, self.start)
        self.assertEqual(self.slot.end_time, self.end)
        self.assertEqual(self.slot.price_per_hour, Decimal('25.50'))
        self.assertEqual(
            self.slot.location_type,
            Available_Slots.LocationType.ONLINE,
        )

    def test_booked_slot_cannot_be_cancelled(self):
        self.slot.status = Available_Slots.Status.BOOKED
        self.slot.save(update_fields=['status'])

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'cancel the booking instead',
            response.json()['error'],
        )
        self.assert_slot_status(Available_Slots.Status.BOOKED)
        self.assertEqual(Available_Slots.objects.count(), 1)

    def test_already_cancelled_slot_rejected(self):
        self.slot.cancel_slot()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'already cancelled',
            response.json()['error'],
        )
        self.assert_slot_status(Available_Slots.Status.CANCELLED)
        self.assertEqual(Available_Slots.objects.count(), 1)

    def test_other_tutor_cannot_cancel_slot(self):
        self.client.force_login(self.other_tutor)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {'error': 'You can only cancel your own slots.'},
        )
        self.assert_slot_status(Available_Slots.Status.AVAILABLE)

    def test_unknown_slot_returns_json_404(self):
        missing_id = self.slot.id
        self.slot.delete()
        url = reverse(
            'delete_slot',
            kwargs={'slot_id': missing_id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {'error': 'Slot not found.'},
        )

    def test_requires_login(self):
        self.client.logout()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {'error': 'Authentication required.'},
        )
        self.assert_slot_status(Available_Slots.Status.AVAILABLE)

    def test_requires_tutor_role(self):
        for role in (User.Role.STUDENT, ''):
            self.tutor.role = role
            self.tutor.save(update_fields=['role'])

            with self.subTest(role=role):
                response = self.client.post(self.url)

                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json(),
                    {
                        'error': (
                            'Your active role does not allow this action.'
                        ),
                    },
                )
                self.assert_slot_status(
                    Available_Slots.Status.AVAILABLE,
                )

    def test_other_http_methods_not_allowed(self):
        for method in ('get', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)

                self.assertEqual(response.status_code, 405)
                self.assertEqual(
                    response.headers['Allow'],
                    'POST',
                )
                self.assert_slot_status(
                    Available_Slots.Status.AVAILABLE,
                )

    def test_request_data_cannot_redirect_cancellation(self):
        other_slot = Available_Slots.create_slot(
            tutor=self.other_tutor,
            start_time=self.start,
            end_time=self.end,
            price_per_hour=Decimal('30.00'),
        )

        response = self.client.post(self.url, {
            'slot_id': other_slot.id,
            'tutor_id': self.other_tutor.id,
            'status': Available_Slots.Status.AVAILABLE,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_slot_status(Available_Slots.Status.CANCELLED)
        other_slot.refresh_from_db()
        self.assertEqual(
            other_slot.status,
            Available_Slots.Status.AVAILABLE,
        )

class test_slot_management_workflow(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='slot-workflow-tutor@uregina.ca',
            password='SlotWorkflowPassword123!',
            role=User.Role.TUTOR,
        )
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)
        self.client.force_login(self.tutor)

    def test_create_list_update_and_cancel_slot(self):
        create_response = self.client.post(
            reverse('create_slot'),
            {
                'start_time': self.start.isoformat(),
                'end_time': self.end.isoformat(),
                'price_per_hour': '25.50',
                'location_type': Available_Slots.LocationType.ONLINE,
            },
        )

        self.assertEqual(create_response.status_code, 201)
        slot_id = create_response.json()['slot']['id']

        schedule_response = self.client.get(reverse('tutor_schedule'))

        self.assertEqual(schedule_response.status_code, 200)
        slots = schedule_response.json()['slots']
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['id'], slot_id)
        self.assertEqual(
            slots[0]['status'],
            Available_Slots.Status.AVAILABLE,
        )

        new_start = self.start + timedelta(days=1)
        new_end = new_start + timedelta(hours=1)

        update_response = self.client.post(
            reverse('update_slot', kwargs={'slot_id': slot_id}),
            {
                'start_time': new_start.isoformat(),
                'end_time': new_end.isoformat(),
                'price_per_hour': '30.00',
            },
        )

        self.assertEqual(update_response.status_code, 200)
        updated_slot = update_response.json()['slot']
        self.assertEqual(
            datetime.fromisoformat(updated_slot['start_time']),
            new_start,
        )
        self.assertEqual(
            datetime.fromisoformat(updated_slot['end_time']),
            new_end,
        )
        self.assertEqual(updated_slot['price_per_hour'], '30.00')
        self.assertEqual(
            updated_slot['location_type'],
            Available_Slots.LocationType.ONLINE,
        )

        cancel_response = self.client.post(
            reverse('delete_slot', kwargs={'slot_id': slot_id}),
        )

        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(
            cancel_response.json()['slot']['status'],
            Available_Slots.Status.CANCELLED,
        )

        final_response = self.client.get(reverse('tutor_schedule'))

        self.assertEqual(final_response.status_code, 200)
        final_slots = final_response.json()['slots']
        self.assertEqual(len(final_slots), 1)
        self.assertEqual(final_slots[0]['id'], slot_id)
        self.assertEqual(
            final_slots[0]['status'],
            Available_Slots.Status.CANCELLED,
        )
        self.assertEqual(final_slots[0]['price_per_hour'], '30.00')

        slot = Available_Slots.objects.get(pk=slot_id)
        self.assertEqual(slot.tutor_id, self.tutor.id)
        self.assertEqual(slot.start_time, new_start)
        self.assertEqual(slot.end_time, new_end)
        self.assertEqual(slot.status, Available_Slots.Status.CANCELLED)

@override_settings(
    CSRF_USE_SESSIONS=False,
    CSRF_COOKIE_NAME='csrftoken',
    CSRF_HEADER_NAME='HTTP_X_CSRFTOKEN',
)
class test_slot_management_csrf(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email='slot-csrf-tutor@uregina.ca',
            password='SlotCsrfPassword123!',
            role=User.Role.TUTOR,
        )
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=1)

        self.slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.start,
            end_time=self.end,
            price_per_hour=Decimal('25.50'),
        )

        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.tutor)

        self.create_data = {
            'start_time': (
                self.start + timedelta(days=1)
            ).isoformat(),
            'end_time': (
                self.end + timedelta(days=1)
            ).isoformat(),
            'price_per_hour': '30.00',
        }

    def add_csrf_cookie(self):
        request = RequestFactory().get('/')
        token = get_token(request)
        self.client.cookies['csrftoken'] = request.META['CSRF_COOKIE']
        return token

    def test_post_without_token_rejected(self):
        self.add_csrf_cookie()

        requests = (
            (reverse('create_slot'), self.create_data),
            (
                reverse(
                    'update_slot',
                    kwargs={'slot_id': self.slot.id},
                ),
                {'price_per_hour': '30.00'},
            ),
            (
                reverse(
                    'delete_slot',
                    kwargs={'slot_id': self.slot.id},
                ),
                {},
            ),
        )

        for url, data in requests:
            with self.subTest(url=url):
                response = self.client.post(url, data)

                self.assertEqual(response.status_code, 403)

        self.slot.refresh_from_db()
        self.assertEqual(Available_Slots.objects.count(), 1)
        self.assertEqual(self.slot.price_per_hour, Decimal('25.50'))
        self.assertEqual(self.slot.status, Available_Slots.Status.AVAILABLE)

    def test_create_with_csrf_header_allowed(self):
        token = self.add_csrf_cookie()

        response = self.client.post(
            reverse('create_slot'),
            self.create_data,
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Available_Slots.objects.count(), 2)

    def test_update_with_csrf_header_allowed(self):
        token = self.add_csrf_cookie()

        response = self.client.post(
            reverse('update_slot', kwargs={'slot_id': self.slot.id}),
            {'price_per_hour': '30.00'},
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.price_per_hour, Decimal('30.00'))

    def test_cancel_with_csrf_form_field_allowed(self):
        token = self.add_csrf_cookie()

        response = self.client.post(
            reverse('delete_slot', kwargs={'slot_id': self.slot.id}),
            {'csrfmiddlewaretoken': token},
        )

        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, Available_Slots.Status.CANCELLED)


class test_double_booking(TransactionTestCase):
    def setUp(self):
        self.student1 = User.objects.create_user(email="stud1@uregina.ca", password="67676969ahshG!")
        self.student2 = User.objects.create_user(email="stud2@uregina.ca", password="67676969ahshG!")
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="67676969ahshG!", role=User.Role.TUTOR)
        self.start = timezone.now() + timedelta(days=2)

    def test_simultaneous_booking(self):
        slot = Available_Slots.create_slot(
            tutor=self.tutor,
            price_per_hour=Decimal('20.00'),
            start_time=self.start,
            end_time=self.start + timedelta(hours=1),
        )
        results, errors = [], []
        barrier = threading.Barrier(2)

        def book_slot(user):
            connection.close()
            barrier.wait()
            try:
                results.append(create_booking_request(student=user, tutor=self.tutor, slot=slot))
            except (DoubleBookingError, OperationalError) as e:
                errors.append(e)

        t1 = threading.Thread(target=book_slot, args=(self.student1,))
        t2 = threading.Thread(target=book_slot, args=(self.student2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)


class test_slot_booking_and_completion(TestCase):
    def setUp(self):
        self.student1 = User.objects.create_user(email="stud1@uregina.ca", password="67676969ahshG!", role=User.Role.STUDENT)
        self.student2 = User.objects.create_user(email="stud2@uregina.ca", password="67676969ahshG!", role=User.Role.STUDENT)
        self.tutor = User.objects.create_user(email="tutor@uregina.ca", password="67676969ahshG!", role=User.Role.TUTOR)
        self.course = Course.create_course("CS 476", "SW eng")
        self.start = timezone.now() + timedelta(days=2)
        self.slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.start,
            end_time=self.start + timedelta(hours=3),
            price_per_hour=Decimal('20.00'),
            location_type=Available_Slots.LocationType.ONLINE,
        )

    def test_partial_overlap_and_remaining_timeslot(self):
        booking = create_booking_request(
            student=self.student1,
            tutor=self.tutor,
            slot=self.slot,
            course=self.course,
            start_time=self.start + timedelta(hours=1),
            end_time=self.start + timedelta(hours=2),
        )
        self.slot.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.session_price, Decimal('20.00'))
        self.assertEqual(self.slot.status, Available_Slots.Status.AVAILABLE)

        with self.assertRaises(DoubleBookingError):
            create_booking_request(
                student=self.student2,
                tutor=self.tutor,
                slot=self.slot,
                start_time=self.start + timedelta(hours=1, minutes=30),
                end_time=self.start + timedelta(hours=2, minutes=30),
            )

        remaining = get_tutor_available_slots(self.tutor)
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[0]['location_type'], Available_Slots.LocationType.ONLINE)
        self.assertEqual(remaining[0]['end_time'], (self.start + timedelta(hours=1)).isoformat())
        self.assertEqual(remaining[1]['start_time'], (self.start + timedelta(hours=2)).isoformat())

    def test_cancel_by_tutor_slot_available(self):
        full = create_booking_request(student=self.student1, tutor=self.tutor, slot=self.slot)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, Available_Slots.Status.BOOKED)

        full.cancel(cancelled_by='tutor', reason='Sick')
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, Available_Slots.Status.AVAILABLE)

    def test_book_slot(self):
        self.client.force_login(self.student1)
        book_url = reverse('book_slot', kwargs={'slot_id': self.slot.id})

        res1 = self.client.post(book_url, {
            'start_time': (self.start + timedelta(hours=1)).isoformat(),
            'end_time': (self.start + timedelta(hours=2)).isoformat(),
        })
        self.assertEqual(res1.status_code, 201)
        booking_id = res1.json()['booking_id']

        res_conflict = self.client.post(book_url, {
            'start_time': (self.start + timedelta(hours=1)).isoformat(),
            'end_time': (self.start + timedelta(hours=2)).isoformat(),
        })
        self.assertEqual(res_conflict.status_code, 409)

        complete_url = reverse('complete_booking', kwargs={'booking_id': booking_id})
        self.client.force_login(self.student2)
        self.assertEqual(self.client.post(complete_url).status_code, 403)

        self.client.force_login(self.tutor)
        self.assertEqual(self.client.post(complete_url).status_code, 400)

        past_booking = Booking.objects.create(student=self.student1, tutor=self.tutor, time_slot=self.slot, start_time=timezone.now() - timedelta(hours=2), end_time=timezone.now() - timedelta(hours=1), session_price=Decimal('20.00'), status=Booking.Status.CONFIRMED,)
        past_complete_url = reverse('complete_booking', kwargs={'booking_id': past_booking.id})
        self.assertEqual(self.client.post(past_complete_url).status_code, 200)
        past_booking.refresh_from_db()
        self.assertEqual(past_booking.status, Booking.Status.COMPLETED)

    def test_update_cancel_slot_with_partial_booking(self):
        create_booking_request(student=self.student1, tutor=self.tutor, slot=self.slot, start_time=self.start + timedelta(hours=1), end_time=self.start + timedelta(hours=2),)
        with self.assertRaises(ValueError):
            self.slot.update_slot(
                start_time=self.start + timedelta(hours=3),
                end_time=self.start + timedelta(hours=5),
            )
        with self.assertRaises(ValueError):
            self.slot.cancel_slot()

    def test_ongoing_slot_still_returns_future_window(self):
        ongoing = Available_Slots(tutor=self.tutor, start_time=timezone.now() - timedelta(hours=1), end_time=timezone.now() + timedelta(hours=2), price_per_hour=Decimal('20.00'),)
        ongoing.save()
        slots = get_tutor_available_slots(self.tutor)
        ongoing_entries = [s for s in slots if s['id'] == ongoing.id]
        self.assertEqual(len(ongoing_entries), 1)


class test_booking_session_details(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='session-student@uregina.ca',
            password='RequestTestPassword123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='session-tutor@uregina.ca',
            password='RequestTestPassword123!',
            role=User.Role.TUTOR,
        )

        self.window_start = timezone.now() + timedelta(days=2)

        self.slot = Available_Slots.create_slot(
            tutor=self.tutor,
            start_time=self.window_start,
            end_time=self.window_start + timedelta(hours=3),
            price_per_hour=Decimal('25.00'),
        )

        self.booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            time_slot=self.slot,
            start_time=self.window_start + timedelta(hours=1),
            end_time=self.window_start + timedelta(hours=2),
            price_per_hour=Decimal('25.00'),
            location_type=Available_Slots.LocationType.ONLINE,
            session_price=Decimal('25.00'),
            status=Booking.Status.PENDING,
        )

    def test_session_details_are_persisted(self):
        self.booking.refresh_from_db()

        self.assertEqual(self.booking.time_slot_id, self.slot.id)
        self.assertEqual(
            self.booking.start_time,
            self.window_start + timedelta(hours=1),
        )
        self.assertEqual(
            self.booking.end_time,
            self.window_start + timedelta(hours=2),
        )
        self.assertEqual(self.booking.price_per_hour, Decimal('25.00'))
        self.assertEqual(
            self.booking.location_type,
            Available_Slots.LocationType.ONLINE,
        )

    def test_cancellation_uses_session_start_not_window_start(self):
        self.slot.start_time = timezone.now() + timedelta(hours=2)
        self.slot.end_time = timezone.now() + timedelta(hours=8)
        self.slot.save()

        self.booking.start_time = timezone.now() + timedelta(hours=6)
        self.booking.end_time = timezone.now() + timedelta(hours=7)
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.save()

        self.booking.cancel(cancelled_by='student')

        self.booking.refresh_from_db()
        self.assertEqual(
            self.booking.status,
            Booking.Status.CANCELLED_STUDENT,
        )

    def test_student_cannot_cancel_inside_session_deadline(self):
        self.booking.start_time = timezone.now() + timedelta(hours=2)
        self.booking.end_time = timezone.now() + timedelta(hours=3)
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.save()

        with self.assertRaises(CancellationDeadlinePassedError):
            self.booking.cancel(cancelled_by='student')

        self.booking.refresh_from_db()
        self.assertEqual(
            self.booking.status,
            Booking.Status.CONFIRMED,
        )

    def test_session_cancellation_does_not_change_window_status(self):
        self.slot.status = Available_Slots.Status.CANCELLED
        self.slot.save(update_fields=['status'])

        self.booking.cancel(cancelled_by='tutor')

        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.status,
            Available_Slots.Status.CANCELLED,
        )

class TutoringRequestCreationViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='request-view-student@uregina.ca',
            password='RequestViewTest123!',
            role=User.Role.STUDENT,
        )

        self.tutor = User.objects.create_user(
            email='request-view-tutor@uregina.ca',
            password='RequestViewTest123!',
            role=User.Role.TUTOR,
        )

        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )

        self.url = reverse('create_request')
        self.data = {
            'course_id': self.course.pk,
            'description': 'Please help me understand Django models.',
        }

        self.client.force_login(self.student)

    def assert_rejected(self, data, expected_status=400):
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()

        response = self.client.post(self.url, data)

        self.assertEqual(
            response.status_code,
            expected_status,
            msg=response.content.decode(),
        )
        self.assertIn('error', response.json())
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

        return response

    def test_creates_open_request_without_tutor_or_slot(self):
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()
        slot_count = Available_Slots.objects.count()

        response = self.client.post(self.url, self.data)

        self.assertEqual(
            response.status_code,
            201,
            msg=response.content.decode(),
        )

        data = response.json()
        tutoring_request = TutoringRequest.objects.get(
            pk=data['request_id'],
        )

        self.assertEqual(
            data,
            {
                'message': 'Tutoring request published.',
                'request_id': tutoring_request.pk,
                'status': TutoringRequest.Status.OPEN,
            },
        )
        self.assertNotIn('booking_id', data)
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count + 1,
        )
        self.assertEqual(tutoring_request.student, self.student)
        self.assertEqual(tutoring_request.course, self.course)
        self.assertEqual(
            tutoring_request.description,
            self.data['description'],
        )
        self.assertEqual(
            tutoring_request.location_type,
            TutoringRequest.LocationType.FLEXIBLE,
        )
        self.assertEqual(
            tutoring_request.visibility,
            TutoringRequest.Visibility.ALL_TUTORS,
        )
        self.assertEqual(Booking.objects.count(), booking_count)
        self.assertEqual(Available_Slots.objects.count(), slot_count)

    def test_saves_selected_options_and_trims_description(self):
        response = self.client.post(
            self.url,
            {
                **self.data,
                'description': '  Help me with Django.  ',
                'location_type': TutoringRequest.LocationType.ONLINE,
                'visibility': TutoringRequest.Visibility.ALL_TUTORS,
            },
        )

        self.assertEqual(
            response.status_code,
            201,
            msg=response.content.decode(),
        )

        tutoring_request = TutoringRequest.objects.get(
            pk=response.json()['request_id'],
        )

        self.assertEqual(
            tutoring_request.description,
            'Help me with Django.',
        )
        self.assertEqual(
            tutoring_request.location_type,
            TutoringRequest.LocationType.ONLINE,
        )
        self.assertEqual(
            tutoring_request.visibility,
            TutoringRequest.Visibility.ALL_TUTORS,
        )

    def test_requires_login(self):
        self.client.logout()

        self.assert_rejected(self.data, expected_status=401)

    def test_requires_active_student_role(self):
        self.client.force_login(self.tutor)

        self.assert_rejected(self.data, expected_status=403)

    def test_rejects_get(self):
        request_count = TutoringRequest.objects.count()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'POST')
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )

    def test_course_id_is_required(self):
        data = self.data.copy()
        del data['course_id']

        self.assert_rejected(data)

    def test_invalid_course_ids_are_rejected(self):
        for course_id in ('', 'abc', '0', '-1', '1.5'):
            with self.subTest(course_id=course_id):
                self.assert_rejected(
                    {
                        **self.data,
                        'course_id': course_id,
                    },
                )

    def test_unknown_course_is_rejected(self):
        missing_id = self.course.pk
        self.course.delete()

        self.assert_rejected(
            {
                **self.data,
                'course_id': missing_id,
            },
            expected_status=404,
        )

    def test_description_is_required(self):
        data = self.data.copy()
        del data['description']

        self.assert_rejected(data)

    def test_invalid_descriptions_are_rejected(self):
        for description in ('', '   ', 'x' * 2001):
            with self.subTest(length=len(description)):
                self.assert_rejected(
                    {
                        **self.data,
                        'description': description,
                    },
                )

    def test_invalid_options_are_rejected(self):
        for field in ('location_type', 'visibility'):
            for value in ('', 'invalid'):
                with self.subTest(field=field, value=value):
                    self.assert_rejected(
                        {
                            **self.data,
                            field: value,
                        },
                    )

    def test_student_and_status_cannot_be_overridden(self):
        response = self.client.post(
            self.url,
            {
                **self.data,
                'student_id': self.tutor.pk,
                'status': TutoringRequest.Status.FULFILLED,
            },
        )

        self.assertEqual(
            response.status_code,
            201,
            msg=response.content.decode(),
        )

        tutoring_request = TutoringRequest.objects.get(
            pk=response.json()['request_id'],
        )

        self.assertEqual(tutoring_request.student, self.student)
        self.assertEqual(
            tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

class TutoringRequestModelTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='request-model-student@uregina.ca',
            password='RequestModelTest123!',
            role=User.Role.STUDENT,
        )

        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )

    def make_request(self, **overrides):
        fields = {
            'student': self.student,
            'course': self.course,
            'description': 'I need help preparing for the final exam.',
        }
        fields.update(overrides)
        return TutoringRequest(**fields)

    def test_request_can_be_saved_without_tutor_or_slot(self):
        booking_count = Booking.objects.count()
        tutoring_request = self.make_request()

        tutoring_request.full_clean()
        tutoring_request.save()
        tutoring_request.refresh_from_db()

        self.assertEqual(tutoring_request.student, self.student)
        self.assertEqual(tutoring_request.course, self.course)
        self.assertEqual(
            tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )
        self.assertEqual(
            tutoring_request.visibility,
            TutoringRequest.Visibility.ALL_TUTORS,
        )
        self.assertEqual(
            tutoring_request.location_type,
            TutoringRequest.LocationType.FLEXIBLE,
        )
        self.assertIsNotNone(tutoring_request.created_at)
        self.assertEqual(Booking.objects.count(), booking_count)

    def test_description_is_required(self):
        tutoring_request = self.make_request(description='')

        with self.assertRaises(ValidationError) as context:
            tutoring_request.full_clean()

        self.assertIn('description', context.exception.message_dict)

    def test_description_length_is_limited(self):
        tutoring_request = self.make_request(description='x' * 2001)

        with self.assertRaises(ValidationError) as context:
            tutoring_request.full_clean()

        self.assertIn('description', context.exception.message_dict)

    def test_invalid_choices_are_rejected(self):
        invalid_values = {
            'status': 'invalid',
            'visibility': 'invalid',
            'location_type': 'invalid',
        }

        for field, value in invalid_values.items():
            with self.subTest(field=field):
                tutoring_request = self.make_request(**{field: value})

                with self.assertRaises(ValidationError) as context:
                    tutoring_request.full_clean()

                self.assertIn(field, context.exception.message_dict)

    def test_course_is_required(self):
        tutoring_request = self.make_request(course=None)

        with self.assertRaises(ValidationError) as context:
            tutoring_request.full_clean()

        self.assertIn('course', context.exception.message_dict)

class StudentTutoringRequestViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='request-owner@uregina.ca',
            password='RequestOwnerTest123!',
            role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            email='other-request-owner@uregina.ca',
            password='RequestOwnerTest123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='request-owner-tutor@uregina.ca',
            password='RequestOwnerTest123!',
            role=User.Role.TUTOR,
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.tutoring_request = self.make_request()
        self.list_url = reverse('my_tutoring_requests')
        self.client.force_login(self.student)

    def make_request(self, **overrides):
        fields = {
            'student': self.student,
            'course': self.course,
            'description': 'Please help me understand Django.',
        }
        fields.update(overrides)
        return TutoringRequest.objects.create(**fields)

    def detail_url(self, request_id):
        return reverse(
            'my_tutoring_request',
            kwargs={'request_id': request_id},
        )

    def withdraw_url(self, request_id):
        return reverse(
            'withdraw_tutoring_request',
            kwargs={'request_id': request_id},
        )

    def endpoint_calls(self):
        return (
            ('get', self.list_url),
            ('get', self.detail_url(self.tutoring_request.pk)),
            ('post', self.withdraw_url(self.tutoring_request.pk)),
        )

    def test_list_contains_only_own_requests_in_newest_first_order(self):
        newer_request = self.make_request()
        self.make_request(student=self.other_student)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                item['request_id']
                for item in response.json()['requests']
            ],
            [newer_request.pk, self.tutoring_request.pk],
        )

    def test_list_includes_withdrawn_and_fulfilled_requests(self):
        withdrawn = self.make_request(
            status=TutoringRequest.Status.WITHDRAWN,
        )
        fulfilled = self.make_request(
            status=TutoringRequest.Status.FULFILLED,
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {
                item['request_id']
                for item in response.json()['requests']
            },
            {
                self.tutoring_request.pk,
                withdrawn.pk,
                fulfilled.pk,
            },
        )

    def test_list_is_empty_without_own_requests(self):
        self.client.force_login(self.other_student)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'requests': []})

    def test_detail_returns_own_request(self):
        response = self.client.get(
            self.detail_url(self.tutoring_request.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'request': {
                    'request_id': self.tutoring_request.pk,
                    'course_id': self.course.pk,
                    'course': str(self.course),
                    'description': self.tutoring_request.description,
                    'location_type': (
                        TutoringRequest.LocationType.FLEXIBLE
                    ),
                    'visibility': (
                        TutoringRequest.Visibility.ALL_TUTORS
                    ),
                    'status': TutoringRequest.Status.OPEN,
                    'created_at': (
                        self.tutoring_request.created_at.isoformat()
                    ),
                },
            },
        )

    def test_other_students_request_cannot_be_read_or_withdrawn(self):
        other_request = self.make_request(
            student=self.other_student,
        )

        responses = (
            self.client.get(self.detail_url(other_request.pk)),
            self.client.post(self.withdraw_url(other_request.pk)),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404)

        other_request.refresh_from_db()
        self.assertEqual(
            other_request.status,
            TutoringRequest.Status.OPEN,
        )

    def test_unknown_request_returns_404(self):
        request_id = self.tutoring_request.pk
        self.tutoring_request.delete()

        responses = (
            self.client.get(self.detail_url(request_id)),
            self.client.post(self.withdraw_url(request_id)),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404)

    def test_owner_can_withdraw_open_request(self):
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()

        response = self.client.post(
            self.withdraw_url(self.tutoring_request.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'message': 'Tutoring request withdrawn.',
                'request_id': self.tutoring_request.pk,
                'status': TutoringRequest.Status.WITHDRAWN,
            },
        )

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.WITHDRAWN,
        )
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

    def test_non_open_requests_cannot_be_withdrawn(self):
        for status in (
            TutoringRequest.Status.WITHDRAWN,
            TutoringRequest.Status.FULFILLED,
        ):
            with self.subTest(status=status):
                self.tutoring_request.status = status
                self.tutoring_request.save(update_fields=['status'])

                response = self.client.post(
                    self.withdraw_url(self.tutoring_request.pk),
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.tutoring_request.refresh_from_db()
                self.assertEqual(
                    self.tutoring_request.status,
                    status,
                )

    def test_all_endpoints_require_login(self):
        self.client.logout()

        for method, url in self.endpoint_calls():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 401)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

    def test_all_endpoints_require_active_student_role(self):
        self.client.force_login(self.tutor)

        for method, url in self.endpoint_calls():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

    def test_endpoints_reject_wrong_http_methods(self):
        calls = (
            ('post', self.list_url),
            ('post', self.detail_url(self.tutoring_request.pk)),
            ('get', self.withdraw_url(self.tutoring_request.pk)),
        )

        for method, url in calls:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 405)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

class TutoringRequestFormViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='request-form-student@uregina.ca',
            password='RequestFormTest123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='request-form-tutor@uregina.ca',
            password='RequestFormTest123!',
            first_name='Alex',
            last_name='Tutor',
            role=User.Role.TUTOR,
        )
        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.other_course = Course.create_course(
            'CS 477',
            'Another Computer Science Course',
        )
        self.tutor_profile = TutorProfile.objects.create(
            user=self.tutor,
        )

        self.url = reverse('tutoring_request_form')
        self.client.force_login(self.student)

    def get_form(self, course=None):
        data = {}

        if course is not None:
            data['course_id'] = course.pk

        return self.client.get(self.url, data)

    def post_request(self):
        return self.client.post(
            reverse('create_request'),
            {
                'course_id': self.course.pk,
                'description': 'Please help me understand Django.',
            },
        )

    def test_returns_form_metadata_without_course_selection(self):
        response = self.get_form()

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(
            data['courses'],
            [
                {
                    'id': course.pk,
                    'course_code': course.course_code,
                    'course_name': course.course_name,
                    'course_faculty': course.course_faculty,
                }
                for course in (self.course, self.other_course)
            ],
        )
        self.assertEqual(
            data['location_types'],
            [
                {'value': value, 'label': label}
                for value, label in TutoringRequest.LocationType.choices
            ],
        )
        self.assertEqual(
            data['visibility_options'],
            [
                {
                    'value': TutoringRequest.Visibility.ALL_TUTORS,
                    'label': (
                        TutoringRequest.Visibility.ALL_TUTORS.label
                    ),
                },
            ],
        )
        self.assertEqual(data['description_max_length'], 2000)
        self.assertIsNone(data['selected_course_id'])
        self.assertIsNone(data['can_create_request'])
        self.assertEqual(data['existing_tutors'], [])

    def test_allows_course_without_existing_tutors(self):
        response = self.get_form(self.course)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['selected_course_id'],
            self.course.pk,
        )
        self.assertIs(response.json()['can_create_request'], True)
        self.assertEqual(response.json()['existing_tutors'], [])

    def test_existing_tutor_blocks_course_without_requiring_slots(self):
        self.tutor_profile.courses_passed.add(self.course)

        response = self.get_form(self.course)

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()['can_create_request'], False)
        self.assertEqual(
            response.json()['existing_tutors'],
            [
                {
                    'tutor_id': self.tutor.pk,
                    'first_name': 'Alex',
                    'last_name': 'Tutor',
                },
            ],
        )

    def test_tutor_for_different_course_does_not_block(self):
        self.tutor_profile.courses_passed.add(self.other_course)

        response = self.get_form(self.course)

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()['can_create_request'], True)
        self.assertEqual(response.json()['existing_tutors'], [])

    def test_own_tutor_profile_does_not_block(self):
        profile = TutorProfile.objects.create(user=self.student)
        profile.courses_passed.add(self.course)

        form_response = self.get_form(self.course)
        self.assertEqual(form_response.status_code, 200)
        self.assertIs(
            form_response.json()['can_create_request'],
            True,
        )

        create_response = self.post_request()

        self.assertEqual(
            create_response.status_code,
            201,
            msg=create_response.content.decode(),
        )

    def test_inactive_tutor_does_not_block(self):
        self.tutor_profile.courses_passed.add(self.course)
        self.tutor.is_active = False
        self.tutor.save(update_fields=['is_active'])

        form_response = self.get_form(self.course)
        self.assertEqual(form_response.status_code, 200)
        self.assertIs(
            form_response.json()['can_create_request'],
            True,
        )

        create_response = self.post_request()

        self.assertEqual(
            create_response.status_code,
            201,
            msg=create_response.content.decode(),
        )

    def test_tutor_role_switch_does_not_remove_course_offer(self):
        self.tutor_profile.courses_passed.add(self.course)
        self.tutor.switch_role(User.Role.STUDENT)
        self.tutor.save(update_fields=['role'])

        form_response = self.get_form(self.course)
        self.assertEqual(form_response.status_code, 200)
        self.assertIs(
            form_response.json()['can_create_request'],
            False,
        )

        create_response = self.post_request()

        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(TutoringRequest.objects.count(), 0)

    def test_direct_creation_is_blocked_without_form_check(self):
        self.tutor_profile.courses_passed.add(self.course)
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()

        response = self.post_request()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                'error': (
                    'Tutors already offer this course. '
                    'Please view the existing tutors instead.'
                ),
            },
        )
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

    def test_creation_rechecks_offers_after_form_was_loaded(self):
        form_response = self.get_form(self.course)

        self.assertEqual(form_response.status_code, 200)
        self.assertIs(
            form_response.json()['can_create_request'],
            True,
        )

        self.tutor_profile.courses_passed.add(self.course)

        response = self.post_request()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TutoringRequest.objects.count(), 0)

    def test_creation_is_allowed_without_existing_tutors(self):
        response = self.post_request()

        self.assertEqual(
            response.status_code,
            201,
            msg=response.content.decode(),
        )

        tutoring_request = TutoringRequest.objects.get(
            pk=response.json()['request_id'],
        )

        self.assertEqual(tutoring_request.student, self.student)
        self.assertEqual(tutoring_request.course, self.course)
        self.assertEqual(
            tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

    def test_invalid_course_ids_are_rejected(self):
        for course_id in ('', 'abc', '0', '-1', '1.5'):
            with self.subTest(course_id=course_id):
                response = self.client.get(
                    self.url,
                    {'course_id': course_id},
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())

    def test_unknown_course_is_rejected(self):
        missing_id = self.other_course.pk
        self.other_course.delete()

        response = self.client.get(
            self.url,
            {'course_id': missing_id},
        )

        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        self.client.logout()

        response = self.get_form()

        self.assertEqual(response.status_code, 401)

    def test_requires_active_student_role(self):
        self.client.force_login(self.tutor)

        response = self.get_form()

        self.assertEqual(response.status_code, 403)

    def test_rejects_post(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'GET')

    def test_reading_form_does_not_create_requests_or_bookings(self):
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()

        response = self.get_form(self.course)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

class TutoringRequestForumViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='forum-view-student@uregina.ca',
            password='ForumViewTest123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='forum-view-tutor@uregina.ca',
            password='ForumViewTest123!',
            role=User.Role.TUTOR,
        )
        TutorProfile.objects.create(user=self.tutor)

        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.tutoring_request = self.make_request()

        self.url = reverse('incoming_requests')
        self.client.force_login(self.tutor)

    def make_request(self, **overrides):
        fields = {
            'student': self.student,
            'course': self.course,
            'description': 'Please help me understand Django.',
            'status': TutoringRequest.Status.OPEN,
            'visibility': TutoringRequest.Visibility.ALL_TUTORS,
        }
        fields.update(overrides)

        return TutoringRequest.objects.create(**fields)

    def response_ids(self, response):
        self.assertEqual(
            response.status_code,
            200,
            msg=response.content.decode(),
        )
        return [
            item['request_id']
            for item in response.json()['open_requests']
        ]

    def test_returns_open_requests_without_matching_tutor_courses(self):
        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_returns_expected_request_fields(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'open_requests': [
                    {
                        'request_id': self.tutoring_request.pk,
                        'course_id': self.course.pk,
                        'course': str(self.course),
                        'description': (
                            self.tutoring_request.description
                        ),
                        'location_type': (
                            TutoringRequest.LocationType.FLEXIBLE
                        ),
                        'visibility': (
                            TutoringRequest.Visibility.ALL_TUTORS
                        ),
                        'status': TutoringRequest.Status.OPEN,
                        'created_at': (
                            self.tutoring_request.created_at.isoformat()
                        ),
                    },
                ],
            },
        )

    def test_returns_newest_requests_first(self):
        newer_request = self.make_request()

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [newer_request.pk, self.tutoring_request.pk],
        )

    def test_excludes_withdrawn_and_fulfilled_requests(self):
        self.make_request(
            status=TutoringRequest.Status.WITHDRAWN,
        )
        self.make_request(
            status=TutoringRequest.Status.FULFILLED,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_excludes_own_requests(self):
        self.make_request(student=self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_excludes_existing_faculty_restricted_requests(self):
        self.make_request(
            visibility=TutoringRequest.Visibility.COURSE_FACULTY,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_returns_requests_for_different_course_faculties(self):
        engineering_course = Course.objects.create(
            course_code='ENGR 101',
            course_name='Engineering Basics',
            course_faculty='Engineering',
        )
        other_request = self.make_request(
            course=engineering_course,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            set(self.response_ids(response)),
            {self.tutoring_request.pk, other_request.pk},
        )

    def test_does_not_include_legacy_booking_requests(self):
        Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            student_note='Legacy booking request.',
            session_price=Decimal('25.00'),
            status=Booking.Status.PENDING,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_returns_empty_list_without_visible_requests(self):
        self.tutoring_request.status = (
            TutoringRequest.Status.WITHDRAWN
        )
        self.tutoring_request.save(update_fields=['status'])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'open_requests': []})

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)
        self.assertIn('error', response.json())

    def test_rejects_active_student_role(self):
        self.client.force_login(self.student)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())

    def test_rejects_user_without_active_role(self):
        self.tutor.role = ''
        self.tutor.save(update_fields=['role'])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())

    def test_rejects_post(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'GET')

    def test_ignores_tutor_id_query_parameter(self):
        response = self.client.get(
            self.url,
            {'tutor_id': self.student.pk},
        )

        self.assertEqual(
            self.response_ids(response),
            [self.tutoring_request.pk],
        )

    def test_listing_does_not_change_requests_or_bookings(self):
        request_count = TutoringRequest.objects.count()
        booking_count = Booking.objects.count()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

class TutoringRequestInterestViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='interest-student@uregina.ca',
            password='InterestViewTest123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='interest-tutor@uregina.ca',
            password='InterestViewTest123!',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='other-interest-tutor@uregina.ca',
            password='InterestViewTest123!',
            role=User.Role.TUTOR,
        )
        TutorProfile.objects.create(user=self.tutor)
        TutorProfile.objects.create(user=self.other_tutor)

        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.tutoring_request = TutoringRequest.objects.create(
            student=self.student,
            course=self.course,
            description='Please help me understand Django.',
        )

        self.interest_url = reverse(
            'express_tutoring_request_interest',
            kwargs={'request_id': self.tutoring_request.pk},
        )
        self.withdraw_url = reverse(
            'withdraw_tutoring_request_interest',
            kwargs={'request_id': self.tutoring_request.pk},
        )

        self.client.force_login(self.tutor)

    def test_tutor_can_express_interest_without_matching_courses(self):
        response = self.client.post(self.interest_url)

        self.assertEqual(
            response.status_code,
            201,
            msg=response.content.decode(),
        )
        self.assertEqual(
            response.json(),
            {
                'message': 'Interest recorded.',
                'request_id': self.tutoring_request.pk,
                'interested': True,
            },
        )
        self.assertTrue(
            TutoringRequestInterest.objects.filter(
                tutoring_request=self.tutoring_request,
                tutor=self.tutor,
            ).exists()
        )

    def test_repeated_interest_does_not_create_duplicates(self):
        first_response = self.client.post(self.interest_url)
        second_response = self.client.post(self.interest_url)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(TutoringRequestInterest.objects.count(), 1)

    def test_multiple_tutors_can_express_interest(self):
        first_response = self.client.post(self.interest_url)

        self.client.force_login(self.other_tutor)
        second_response = self.client.post(self.interest_url)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(
            set(
                self.tutoring_request.interests.values_list(
                    'tutor_id',
                    flat=True,
                )
            ),
            {self.tutor.pk, self.other_tutor.pk},
        )

    def test_tutor_can_withdraw_own_interest(self):
        self.client.post(self.interest_url)

        response = self.client.post(self.withdraw_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'message': 'Interest withdrawn.',
                'request_id': self.tutoring_request.pk,
                'interested': False,
                'removed': True,
            },
        )
        self.assertFalse(
            TutoringRequestInterest.objects.filter(
                tutoring_request=self.tutoring_request,
                tutor=self.tutor,
            ).exists()
        )

    def test_withdrawal_preserves_other_tutors_interest(self):
        self.client.post(self.interest_url)
        other_interest = TutoringRequestInterest.objects.create(
            tutoring_request=self.tutoring_request,
            tutor=self.other_tutor,
        )

        response = self.client.post(self.withdraw_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            TutoringRequestInterest.objects.filter(
                pk=other_interest.pk,
            ).exists()
        )
        self.assertEqual(TutoringRequestInterest.objects.count(), 1)

    def test_withdrawal_without_interest_is_safe(self):
        response = self.client.post(self.withdraw_url)

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()['removed'], False)
        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_interest_can_be_expressed_again_after_withdrawal(self):
        self.client.post(self.interest_url)
        self.client.post(self.withdraw_url)

        response = self.client.post(self.interest_url)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(TutoringRequestInterest.objects.count(), 1)

    def test_closed_requests_reject_new_interest(self):
        for status in (
            TutoringRequest.Status.WITHDRAWN,
            TutoringRequest.Status.FULFILLED,
        ):
            with self.subTest(status=status):
                self.tutoring_request.status = status
                self.tutoring_request.save(update_fields=['status'])

                response = self.client.post(self.interest_url)

                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                self.assertEqual(
                    TutoringRequestInterest.objects.count(),
                    0,
                )

    def test_interest_can_be_withdrawn_after_request_closes(self):
        self.client.post(self.interest_url)
        self.tutoring_request.status = (
            TutoringRequest.Status.WITHDRAWN
        )
        self.tutoring_request.save(update_fields=['status'])

        response = self.client.post(self.withdraw_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_own_request_cannot_receive_own_interest(self):
        self.tutoring_request.student = self.tutor
        self.tutoring_request.save(update_fields=['student'])

        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 404)

        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_restricted_request_is_not_accessible(self):
        self.tutoring_request.visibility = (
            TutoringRequest.Visibility.COURSE_FACULTY
        )
        self.tutoring_request.save(update_fields=['visibility'])

        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 404)

        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_unknown_request_returns_404(self):
        self.tutoring_request.delete()

        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        self.client.logout()

        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 401)

        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_requires_active_tutor_role(self):
        self.client.force_login(self.student)

        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 403)

        self.assertEqual(TutoringRequestInterest.objects.count(), 0)

    def test_rejects_get(self):
        for url in (self.interest_url, self.withdraw_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.headers['Allow'], 'POST')

    def test_client_cannot_choose_another_tutor(self):
        response = self.client.post(
            self.interest_url,
            {'tutor_id': self.other_tutor.pk},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            TutoringRequestInterest.objects.get().tutor,
            self.tutor,
        )

    def test_interest_actions_do_not_book_or_reserve(self):
        booking_count = Booking.objects.count()
        slot_count = Available_Slots.objects.count()

        create_response = self.client.post(self.interest_url)
        withdraw_response = self.client.post(self.withdraw_url)

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(withdraw_response.status_code, 200)
        self.assertEqual(Booking.objects.count(), booking_count)
        self.assertEqual(Available_Slots.objects.count(), slot_count)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )

class InterestedTutorsViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='interest-list-owner@uregina.ca',
            password='InterestListTest123!',
            role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            email='interest-list-other-student@uregina.ca',
            password='InterestListTest123!',
            role=User.Role.STUDENT,
        )
        self.tutor = User.objects.create_user(
            email='interest-list-tutor@uregina.ca',
            password='InterestListTest123!',
            first_name='Alex',
            last_name='Tutor',
            role=User.Role.TUTOR,
        )
        self.other_tutor = User.objects.create_user(
            email='interest-list-other-tutor@uregina.ca',
            password='InterestListTest123!',
            first_name='Sam',
            last_name='Tutor',
            role=User.Role.TUTOR,
        )

        TutorProfile.objects.create(user=self.tutor)
        TutorProfile.objects.create(user=self.other_tutor)

        self.course = Course.create_course(
            'CS 476',
            'Software Development Project',
        )
        self.tutoring_request = TutoringRequest.objects.create(
            student=self.student,
            course=self.course,
            description='Please help me understand Django.',
        )

        self.url = reverse(
            'interested_tutors',
            kwargs={'request_id': self.tutoring_request.pk},
        )
        self.client.force_login(self.student)

    def make_interest(self, **overrides):
        fields = {
            'tutoring_request': self.tutoring_request,
            'tutor': self.tutor,
        }
        fields.update(overrides)

        return TutoringRequestInterest.objects.create(**fields)

    def response_tutor_ids(self, response):
        self.assertEqual(
            response.status_code,
            200,
            msg=response.content.decode(),
        )
        return [
            item['tutor_id']
            for item in response.json()['interested_tutors']
        ]

    def test_owner_can_see_interested_tutor(self):
        interest = self.make_interest()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'request_id': self.tutoring_request.pk,
                'status': TutoringRequest.Status.OPEN,
                'interested_tutors': [
                    {
                        'tutor_id': self.tutor.pk,
                        'first_name': 'Alex',
                        'last_name': 'Tutor',
                        'interested_since': (
                            interest.created_at.isoformat()
                        ),
                        'profile_url': reverse(
                            'tutor_details',
                            kwargs={'user_id': self.tutor.pk},
                        ),
                        'availability_url': reverse(
                            'tutor_slots',
                            kwargs={'tutor_id': self.tutor.pk},
                        ),
                    },
                ],
            },
        )

    def test_returns_multiple_tutors_in_interest_order(self):
        self.make_interest()
        self.make_interest(tutor=self.other_tutor)

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_tutor_ids(response),
            [self.tutor.pk, self.other_tutor.pk],
        )

    def test_returns_empty_list_without_interests(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'request_id': self.tutoring_request.pk,
                'status': TutoringRequest.Status.OPEN,
                'interested_tutors': [],
            },
        )

    def test_does_not_include_interests_for_other_requests(self):
        self.make_interest()

        other_request = TutoringRequest.objects.create(
            student=self.other_student,
            course=self.course,
            description='Another request.',
        )
        self.make_interest(
            tutoring_request=other_request,
            tutor=self.other_tutor,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_tutor_ids(response),
            [self.tutor.pk],
        )

    def test_other_student_cannot_view_interested_tutors(self):
        self.make_interest()
        self.client.force_login(self.other_student)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_student_id_parameter_does_not_bypass_ownership(self):
        self.client.force_login(self.other_student)

        response = self.client.get(
            self.url,
            {'student_id': self.student.pk},
        )

        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_requires_active_student_role(self):
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_unknown_request_returns_404(self):
        self.tutoring_request.delete()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_rejects_post(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'GET')

    def test_inactive_tutor_is_not_shown(self):
        self.make_interest()
        self.tutor.is_active = False
        self.tutor.save(update_fields=['is_active'])

        response = self.client.get(self.url)

        self.assertEqual(self.response_tutor_ids(response), [])

    def test_tutor_role_switch_preserves_interest(self):
        self.make_interest()
        self.tutor.switch_role(User.Role.STUDENT)
        self.tutor.save(update_fields=['role'])

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_tutor_ids(response),
            [self.tutor.pk],
        )

    def test_withdrawn_interest_disappears(self):
        interest_url = reverse(
            'express_tutoring_request_interest',
            kwargs={'request_id': self.tutoring_request.pk},
        )
        withdraw_url = reverse(
            'withdraw_tutoring_request_interest',
            kwargs={'request_id': self.tutoring_request.pk},
        )

        self.client.force_login(self.tutor)
        create_response = self.client.post(interest_url)
        self.assertEqual(create_response.status_code, 201)

        self.client.force_login(self.student)
        before_response = self.client.get(self.url)
        self.assertEqual(
            self.response_tutor_ids(before_response),
            [self.tutor.pk],
        )

        self.client.force_login(self.tutor)
        withdraw_response = self.client.post(withdraw_url)
        self.assertEqual(withdraw_response.status_code, 200)

        self.client.force_login(self.student)
        after_response = self.client.get(self.url)

        self.assertEqual(
            self.response_tutor_ids(after_response),
            [],
        )

    def test_owner_can_view_interests_after_request_closes(self):
        self.make_interest()

        for status in (
            TutoringRequest.Status.WITHDRAWN,
            TutoringRequest.Status.FULFILLED,
        ):
            with self.subTest(status=status):
                self.tutoring_request.status = status
                self.tutoring_request.save(update_fields=['status'])

                response = self.client.get(self.url)

                self.assertEqual(
                    self.response_tutor_ids(response),
                    [self.tutor.pk],
                )
                self.assertEqual(response.json()['status'], status)

    def test_listing_does_not_change_data(self):
        self.make_interest()
        request_count = TutoringRequest.objects.count()
        interest_count = TutoringRequestInterest.objects.count()
        booking_count = Booking.objects.count()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TutoringRequest.objects.count(),
            request_count,
        )
        self.assertEqual(
            TutoringRequestInterest.objects.count(),
            interest_count,
        )
        self.assertEqual(Booking.objects.count(), booking_count)

        self.tutoring_request.refresh_from_db()
        self.assertEqual(
            self.tutoring_request.status,
            TutoringRequest.Status.OPEN,
        )



class TutorSessionsPageTests(TestCase):
    def setUp(self):
        self.url = reverse('tutor_sessions')
        self.tutor = User.objects.create_user(
            email='tutor@example.com', password='pw-12345-xyz', role='tutor')
        self.student = User.objects.create_user(
            email='student@example.com', password='pw-12345-xyz', role='student')
        self.undecided = User.objects.create_user(
            email='new@example.com', password='pw-12345-xyz')

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}",
                             fetch_redirect_response=False)

    def test_student_is_sent_to_student_home(self):
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(self.url), reverse('student_home'),
                             fetch_redirect_response=False)

    def test_user_without_a_role_is_sent_to_student_home(self):
        self.client.force_login(self.undecided)
        self.assertRedirects(self.client.get(self.url), reverse('student_home'),
                             fetch_redirect_response=False)

    def test_tutor_sees_the_page(self):
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tutor/sessions/setup.html')
        self.assertContains(response, 'Set up tutoring sessions')

    def test_page_preselects_the_tutors_saved_courses(self):
        course = Course.create_course('CS 110', 'Programming and Problem Solving')
        TutorProfile.objects.create(user=self.tutor).courses_passed.add(course)
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertEqual(response.context['selected_ids'], [course.pk])
        self.assertContains(response, 'CS 110')   # the search list holds every course

    def test_page_without_saved_courses_still_loads(self):
        Course.create_course('CS 110', 'Programming and Problem Solving')
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_ids'], [])

    def test_picker_has_no_course_limit_and_posts_to_the_save_view(self):
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-max=""')
        self.assertContains(response, f'action="{reverse("tutor_save_courses")}"')

    def test_page_has_the_new_session_form_wired_to_the_slot_endpoint(self):
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertContains(response, f'data-url="{reverse("create_slot")}"')
        for field_id in ('slot-start', 'slot-end', 'slot-price', 'slot-location', 'slot-submit'):
            self.assertContains(response, f'id="{field_id}"')
        self.assertContains(response, 'js/sessions.js')

    def test_page_has_the_schedule_list_wired_to_the_slot_endpoints(self):
        self.client.force_login(self.tutor)
        response = self.client.get(self.url)
        self.assertContains(response, f'data-list-url="{reverse("tutor_schedule")}"')
        self.assertContains(response, f'data-update-url="{reverse("update_slot", args=[0])}"')
        self.assertContains(response, f'data-delete-url="{reverse("delete_slot", args=[0])}"')
        self.assertContains(response, 'id="schedule-list"')
        self.assertContains(response, 'js/schedule.js')

    def test_tutor_home_links_to_the_page(self):
        self.client.force_login(self.tutor)
        self.assertContains(self.client.get(reverse('tutor_home')), self.url)


class TutorSaveCoursesTests(TestCase):
    def setUp(self):
        self.url = reverse('tutor_save_courses')
        self.tutor = User.objects.create_user(
            email='tutor@example.com', password='pw-12345-xyz', role='tutor')
        self.student = User.objects.create_user(
            email='student@example.com', password='pw-12345-xyz', role='student')
        self.cs110 = Course.create_course('CS 110', 'Programming and Problem Solving')
        self.cs210 = Course.create_course('CS 210', 'Data Structures')

    def saved(self):
        return set(TutorProfile.objects.get(user=self.tutor).courses_passed
                   .values_list('course_code', flat=True))

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.post(self.url, {'courses': [self.cs110.pk]})
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}",
                             fetch_redirect_response=False)

    def test_only_post_is_allowed(self):
        self.client.force_login(self.tutor)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_student_cannot_save_tutor_courses(self):
        self.client.force_login(self.student)
        response = self.client.post(self.url, {'courses': [self.cs110.pk]})
        self.assertRedirects(response, reverse('student_home'), fetch_redirect_response=False)
        self.assertFalse(TutorProfile.objects.filter(user=self.student).exists())

    def test_tutor_saves_courses_and_returns_to_the_page(self):
        self.client.force_login(self.tutor)
        response = self.client.post(self.url, {'courses': [self.cs110.pk, self.cs210.pk]}, follow=True)
        self.assertRedirects(response, reverse('tutor_sessions'))
        self.assertContains(response, 'Your courses were saved.')
        self.assertEqual(self.saved(), {'CS 110', 'CS 210'})

    def test_saving_replaces_the_old_choice(self):
        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.cs110)
        self.client.force_login(self.tutor)
        self.client.post(self.url, {'courses': [self.cs210.pk]})
        self.assertEqual(self.saved(), {'CS 210'})

    def test_unknown_course_is_rejected_and_nothing_changes(self):
        TutorProfile.objects.create(user=self.tutor).courses_passed.add(self.cs110)
        self.client.force_login(self.tutor)
        response = self.client.post(self.url, {'courses': [self.cs210.pk, 99999]}, follow=True)
        self.assertContains(response, 'do not exist')
        self.assertEqual(self.saved(), {'CS 110'})

    def test_tutors_have_no_course_limit(self):
        courses = [Course.create_course(f'MATH {n}', f'Course {n}') for n in range(100, 125)]
        self.client.force_login(self.tutor)
        self.client.post(self.url, {'courses': [c.pk for c in courses]})
        self.assertEqual(len(self.saved()), 25)

def make_user(email, first, role=User.Role.TUTOR):
    user = User.objects.create_user(
        email=email, password='pass12345!', first_name=first, last_name='Test',
    )
    user.role = role
    user.save()
    return user


def future_slot(tutor, days=2, hour=10, hours=1, price='20.00',
                location='online'):
    """Create an open slot `days` from now at the given LOCAL hour."""
    base = timezone.localtime(timezone.now()) + timedelta(days=days)
    start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    return Available_Slots.objects.create(
        tutor=tutor,
        start_time=start,
        end_time=start + timedelta(hours=hours),
        price_per_hour=Decimal(price),
        location_type=location,
    )


class FindTutorsBase(TestCase):
    def setUp(self):
        self.cs = Course.objects.create(
            course_code='CS110', course_name='Intro to Programming',
            course_faculty='Science')
        self.eng = Course.objects.create(
            course_code='ENGL100', course_name='Academic Writing',
            course_faculty='Arts')

        self.student = make_user('stu@uregina.ca', 'Sam', User.Role.STUDENT)
        StudentProfile.objects.get_or_create(user=self.student)

        self.alice = make_user('alice@uregina.ca', 'Alice')
        self.alice_profile, _ = TutorProfile.objects.get_or_create(user=self.alice)
        self.alice_profile.courses_passed.add(self.cs)
        self.alice_profile.average_rating = Decimal('4.50')
        self.alice_profile.save()

        self.bob = make_user('bob@uregina.ca', 'Bob')
        self.bob_profile, _ = TutorProfile.objects.get_or_create(user=self.bob)
        self.bob_profile.courses_passed.add(self.eng)

        self.alice_slot = future_slot(self.alice, days=2, hour=9, price='30.00')
        self.bob_slot = future_slot(
            self.bob, days=3, hour=18, price='18.00', location='in_person')

        self.client.force_login(self.student)
        self.url = reverse('find_tutors')

    def names(self, response):
        return [t['first_name'] for t in response.context['tutors']]


class FindTutorsPageTests(FindTutorsBase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_tutor_role_redirected_home(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('tutor_home'))

    def test_lists_all_tutors_with_open_times(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(self.names(response), ['Alice', 'Bob'])

    def test_tutor_without_open_slots_is_hidden(self):
        self.alice_slot.status = Available_Slots.Status.BOOKED
        self.alice_slot.save()
        self.assertEqual(self.names(self.client.get(self.url)), ['Bob'])

    def test_past_slots_do_not_count(self):
        Available_Slots.objects.filter(pk=self.bob_slot.pk).update(
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=2) + timedelta(hours=1),
        )
        self.assertEqual(self.names(self.client.get(self.url)), ['Alice'])

    def test_viewer_never_sees_themselves(self):
        both = make_user('both@uregina.ca', 'Both', User.Role.STUDENT)
        TutorProfile.objects.get_or_create(user=both)
        future_slot(both, days=4)
        self.client.force_login(both)
        self.assertNotIn('Both', self.names(self.client.get(self.url)))

    def test_empty_state_message(self):
        response = self.client.get(self.url, {'q': 'zzzzzz'})
        self.assertContains(response, 'No tutors match')
        self.assertContains(response, 'Clear all filters')

    def test_card_shows_time_price_and_course(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'CS110')
        self.assertContains(response, '$30.00/hour')

    def test_student_home_has_search_box(self):
        response = self.client.get(reverse('student_home'))
        self.assertContains(response, 'action="%s"' % self.url)


class FindTutorsFilterTests(FindTutorsBase):
    def test_search_by_tutor_name(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'q': 'alic'})), ['Alice'])

    def test_search_by_course_code(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'q': 'engl'})), ['Bob'])

    def test_search_by_course_name(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'q': 'programming'})),
            ['Alice'])

    def test_faculty_filter(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'faculty': 'Arts'})), ['Bob'])

    def test_location_filter(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'location': 'in_person'})),
            ['Bob'])

    def test_max_price_filter(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'max_price': '25'})), ['Bob'])

    def test_max_price_is_inclusive(self):
        self.assertCountEqual(
            self.names(self.client.get(self.url, {'max_price': '30'})),
            ['Alice', 'Bob'])

    def test_day_filter(self):
        day = timezone.localtime(self.alice_slot.start_time).date().isoformat()
        self.assertEqual(
            self.names(self.client.get(self.url, {'date': day})), ['Alice'])

    def test_part_of_day_morning(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'part': 'morning'})),
            ['Alice'])

    def test_part_of_day_evening(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'part': 'evening'})), ['Bob'])

    def test_filters_combine(self):
        response = self.client.get(
            self.url, {'faculty': 'Science', 'location': 'in_person'})
        self.assertEqual(self.names(response), [])

    def test_only_matching_times_are_shown_on_card(self):
        future_slot(self.alice, days=5, hour=19, price='45.00')
        response = self.client.get(self.url, {'part': 'evening'})
        tutor = [t for t in response.context['tutors']
                 if t['first_name'] == 'Alice'][0]
        self.assertEqual(len(tutor['available_slots']), 1)
        self.assertEqual(tutor['lowest_price'], Decimal('45.00'))

    def test_partially_booked_slot_uses_remaining_window(self):
        from bookings.models import Booking
        self.alice_slot.end_time = self.alice_slot.start_time + timedelta(hours=3)
        self.alice_slot.save()
        Booking.objects.create(
            student=self.student, tutor=self.alice, course=self.cs,
            start_time=self.alice_slot.start_time,
            end_time=self.alice_slot.start_time + timedelta(hours=3),
            session_price=Decimal('30.00'),
            status=Booking.Status.CONFIRMED,
        )
        self.assertEqual(self.names(self.client.get(self.url)), ['Bob'])


class FindTutorsSortTests(FindTutorsBase):
    def test_sort_soonest_default(self):
        self.assertEqual(self.names(self.client.get(self.url)), ['Alice', 'Bob'])

    def test_sort_by_price(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'sort': 'price'})),
            ['Bob', 'Alice'])

    def test_sort_by_rating_puts_unrated_last(self):
        self.assertEqual(
            self.names(self.client.get(self.url, {'sort': 'rating'})),
            ['Alice', 'Bob'])

    def test_unknown_sort_falls_back(self):
        filters, _ = clean_filters({'sort': 'nonsense'})
        self.assertEqual(filters['sort'], 'soonest')


class CleanFiltersTests(TestCase):
    def test_bad_price_gives_message_and_is_ignored(self):
        filters, errors = clean_filters({'max_price': 'abc'})
        self.assertIsNone(filters['max_price'])
        self.assertEqual(len(errors), 1)

    def test_price_out_of_range(self):
        _, errors = clean_filters({'max_price': '5'})
        self.assertEqual(len(errors), 1)
        _, errors = clean_filters({'max_price': '9999'})
        self.assertEqual(len(errors), 1)

    def test_bad_date_gives_message(self):
        filters, errors = clean_filters({'date': 'not-a-date'})
        self.assertIsNone(filters['date'])
        self.assertEqual(errors, ['Pick a valid date.'])

    def test_impossible_date_gives_message(self):
        _, errors = clean_filters({'date': '2026-02-31'})
        self.assertEqual(errors, ['Pick a valid date.'])

    def test_past_date_gives_message(self):
        _, errors = clean_filters({'date': '2001-01-01'})
        self.assertEqual(errors, ['That date has already passed.'])

    def test_unknown_location_and_part_are_dropped(self):
        filters, errors = clean_filters({'location': 'moon', 'part': 'night'})
        self.assertEqual(filters['location'], '')
        self.assertEqual(filters['part'], '')
        self.assertEqual(errors, [])

    def test_q_is_trimmed_and_capped(self):
        filters, _ = clean_filters({'q': '  ' + 'x' * 500 + '  '})
        self.assertEqual(len(filters['q']), 100)

    def test_page_survives_garbage_and_shows_error(self):
        student = make_user('s2@uregina.ca', 'Sam2', User.Role.STUDENT)
        self.client.force_login(student)
        response = self.client.get(
            reverse('find_tutors'), {'max_price': 'x', 'date': 'y'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Max price must be a number')
        self.assertContains(response, 'Pick a valid date.')
