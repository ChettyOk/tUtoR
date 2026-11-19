import csv
import re
import unicodedata
from pathlib import Path

import pypdf

DEFAULT_CSV = Path(__file__).resolve().parent / 'data' / 'uregina_courses.csv'

# "CS 110 - Name": 2-4 capital letters, space, 3 digits, then " - " and the title
HEADING = re.compile(r'^([A-Z]{2,4}\s\d{3})\s-\s(.+)$')
# headings with a letter suffix, e.g. "ACSC 390AA - ..."
SUFFIX_HEADING = re.compile(r'^[A-Z]{2,4}\s\d{3}[A-Z]{1,3}\s-\s')
# a title line is usually wrapped at about this many characters
WRAP_LINE_LENGTH = 58
MAX_WRAPPED_LENGTH = 45


def _looks_like_title_continuation(heading_line, next_line):
    """True when next_line is the second half of a title that wrapped."""
    if len(heading_line) < WRAP_LINE_LENGTH or not next_line:
        return False
    if len(next_line) > MAX_WRAPPED_LENGTH:
        return False
    if next_line.endswith('.') and 'AA-ZZ' not in next_line:   # a full sentence = description
        return False
    if next_line[0].isdigit() or next_line[0] == '*':
        return False
    if next_line.startswith(('Prerequisite', 'Note')):
        return False
    return not (HEADING.match(next_line) or SUFFIX_HEADING.match(next_line))


def _clean_name(name):
    name = unicodedata.normalize('NFKC', name)   # turns the ligature "ﬁ" back into "fi"
    # drop the "- an AA-ZZ series" tag (also AA-AZ, AA-) that topic courses carry
    name = re.sub(r'\s*[-–]?\s*(an\s+)?AA\s*(-|to)\s*([A-Z]{2})?(\s+series)?(\s+course)?\.?$',
                  '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip()


def parse_catalogue_lines(lines):
    """Return a list of (course_code, course_name) from the catalogue's text lines."""
    lines = [line.strip() for line in lines]
    courses = {}

    for i, line in enumerate(lines):
        match = HEADING.match(line)
        if not match:
            continue
        # A heading right after another heading is part of that title
        # (e.g. "... (formerly" / "EFLD 050 - Bac section only)"), not a new course.
        if i > 0 and HEADING.match(lines[i - 1]):
            continue

        code, name = match.groups()
        next_line = lines[i + 1] if i + 1 < len(lines) else ''
        if HEADING.match(next_line) or _looks_like_title_continuation(line, next_line):
            name = f'{name} {next_line}'

        courses.setdefault(code, _clean_name(name))   # first real heading wins

    return list(courses.items())


def parse_catalogue_pdf(pdf_path):
    reader = pypdf.PdfReader(pdf_path)
    lines = []
    for page in reader.pages:
        lines.extend((page.extract_text() or '').split('\n'))
    return parse_catalogue_lines(lines)


def write_csv(courses, csv_path):
    with open(csv_path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['course_code', 'course_name'])
        writer.writerows(courses)


def read_csv(csv_path=DEFAULT_CSV):
    with open(csv_path, newline='', encoding='utf-8') as file:
        return [(row['course_code'], row['course_name']) for row in csv.DictReader(file)]
