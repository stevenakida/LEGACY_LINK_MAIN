#!/usr/bin/env python
"""
Script to set up test OAuth credentials for local development
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp

def setup_test_credentials():
    """Create test OAuth credentials for Google and Facebook"""
    
    # Get or create the site
    site, created = Site.objects.get_or_create(
        id=1,
        defaults={
            'domain': 'localhost:8000',
            'name': 'LegacyLink Africa Dev'
        }
    )
    
    if created:
        print(f"✓ Created site: {site.name} ({site.domain})")
    else:
        print(f"✓ Using existing site: {site.name} ({site.domain})")
    
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
        print(f"✓ Created Google OAuth app")
        google_app.sites.add(site)
        print(f"  - Client ID: {google_app.client_id}")
    else:
        print(f"✓ Google OAuth app already exists")
    
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
        print(f"✓ Created Facebook OAuth app")
        facebook_app.sites.add(site)
        print(f"  - App ID: {facebook_app.client_id}")
    else:
        print(f"✓ Facebook OAuth app already exists")
    
    print("\n✅ OAuth credentials configured for testing!")
    print("\nLogin flows are now available at:")
    print("  - /login/")
    print("  - /register/")
    print("\nNote: These are test credentials. Replace with real credentials for production.")

if __name__ == '__main__':
    try:
        setup_test_credentials()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
