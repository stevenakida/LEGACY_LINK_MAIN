from rest_framework import serializers
from .models import School


class SchoolSerializer(serializers.ModelSerializer):
    alumni_count = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = ['id', 'name', 'slug', 'region', 'school_type', 'alumni_count']

    def get_alumni_count(self, obj):
        return obj.alumni.filter(onboarding_complete=True).count()