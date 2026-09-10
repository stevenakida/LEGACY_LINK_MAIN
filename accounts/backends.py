from django.contrib.auth.backends import ModelBackend
from .models import User


class PhoneOrEmailBackend(ModelBackend):
    """Custom authentication backend that allows login with:
    - phone_or_email, the canonical login identifier, in any of the
      equivalent Tanzanian phone formats (+255…, 255…, 0…) — see
      normalize_identifier, applied via User.find_by_login_identifier so a
      user who typed 0712345678 at signup can log in with +255712345678
      and vice versa, instead of needing an exact string match.
    - a later profile email, once verified, for accounts that registered
      with a phone number — same account, same password, see
      User.find_by_login_identifier / User.eligible_reset_email for the
      parallel trust rule used by password reset.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get('phone_or_email')
        if identifier is None:
            return None
        user = User.find_by_login_identifier(identifier)
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
