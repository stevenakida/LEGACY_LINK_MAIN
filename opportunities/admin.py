from django.contrib import admin
from .models import Opportunity, OpportunityInterest


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'organization', 'location', 'event_date', 'school_scope', 'is_active', 'created_at')
    list_filter = ('type', 'is_active', 'school_scope')
    search_fields = ('title', 'description', 'organization', 'location')
    autocomplete_fields = ('posted_by', 'school_scope')


@admin.register(OpportunityInterest)
class OpportunityInterestAdmin(admin.ModelAdmin):
    list_display = ('opportunity', 'user', 'created_at')
    list_filter = ('opportunity__type',)
    search_fields = ('opportunity__title', 'user__full_name')
