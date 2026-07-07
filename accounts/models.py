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

    high_school = models.ForeignKey(
        'alumni.School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='high_school_alumni',
        limit_choices_to={'school_type': 'high_school'}
    )
    high_school_completion_year = models.PositiveIntegerField(null=True, blank=True)

    tertiary_school = models.ForeignKey(
        'alumni.School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tertiary_alumni',
        limit_choices_to={'school_type': 'university'}
    )
    tertiary_completion_year = models.PositiveIntegerField(null=True, blank=True)

    current_role = models.CharField(max_length=200, blank=True)

    EMPLOYMENT_STATUS_CHOICES = [
        ('employed', 'Employed'),
        ('self_employed', 'Self-employed'),
        ('business_owner', 'Business Owner'),
    ]
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, blank=True)
    company_name = models.CharField(max_length=200, blank=True)

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

    # Weights for the Identity Score (profile completion meter). Education is
    # split across the three school levels; together they total 35%.
    IDENTITY_SCORE_WEIGHTS = {
        'avatar': 10,
        'bio': 10,
        'primary_school': 12,
        'secondary_school': 12,
        'tertiary_school': 11,
        'current_location': 10,
        'current_role': 20,
        'company_name': 15,
    }

    def _identity_score_components(self):
        w = self.IDENTITY_SCORE_WEIGHTS
        return [
            ('avatar', 'Upload a profile picture', w['avatar'], bool(self.avatar)),
            ('bio', 'Add a short bio about yourself', w['bio'], bool(self.bio)),
            ('primary_school', 'Add your Primary school', w['primary_school'],
                bool(self.primary_school and self.primary_completion_year)),
            ('secondary_school', 'Add your Secondary school', w['secondary_school'],
                bool(self.secondary_school and self.secondary_completion_year)),
            ('tertiary_school', 'Add your University/Tertiary education', w['tertiary_school'],
                bool(self.tertiary_school and self.tertiary_completion_year)),
            ('current_location', 'Add your current location', w['current_location'], bool(self.current_location)),
            ('current_role', 'Add your profession', w['current_role'], bool(self.current_role)),
            ('company_name', 'Add your company or organization', w['company_name'], bool(self.company_name)),
        ]

    @property
    def identity_score(self):
        return sum(points for _, _, points, done in self._identity_score_components() if done)

    @property
    def identity_score_suggestions(self):
        missing = [
            {'label': label, 'points': points}
            for _, label, points, done in self._identity_score_components()
            if not done
        ]
        return sorted(missing, key=lambda item: item['points'], reverse=True)
