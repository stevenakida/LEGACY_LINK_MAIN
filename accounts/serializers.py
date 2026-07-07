from rest_framework import serializers
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['full_name', 'phone_or_email', 'password']

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
            'current_location', 'current_role',
            'primary_school', 'primary_school_name', 'primary_completion_year',
            'secondary_school', 'secondary_school_name', 'secondary_completion_year',
            'high_school', 'high_school_name', 'high_school_completion_year',
            'cohort_label', 'onboarding_complete'
        ]
        read_only_fields = ['id', 'phone_or_email', 'primary_school_name', 'secondary_school_name', 'high_school_name']