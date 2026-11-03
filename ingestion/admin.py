from django.contrib import admin

from .models import IngestedItem, SourceCheck


@admin.register(IngestedItem)
class IngestedItemAdmin(admin.ModelAdmin):
    list_display = ('source', 'external_id', 'created_at')
    list_filter = ('source',)
    search_fields = ('external_id',)
    ordering = ('-created_at',)


@admin.register(SourceCheck)
class SourceCheckAdmin(admin.ModelAdmin):
    list_display = ('source', 'consecutive_failures', 'last_checked_at', 'last_success_at', 'last_error')
    ordering = ('source',)
