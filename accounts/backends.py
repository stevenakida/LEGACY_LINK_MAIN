from django.contrib.auth.backends import ModelBackend
from .models import User


class PhoneOrEmailBackend(ModelBackend):
    """
    Custom authentication backend that allows users to login with phone_or_email
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get('phone_or_email')
        if identifier is None:
            return None
        try:
            user = User.objects.get(phone_or_email=identifier)
        except User.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
