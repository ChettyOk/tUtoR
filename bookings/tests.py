from django.urls import reverse
from django.test import TestCase
from accounts.models import Course, User
from django.test import Client
from django.urls import reverse
from bookings.pricing import (calc_price_suggestion, DEFAULT_PRICE_UNDERGRAD, DEFAULT_PRICE_GRAD, MAX_PRICE, MIN_PRICE, custom_pricing)
from decimal import Decimal
import time

from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from bookings.models import Booking

from unittest.mock import MagicMock
from bookings.services import create_booking_request, get_user_bookings, DoubleBookingError
import threading
from django.db import connection

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

    # def test_mean_calc(self):
    #     price = calc_price_suggestion(self.undergrad_tutor)
    #     self.assertEqual(price, Decimal('25.00'))

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
        class Dummy_Slot: 
            objects = MagicMock()
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