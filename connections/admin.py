from django.contrib import admin
from .models import Connection, UserRelationshipOverride

@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ['requester', 'receiver', 'status', 'created_at']
    list_filter = ['status']


@admin.register(UserRelationshipOverride)
class UserRelationshipOverrideAdmin(admin.ModelAdmin):
    list_display = ['actor', 'type', 'target', 'created_at']
    list_filter = ['type']
    search_fields = ['actor__full_name', 'target__full_name']
    autocomplete_fields = ['actor', 'target']
