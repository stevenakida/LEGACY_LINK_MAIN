from django.contrib import admin

from .models import ContentReport, ModerationHold


@admin.register(ModerationHold)
class ModerationHoldAdmin(admin.ModelAdmin):
    list_display = ('target', 'content_type', 'reason', 'status', 'created_at', 'resolved_at', 'resolved_by')
    list_filter = ('content_type', 'reason', 'status', 'created_at')
    search_fields = ('object_id',)
    autocomplete_fields = ('resolved_by',)


@admin.register(ContentReport)
class ContentReportAdmin(admin.ModelAdmin):
    list_display = ('target', 'content_type', 'category', 'reporter', 'created_at')
    list_filter = ('content_type', 'category', 'created_at')
    search_fields = ('reporter__full_name', 'description', 'object_id')
    autocomplete_fields = ('reporter',)

    def has_add_permission(self, request):
        return False  # reports are only ever created via the report flow
