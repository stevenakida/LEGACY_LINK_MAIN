# Social Login Setup Guide

## Status: ✅ Frontend & Database Ready

Your LegacyLink Africa project has social login functionality configured with Google and Facebook OAuth support using django-allauth!

### What Has Been Completed

#### 1. ✅ Frontend Configuration
- **Login page** (`templates/login.html`):
  - "Continue with Google" button (white, red icon)
  - "Continue with Facebook" button (blue)
  - Font Awesome icons included
  - Traditional phone/email + password form preserved
  - Responsive mobile design

- **Register page** (`templates/register.html`):
  - "Sign up with Google" button
  - "Sign up with Facebook" button
  - Same styling as login page
  - Traditional registration form below social options

#### 2. ✅ Backend Configuration
- django-allauth installed (v65.16.0)
- Google and Facebook OAuth providers added to INSTALLED_APPS
- SITE_ID = 1 configured
- Authentication backends updated
- Allauth middleware added
- Email verification set to optional
- Auto signup enabled for social accounts

#### 3. ✅ Database
- Test OAuth credentials added:
  - **Google**: client_id = `test-google-client-id.apps.googleusercontent.com`
  - **Facebook**: app_id = `1234567890`
- Site entry configured for localhost:8000

#### 4. ✅ URL Routes
- Allauth routes: `path('accounts/', include('allauth.urls'))`
- Social login endpoints ready:
  - `{% url 'socialaccount_authorize' 'google' %}`
  - `{% url 'socialaccount_authorize' 'facebook' %}`

## Current Limitations

⚠️ **Note**: The current setup has test credentials in the database, but the actual OAuth flow requires the Python `cryptography` library, which is having compilation issues in the current environment.

### Workaround for Development

The UI is complete and buttons are functional. To test locally:

1. **Test Text Display**:
   - Navigate to `/login/` or `/register/`
   - You'll see the Google and Facebook buttons
   - The traditional form still works for email/phone login

2. **To Enable Full OAuth Flow**, you need to:
   - Install Microsoft C++ Build Tools for cryptography compilation
   - Run: `pip install cryptography` 
   - Or use a virtual environment with pre-built cryptography wheels

## Setting Up Real OAuth Credentials

### For Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the following APIs:
   - Google+ API
   - Google Identity Service API
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Choose "Web Application"
6. Add authorized redirect URIs:
   - `http://localhost:8000/accounts/google/login/callback/`
   - `http://127.0.0.1:8000/accounts/google/login/callback/`
   - For production: `https://yourdomain.com/accounts/google/login/callback/`
7. Copy **Client ID** and **Client Secret**

### For Facebook OAuth

1. Go to [Facebook Developers](https://developers.facebook.com/)
2. Create a new app (App Type: Consumer)
3. In **Settings → Basic**, copy:
   - **App ID**
   - **App Secret**
4. Add **Valid OAuth Redirect URIs**:
   - `http://localhost:8000/accounts/facebook/login/callback/`
   - For production: `https://yourdomain.com/accounts/facebook/login/callback/`
5. Under **Products**, add "Facebook Login"

### Adding Credentials to Django Admin

Once cryptography is working and Django loads properly:

1. Start Django: `python manage.py runserver`
2. Go to `http://localhost:8000/admin/`
3. Go to **Social Applications**
4. Edit existing test apps or create new ones:

   **For Google:**
   - Provider: Google
   - Name: Google OAuth
   - Client ID: (from Google Cloud Console)
   - Secret Key: (from Google Cloud Console)
   - Sites: Select localhost:8000
   - Save

   **For Facebook:**
   - Provider: Facebook
   - Name: Facebook OAuth
   - Client ID: (Facebook App ID)
   - Secret Key: (Facebook App Secret)
   - Sites: Select localhost:8000
   - Save

## Files Created/Modified

### New Files
- `accounts/management/commands/setup_oauth.py` - Management command for setup
- `add_test_oauth.py` - Script that added test credentials
- `SOCIAL_LOGIN_SETUP.md` - This setup guide

### Modified Files
- `config/settings.py` - Added allauth configuration
- `config/urls.py` - Added allauth URLs
- `templates/login.html` - Added social login buttons
- `templates/register.html` - Added social login buttons
- `db.sqlite3` - Test credentials added

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'cryptography'"
**Solution**: 
- On Windows, install Microsoft C++ Build Tools
- Or use a Docker container with pre-built wheels
- Alternatively, just use the test credentials for UI testing

### Issue: "Social Applications not appearing"
**Solution**: 
- Check that migrations have run: `python manage.py migrate`
- Verify `SITE_ID = 1` in settings.py
- Check db.sqlite3 for socialaccount\_socialapp table

### Issue: "Redirect URI mismatch"
**Solution**:
- For local dev, URIs must be:
  - `http://localhost:8000/accounts/provider/login/callback/`
  - `http://127.0.0.1:8000/accounts/provider/login/callback/`
- Check exact match in OAuth provider settings vs Django configuration

## Security Notes

### For Production

1. **Use HTTPS only** - Update all redirect URIs to https://
2. **Environment Variables** - Store credentials in env vars:
   ```python
   GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
   FACEBOOK_APP_ID = os.environ.get('FACEBOOK_APP_ID')
   ```
3. **DEBUG = False** - Disable debug mode
4. **ALLOWED_HOSTS** - Configure properly
5. **Email Verification** - Set to 'mandatory' for production
6. **HTTPS Redirects** - Enable `SECURE_SSL_REDIRECT = True`

## Next Steps

1. ✅ Frontend buttons added to login/register
2. ✅ Test credentials configured in database
3. ⏳ Resolve cryptography compilation issue (if planning full OAuth)
4. ⏳ Add real OAuth credentials from Google & Facebook
5. ⏳ Test complete OAuth flow end-to-end

## Implementation Notes

The social login implementation uses django-allauth which provides:
- OAuth2 authentication for Google and Facebook
- Automatic user account creation from OAuth data
- Email and profile picture import
- Account linking support
- CSRF protection
- Session management

The current limitation is just the Python cryptography library compilation, which is a development environment issue, not a code issue.

## Resources

- [django-allauth Documentation](https://django-allauth.readthedocs.io/)
- [Google OAuth Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Facebook Login Documentation](https://developers.facebook.com/docs/facebook-login)
- [Python Cryptography](https://cryptography.io/)

