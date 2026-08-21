from django.contrib import admin

from .models import ModerationHold


@admin.register(ModerationHold)
class ModerationHoldAdmin(admin.ModelAdmin):
    list_display = ('target', 'content_type', 'reason', 'status', 'created_at', 'resolved_at', 'resolved_by')
    list_filter = ('content_type', 'reason', 'status', 'created_at')
    search_fields = ('object_id',)
    autocomplete_fields = ('resolved_by',)
