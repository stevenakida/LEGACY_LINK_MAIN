from django.contrib import admin
from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'category', 'status', 'page_path', 'short_message')
    list_display_links = ('created_at', 'short_message')
    list_editable = ('status',)
    list_filter = ('category', 'status', 'created_at')
    search_fields = ('message', 'user__full_name', 'user__phone_or_email')
    readonly_fields = ('user', 'category', 'message', 'page_path', 'created_at')

    def short_message(self, obj):
        return (obj.message[:80] + '…') if len(obj.message) > 80 else obj.message
    short_message.short_description = 'Message'

    def has_add_permission(self, request):
        return False
