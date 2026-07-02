from rest_framework import serializers
from .models import Connection
from accounts.serializers import UserProfileSerializer


class ConnectionSerializer(serializers.ModelSerializer):
    requester = UserProfileSerializer(read_only=True)
    receiver = UserProfileSerializer(read_only=True)

    class Meta:
        model = Connection
        fields = ['id', 'requester', 'receiver', 'status', 'created_at']