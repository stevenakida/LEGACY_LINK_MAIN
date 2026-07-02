from django.contrib import admin
from .models import School

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'region', 'country', 'school_type']
    search_fields = ['name', 'region']
    list_filter = ['school_type', 'country']
