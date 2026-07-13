from rest_framework import serializers
from .models import Opportunity


class OpportunitySerializer(serializers.ModelSerializer):
    school_scope_name = serializers.CharField(source='school_scope.name', read_only=True, default='')
    is_interested = serializers.SerializerMethodField()

    class Meta:
        model = Opportunity
        fields = [
            'id', 'type', 'title', 'description', 'organization', 'location',
            'event_date', 'external_link', 'school_scope_name', 'is_active',
            'created_at', 'is_interested',
        ]

    def get_is_interested(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if not user or not user.is_authenticated:
            return False
        return obj.interests.filter(user=user).exists()
