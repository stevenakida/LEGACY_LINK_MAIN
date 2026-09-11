from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
import re
import uuid


def normalize_identifier(value):
    """Collapse the many equivalent ways a Tanzanian phone number gets typed
    (with/without +255, with/without the leading 0, with spaces or dashes)
    into one canonical form, so the same number always maps to one account.
    Emails are just trimmed/lowercased. Anything that doesn't look like a
    local 10-digit (0xxxxxxxxx) or +255/255-prefixed number is left as-is —
    better to under-normalize an unfamiliar format than mangle it."""
    if not value:
        return value
    value = value.strip()
    if '@' in value:
        return value.lower()

    digits_only = re.sub(r'[\s\-().]', '', value)
    if digits_only.startswith('+255') and len(digits_only) == 13:
        return digits_only
    if digits_only.startswith('255') and len(digits_only) == 12:
        return '+' + digits_only
    if digits_only.startswith('0') and len(digits_only) == 10:
        return '+255' + digits_only[1:]
    return digits_only


class UserManager(BaseUserManager):
    def create_user(self, phone_or_email, password=None, **extra_fields):
        if not phone_or_email:
            raise ValueError('Phone or email is required')
        phone_or_email = normalize_identifier(phone_or_email)
        user = self.model(phone_or_email=phone_or_email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_or_email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(phone_or_email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": normalize_identifier(username)})


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_or_email = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=200)
    bio = models.TextField(blank=True, max_length=300)
    avatar = models.FileField(upload_to='avatars/', blank=True, null=True)

    # Persists the EN/SW toggle across sessions/devices — set from the top
    # nav language switch (see config.views.set_language_web).
    preferred_language = models.CharField(
        max_length=5, choices=settings.LANGUAGES, default='en'
    )

    # Separate contact fields so we can capture both a phone number and an
    # email regardless of which one was used to register (phone_or_email is
    # whichever the user signed up with — these two let them fill in the
    # other one from their profile).
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    # Whether `email` above has been confirmed by clicking the link sent to
    # it (see config.views.verify_email_confirm). Only a verified profile
    # email is trusted as a password-reset destination — an unconfirmed
    # address could have been mistyped or belong to someone else entirely.
    # Not relevant when `phone_or_email` itself is an email: that one is
    # already trusted at login-credential strength (see eligible_reset_email).
    email_verified = models.BooleanField(default=False)

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

    @classmethod
    def find_by_login_identifier(cls, identifier):
        """Resolve a login-form identifier (phone or email, in any of the
        accepted formats — see normalize_identifier) to an account. Tries
        `phone_or_email` (the canonical login identifier) first, then falls
        back to a VERIFIED profile email — an unverified one can't be used
        to log in, same rule as password reset (see eligible_reset_email).
        Used by PhoneOrEmailBackend and by login_view's invalid-password-vs-
        no-account messaging, so both stay consistent."""
        if not identifier:
            return None
        identifier = normalize_identifier(identifier.strip())
        user = cls.objects.filter(phone_or_email__iexact=identifier).first()
        if user is None and '@' in identifier:
            user = cls.objects.filter(email__iexact=identifier, email_verified=True).first()
        return user

    @classmethod
    def find_by_email_identifier(cls, identifier):
        """Look up an account by an email address, checking both places one
        can live: `phone_or_email` (the login identifier itself, for users
        who registered with an email) and `email` (added later from the
        profile, for phone-only registrants). Case-insensitive. Returns None
        on no match; if legacy data somehow has more than one account
        matching (no DB-level uniqueness on `email`), deterministically
        returns one rather than raising."""
        if not identifier:
            return None
        return cls.objects.filter(
            models.Q(phone_or_email__iexact=identifier) | models.Q(email__iexact=identifier)
        ).order_by('id').first()

    def apply_email_update(self, raw_value):
        """Validate/normalize/dedupe a submitted email and apply it to
        `self` in place (caller still needs to `.save()`). Returns
        (changed, error_message). On any rejection, `self.email` is left
        untouched so the rest of a larger form/request can still save.
        Changing the email always resets `email_verified` to False — a
        freshly typed (or re-typed) address isn't trusted for password
        reset or login until its owner clicks the verification link again;
        see eligible_reset_email() / find_by_login_identifier(). Shared by
        the web profile-edit view and the mobile API (accounts.views.MeView)
        so both apply the exact same rules — see accounts/services.py for
        the matching shared verification-email dispatch."""
        new_email = (raw_value or '').strip().lower()
        if new_email == (self.email or '').lower():
            return False, None
        if new_email:
            try:
                validate_email(new_email)
            except ValidationError:
                return False, "That email address doesn't look valid, so it wasn't updated."
            duplicate = User.objects.filter(
                models.Q(email__iexact=new_email) | models.Q(phone_or_email__iexact=new_email)
            ).exclude(id=self.id).exists()
            if duplicate:
                return False, "That email address is already in use on another LegacyLink Africa account, so it wasn't updated."
        self.email = new_email
        self.email_verified = False
        return True, None

    def eligible_reset_email(self):
        """The address a password-reset link may be sent to, or None if this
        account has none yet. An email is eligible when it's either the
        identifier the user logs in with (trusted at login-credential
        strength already) or a later profile email that's been verified.
        A phone-only account with no verified profile email has no eligible
        recipient — SMS-based reset isn't available."""
        if '@' in self.phone_or_email:
            return self.phone_or_email
        if self.email and self.email_verified:
            return self.email
        return None

    @property
    def cohort_label(self):
        if self.secondary_school and self.secondary_completion_year:
            return f"{self.secondary_school.name} · Class of {self.secondary_completion_year}"
        if self.high_school and self.high_school_completion_year:
            return f"{self.high_school.name} · Class of {self.high_school_completion_year}"
        if self.tertiary_school and self.tertiary_completion_year:
            return f"{self.tertiary_school.name} · Class of {self.tertiary_completion_year}"
        if self.primary_school and self.primary_completion_year:
            return f"{self.primary_school.name} · Class of {self.primary_completion_year}"
        return ""

    def cohort_queryset(self):
        """Other users who share this user's school+year at ANY of the four
        education levels (primary, secondary/O-level, high school/A-level,
        university/tertiary). Any single match is enough — a shared primary
        class counts even without a shared secondary school, and so on for
        every level."""
        match = models.Q(pk__in=[])
        has_criteria = False
        if self.primary_school and self.primary_completion_year:
            match |= models.Q(
                primary_school=self.primary_school,
                primary_completion_year=self.primary_completion_year,
            )
            has_criteria = True
        if self.secondary_school and self.secondary_completion_year:
            match |= models.Q(
                secondary_school=self.secondary_school,
                secondary_completion_year=self.secondary_completion_year,
            )
            has_criteria = True
        if self.high_school and self.high_school_completion_year:
            match |= models.Q(
                high_school=self.high_school,
                high_school_completion_year=self.high_school_completion_year,
            )
            has_criteria = True
        if self.tertiary_school and self.tertiary_completion_year:
            match |= models.Q(
                tertiary_school=self.tertiary_school,
                tertiary_completion_year=self.tertiary_completion_year,
            )
            has_criteria = True
        if not has_criteria:
            return User.objects.none()
        return User.objects.filter(match).exclude(id=self.id)

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
