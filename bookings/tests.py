import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Course, StudentProfile, TutorProfile, User
from bookings.models import Available_Slots, Booking, CancellationDeadlinePassedError, Rating
from bookings.pricing import (
    DEFAULT_PRICE_GRAD,
    DEFAULT_PRICE_UNDERGRAD,
    MAX_PRICE,
    MIN_PRICE,
    calc_price_suggestion,
    custom_pricing,
)
from bookings.services import DoubleBookingError, create_booking_request, get_tutor_available_slots, get_user_bookings
from tUtoR.views import custom_403, custom_500

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
        slot = Dummy_Slot()
        slot.start_time = timezone.now() + timedelta(hours=3)
        booking.time_slot = slot
        with self.assertRaises(CancellationDeadlinePassedError):
            booking.cancel(cancelled_by='student', reason='Fortnite')

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

    # uncomment once available_slots becomes available
    # def test_simultaneous_booking(self):
    #     slot = Available_Slots.objects.create(
    #         tutor=self.tutor,
    #         status='available',
    #         price_per_hour=Decimal('20.00'),
    #         start_time=datetime(2026, 11, 1, 14, 0, 0),
    #         end_time=datetime(2026, 11, 1, 15, 0, 0))
    
    #     results = []
    #     errors = []
    
    #     barrier = threading.Barrier(2)
    #     def book_slot(user):
    #         connection.close()
    #         barrier.wait()
    #         try:
    #             b = create_booking_request(student=user, tutor=self.tutor, slot=slot)
    #             results.append(b)
    #         except DoubleBookingError as e:
    #             errors.append(e)
    
    #     t1 = threading.Thread(target=book_slot, args=(self.student,))
    #     t2 = threading.Thread(target=book_slot, args=(self.student2,))
    
    #     t1.start()
    #     t2.start()
    #     t1.join()
    #     t2.join()

    #     self.assertEqual(len(results), 1)
    #     self.assertEqual(len(errors), 1)

class test_session_request(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='student@ureg.com',
            password='676767HHh?',
            first_name='Dieter',
            last_name='Schwarz',
        )
        self.tutor = User.objects.create_user(
            email='tutor@ureg.com',
            password='676767HHh?',
            first_name='Olli',
            last_name='Blume',
        )
        self.other_user = User.objects.create_user(
            email='other@jyy.com',
            password='676767HHh?',
            first_name='Manfred',
            last_name='mueller',
        )
        self.course = Course.create_course('CS 476', 'SW dev Project')
        self.booking = Booking.objects.create(
            student=self.student,
            tutor=self.tutor,
            course=self.course,
            student_note='bitte helfen sie mir ich bin in gefahr',
            session_price=Decimal('25.00'),
            status=Booking.Status.PENDING,
        )

    def test_student_create_session_request(self):
        self.client.force_login(self.student)
        url = reverse('create_request')
        response = self.client.post(url, {
            'tutor_id': self.tutor.id,
            'course_id': self.course.id,
            'student_note': 'wowhooo bitte bring mir fortnite bei daddy',
            'session_price': '30.00',
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['status'], Booking.Status.PENDING)

    def test_tutor_get_incoming_requests(self):
        self.booking.status = Booking.Status.PENDING
        self.booking.save()

        self.client.force_login(self.tutor)
        url = reverse('incoming_requests')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['open_requests']), 1)
        self.assertEqual(data['open_requests'][0]['id'], self.booking.id)

    def test_tutor_accept_request(self):
        self.booking.status = Booking.Status.PENDING
        self.booking.save()

        self.client.force_login(self.tutor)
        url = reverse('accept_request', kwargs={'booking_id': self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)

    def test_tutor_decline_request(self):
        self.booking.status = Booking.Status.PENDING
        self.booking.save()

        self.client.force_login(self.tutor)
        url = reverse('decline_request', kwargs={'booking_id': self.booking.id})
        response = self.client.post(url, {'reason': 'Kein bock auf dich'})
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED_TUTOR)
        self.assertEqual(self.booking.cancellation_reason, 'Kein bock auf dich')

    def test_wrong_user_accept(self):
        self.booking.status = Booking.Status.PENDING
        self.booking.save()

        self.client.force_login(self.other_user)
        url = reverse('accept_request', kwargs={'booking_id': self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

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
