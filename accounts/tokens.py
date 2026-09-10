from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Same HMAC+timestamp scheme Django uses for password-reset tokens, but
    salted by class path (differs automatically from PasswordResetTokenGenerator,
    which bakes in its own class path) so a token minted for one purpose can't
    be replayed for the other. The hash also mixes in the pending `email` and
    `email_verified` values, so a verification link is invalidated the moment
    the user changes their email again or the address is already verified."""

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.email}{user.email_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()
