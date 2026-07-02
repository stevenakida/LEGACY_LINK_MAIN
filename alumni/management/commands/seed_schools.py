from django.core.management.base import BaseCommand
from alumni.models import School

SCHOOLS = [
    # Primary Schools
    {"name": "Jangwani Primary School", "region": "Dar es Salaam", "school_type": "primary"},
    {"name": "Tambaza Primary School", "region": "Dar es Salaam", "school_type": "primary"},
    {"name": "Azania Primary School", "region": "Dar es Salaam", "school_type": "primary"},
    {"name": "Ilboru Primary School", "region": "Arusha", "school_type": "primary"},
    {"name": "Mzumbe Primary School", "region": "Morogoro", "school_type": "primary"},
    {"name": "Alliance Primary School", "region": "Dar es Salaam", "school_type": "primary"},
    {"name": "Arusha Modern Primary School", "region": "Arusha", "school_type": "primary"},
    {"name": "Nalopa English Medium School", "region": "Arusha", "school_type": "primary"},
    {"name": "Lucky Vicent Nursery and Primary School", "region": "Arusha", "school_type": "primary"},
    {"name": "Uhuru Peak Pre and Primary School", "region": "Arusha", "school_type": "primary"},
    {"name": "Haradali Pre and Primary School", "region": "Arusha", "school_type": "primary"},

    # Secondary Schools
    {"name": "Jangwani Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Tambaza High School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Azania Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Ilboru Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Mzumbe Secondary School", "region": "Morogoro", "school_type": "secondary"},
    {"name": "Kilakala Girls Secondary", "region": "Morogoro", "school_type": "secondary"},
    {"name": "Alliance Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "St. Mary's Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},

    # Secondary Schools - Arusha region
    {"name": "Kisimiri Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Trust St Patrick Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Star High School", "region": "Arusha", "school_type": "secondary"},
    {"name": "St Theresa of the Child Jesus Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "St Jude Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Unambwe Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Peace House Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Moringe Sokoine Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Olorien Valley School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Enaboishu High School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Karatu High School", "region": "Arusha", "school_type": "secondary"},
    {"name": "St Joseph Ngarenaro Girls Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Oldadai Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Edmund Rice Sinon Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Florian Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Kinana Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Mwandet Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Turkish Maarif Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Tengeru Boys Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Mariado Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Mang'ola Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Prime Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "El-Shammah Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Tanzania Adventist Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Sakina Secondary School", "region": "Arusha", "school_type": "secondary"},
    # Add more as needed
]

class Command(BaseCommand):
    help = 'Seed Tanzania primary and secondary schools'

    def handle(self, *args, **options):
        created = 0
        for s in SCHOOLS:
            _, was_created = School.objects.get_or_create(name=s['name'], defaults=s)
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Seeded {created} schools'))