from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import User
from .services import dispatch_email_verification


class RegisterSerializer(serializers.ModelSerializer):
    # No separate min_length: the project's AUTH_PASSWORD_VALIDATORS (below)
    # are the single rule, the same one the web form and password reset use.
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['full_name', 'phone_or_email', 'password']

    def validate_password(self, value):
        identifier = self.initial_data.get('phone_or_email') or ''
        candidate = User(
            phone_or_email=identifier, full_name=self.initial_data.get('full_name') or '',
            email=identifier if '@' in identifier else '',
        )
        try:
            validate_password(value, user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    primary_school_name = serializers.CharField(source='primary_school.name', read_only=True)
    secondary_school_name = serializers.CharField(source='secondary_school.name', read_only=True)
    high_school_name = serializers.CharField(source='high_school.name', read_only=True)
    cohort_label = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'full_name', 'phone_or_email', 'bio', 'avatar',
            'email', 'phone_number', 'email_verified',
            'current_location', 'current_role',
            'primary_school', 'primary_school_name', 'primary_completion_year',
            'secondary_school', 'secondary_school_name', 'secondary_completion_year',
            'high_school', 'high_school_name', 'high_school_completion_year',
            'cohort_label', 'onboarding_complete'
        ]
        read_only_fields = [
            'id', 'phone_or_email', 'primary_school_name', 'secondary_school_name',
            'high_school_name', 'email_verified',
        ]

    def update(self, instance, validated_data):
        """`email` goes through User.apply_email_update (validate, normalize,
        dedupe, reset email_verified) instead of a plain field assignment —
        the same rules the web profile-edit form applies, see
        config.views.profile_edit. Popped out of validated_data and applied
        first so an invalid/taken email rejects the whole PATCH atomically
        (standard REST semantics: nothing saves, client sees exactly why and
        can resubmit) rather than silently dropping just that one field."""
        email_changed = False
        if 'email' in validated_data:
            raw_email = validated_data.pop('email')
            email_changed, error = instance.apply_email_update(raw_email)
            if error:
                raise serializers.ValidationError({'email': error})

        instance = super().update(instance, validated_data)

        if email_changed and instance.email:
            request = self.context.get('request')
            if request is not None:
                dispatch_email_verification(request, instance)
        return instance