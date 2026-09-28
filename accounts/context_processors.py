from . import google_oauth


def google_sign_in(request):
    # Hide the Google button unless OAuth is configured: an unconfigured button
    # bounces back to /login/ instead of accounts.google.com, which Safe
    # Browsing flagged as a deceptive (fake Google sign-in) page.
    return {'google_sign_in_enabled': google_oauth.is_configured()}
