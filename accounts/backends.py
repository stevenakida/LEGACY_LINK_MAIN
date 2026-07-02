from django.contrib.auth.backends import ModelBackend
from .models import User


class PhoneOrEmailBackend(ModelBackend):
    """
    Custom authentication backend that allows users to login with phone_or_email
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = User.objects.get(phone_or_email=username)
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
