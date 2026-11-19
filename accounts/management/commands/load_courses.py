from django.core.management.base import BaseCommand, CommandError

from accounts.course_catalogue import DEFAULT_CSV, parse_catalogue_pdf, read_csv, write_csv
from accounts.models import Course


class Command(BaseCommand):
    help = 'Load the University of Regina courses into the database (safe to run again).'

    def add_arguments(self, parser):
        parser.add_argument('--pdf', help='Read the course catalogue PDF instead of the saved CSV.')
        parser.add_argument('--save-csv', help='With --pdf: also write the courses to this CSV file.')

    def handle(self, *args, **options):
        try:
            if options['pdf']:
                courses = parse_catalogue_pdf(options['pdf'])
                if options['save_csv']:
                    write_csv(courses, options['save_csv'])
                    self.stdout.write(f"Saved {len(courses)} courses to {options['save_csv']}")
            else:
                courses = read_csv(DEFAULT_CSV)
        except FileNotFoundError as error:
            raise CommandError(f'File not found: {error.filename}')

        existing = {course.course_code: course for course in Course.objects.all()}
        to_create, to_update = [], []

        for code, name in courses:
            prefix = code.split()[0]
            faculty = Course.FACULTIES.get(prefix, 'other')
            course = existing.get(code)
            if course is None:
                to_create.append(Course(course_code=code, course_name=name, course_faculty=faculty))
            elif (course.course_name, course.course_faculty) != (name, faculty):
                course.course_name, course.course_faculty = name, faculty
                to_update.append(course)

        Course.objects.bulk_create(to_create)
        Course.objects.bulk_update(to_update, ['course_name', 'course_faculty'])

        self.stdout.write(self.style.SUCCESS(
            f'{len(to_create)} added, {len(to_update)} updated, '
            f'{len(courses) - len(to_create) - len(to_update)} unchanged.'))