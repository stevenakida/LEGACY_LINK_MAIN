from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
import uuid


class UserManager(BaseUserManager):
    def create_user(self, phone_or_email, password=None, **extra_fields):
        if not phone_or_email:
            raise ValueError('Phone or email is required')
        user = self.model(phone_or_email=phone_or_email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_or_email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(phone_or_email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_or_email = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=200)
    bio = models.TextField(blank=True, max_length=300)
    avatar = models.FileField(upload_to='avatars/', blank=True, null=True)
    
    # Location
    current_location = models.CharField(max_length=200, blank=True)
    
    # Educational background - linked to School model
    primary_school = models.ForeignKey(
        'alumni.School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='primary_alumni',
        limit_choices_to={'school_type': 'primary'}
    )
    primary_completion_year = models.PositiveIntegerField(null=True, blank=True)
    
    secondary_school = models.ForeignKey(
        'alumni.School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='secondary_alumni',
        limit_choices_to={'school_type': 'secondary'}
    )
    secondary_completion_year = models.PositiveIntegerField(null=True, blank=True)
    
    high_school = models.CharField(max_length=200, blank=True)
    high_school_completion_year = models.PositiveIntegerField(null=True, blank=True)
    
    current_role = models.CharField(max_length=200, blank=True)
    
    onboarding_complete = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'phone_or_email'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.phone_or_email})"

    @property
    def cohort_label(self):
        if self.secondary_school and self.secondary_completion_year:
            return f"{self.secondary_school.name} · Class of {self.secondary_completion_year}"
        return ""
