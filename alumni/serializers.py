from rest_framework import serializers
from .models import School

_ALUMNI_RELATED_NAME = {
    'primary': 'primary_alumni',
    'secondary': 'secondary_alumni',
    'high_school': 'high_school_alumni',
    'university': 'tertiary_alumni',
}


class SchoolSerializer(serializers.ModelSerializer):
    alumni_count = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = ['id', 'name', 'slug', 'region', 'district', 'school_type', 'alumni_count']

    def get_alumni_count(self, obj):
        related_name = _ALUMNI_RELATED_NAME.get(obj.school_type)
        if not related_name:
            return 0
        return getattr(obj, related_name).filter(onboarding_complete=True).count()