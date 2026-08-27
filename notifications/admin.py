from django.contrib import admin

from .models import DeviceToken, Notification


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'created_at', 'last_seen_at')
    search_fields = ('user__phone_or_email', 'user__full_name', 'token')
    list_filter = ('platform',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'verb', 'actor', 'created_at', 'read_at')
    list_filter = ('verb', 'read_at', 'created_at')
    search_fields = ('recipient__full_name', 'actor__full_name')
    autocomplete_fields = ('recipient', 'actor')

    def has_add_permission(self, request):
        return False  # notifications are only ever created via notifications.services.notify()
