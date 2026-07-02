from django.contrib import admin
from django.db.models import Count
from django.urls import path
from django.template.response import TemplateResponse
from accounts.models import User
from connections.models import Connection
from .models import School


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'school_type', 'region', 'country', 'alumni_count', 'is_active']
    search_fields = ['name', 'region']
    list_filter = ['school_type', 'country', 'is_active']
    list_editable = ['is_active']
    ordering = ['name']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _primary_count=Count('primary_alumni', distinct=True),
            _secondary_count=Count('secondary_alumni', distinct=True),
        )

    @admin.display(description='Alumni', ordering='_primary_count')
    def alumni_count(self, obj):
        return obj._primary_count + obj._secondary_count


def admin_stats_view(request):
    context = dict(
        admin.site.each_context(request),
        title='LegacyLink Africa — Stats',
        total_users=User.objects.count(),
        onboarded_users=User.objects.filter(onboarding_complete=True).count(),
        total_schools=School.objects.count(),
        primary_schools=School.objects.filter(school_type='primary').count(),
        secondary_schools=School.objects.filter(school_type='secondary').count(),
        pending_connections=Connection.objects.filter(status='pending').count(),
        accepted_connections=Connection.objects.filter(status='accepted').count(),
    )
    return TemplateResponse(request, 'admin/stats.html', context)


_original_get_urls = admin.site.get_urls


def _get_urls():
    custom_urls = [
        path('stats/', admin.site.admin_view(admin_stats_view), name='admin-stats'),
    ]
    return custom_urls + _original_get_urls()


admin.site.get_urls = _get_urls
