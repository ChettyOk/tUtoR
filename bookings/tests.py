from django.urls import reverse
from django.test import TestCase
from accounts.models import Course, User
from django.test import Client
from django.urls import reverse
from bookings.pricing import (calc_price_suggestion, DEFAULT_PRICE_UNDERGRAD, DEFAULT_PRICE_GRAD, MAX_PRICE, MIN_PRICE, custom_pricing)
from decimal import Decimal
import time


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
     
        
