from django.core.management.base import BaseCommand

from alumni.alias_seed import seed
from alumni.models import School, SchoolAlias


class Command(BaseCommand):
    help = 'Add the curated starting school aliases (idempotent; safe to re-run).'

    def handle(self, *args, **options):
        created, missing = seed(School, SchoolAlias)
        self.stdout.write(f'{created} alias(es) created.')
        for name in missing:
            self.stdout.write(f'  not found, skipped: {name}')
