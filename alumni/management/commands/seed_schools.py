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
    
    # Secondary Schools
    {"name": "Jangwani Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Tambaza High School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Azania Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "Ilboru Secondary School", "region": "Arusha", "school_type": "secondary"},
    {"name": "Mzumbe Secondary School", "region": "Morogoro", "school_type": "secondary"},
    {"name": "Kilakala Girls Secondary", "region": "Morogoro", "school_type": "secondary"},
    {"name": "Alliance Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
    {"name": "St. Mary's Secondary School", "region": "Dar es Salaam", "school_type": "secondary"},
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