from accounts.models import User

SYSTEM_ACCOUNT_IDENTIFIER = 'system+content@legacylinkafrica.local'


def get_system_author():
    """The account external-content ingestion (NECTA news, ReliefWeb jobs,
    any future source) posts/lists as — 'LegacyLink Africa' rather than a
    real user. Unusable password: this account can never log in, it only
    ever appears as a Post.author / Opportunity.posted_by. get_or_create
    keeps every ingestion command idempotent without needing a
    migration-time data fixture."""
    user, created = User.objects.get_or_create(
        phone_or_email=SYSTEM_ACCOUNT_IDENTIFIER,
        defaults={'full_name': 'LegacyLink Africa', 'onboarding_complete': True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user
