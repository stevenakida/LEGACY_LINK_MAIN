from django.contrib import admin

from .models import DeviceToken


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'created_at', 'last_seen_at')
    search_fields = ('user__phone_or_email', 'user__full_name', 'token')
    list_filter = ('platform',)
