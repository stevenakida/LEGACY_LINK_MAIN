from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp


class Command(BaseCommand):
    help = 'Setup OAuth credentials for testing'

    def handle(self, *args, **options):
        # Get or create the site
        site, created = Site.objects.get_or_create(
            id=1,
            defaults={
                'domain': 'localhost:8000',
                'name': 'LegacyLink Africa Dev'
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created site: {site.name} ({site.domain})'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Using existing site: {site.name} ({site.domain})'))
        
        # Google OAuth Test Credentials
        google_app, created = SocialApp.objects.get_or_create(
            provider='google',
            defaults={
                'name': 'Google OAuth (Test)',
                'client_id': 'test-google-client-id.apps.googleusercontent.com',
                'secret': 'test-google-client-secret-abc123',
            }
        )
        
        if created:
            google_app.sites.add(site)
            self.stdout.write(self.style.SUCCESS(f'✓ Created Google OAuth app'))
            self.stdout.write(f'  - Client ID: {google_app.client_id}')
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Google OAuth app already exists'))
        
        # Facebook OAuth Test Credentials
        facebook_app, created = SocialApp.objects.get_or_create(
            provider='facebook',
            defaults={
                'name': 'Facebook OAuth (Test)',
                'client_id': '1234567890',
                'secret': 'test-facebook-app-secret-xyz789',
            }
        )
        
        if created:
            facebook_app.sites.add(site)
            self.stdout.write(self.style.SUCCESS(f'✓ Created Facebook OAuth app'))
            self.stdout.write(f'  - App ID: {facebook_app.client_id}')
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Facebook OAuth app already exists'))
        
        self.stdout.write(self.style.SUCCESS('\n✅ OAuth credentials configured for testing!'))
        self.stdout.write('\nLogin flows are now available at:')
        self.stdout.write('  - /login/')
        self.stdout.write('  - /register/')
        self.stdout.write('\nNote: These are test credentials. Replace with real credentials for production.')
