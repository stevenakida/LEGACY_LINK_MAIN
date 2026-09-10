from django.contrib import admin

from .models import IngestedItem


@admin.register(IngestedItem)
class IngestedItemAdmin(admin.ModelAdmin):
    list_display = ('source', 'external_id', 'created_at')
    list_filter = ('source',)
    search_fields = ('external_id',)
    ordering = ('-created_at',)
