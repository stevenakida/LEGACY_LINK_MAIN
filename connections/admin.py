from django.contrib import admin
from .models import Connection

@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ['requester', 'receiver', 'status', 'created_at']
    list_filter = ['status']
