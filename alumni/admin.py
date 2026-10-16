from django.contrib import admin, messages
from django.db.models import Count
from django.urls import path
from django.template.response import TemplateResponse
from accounts.models import User
from connections.models import Connection
from . import services
from .models import School, SchoolAlias, SchoolRequest


class SchoolAliasInline(admin.TabularInline):
    model = SchoolAlias
    extra = 1


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'school_type', 'region', 'country', 'alumni_count', 'is_active']
    search_fields = ['name', 'region', 'aliases__alias']
    inlines = [SchoolAliasInline]
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


@admin.action(description='Approve: add as a NEW school and link the requester')
def approve_as_new(modeladmin, request, queryset):
    done = 0
    for req in queryset.filter(status=SchoolRequest.Status.PENDING).select_related('user'):
        try:
            services.approve_as_new_school(req, request.user)
            done += 1
        except services.InvalidRequest as exc:
            modeladmin.message_user(request, f'"{req.name}": {exc}', messages.WARNING)
    if done:
        modeladmin.message_user(request, f'{done} school(s) added and requesters notified.', messages.SUCCESS)


@admin.action(description='Approve: it is the existing school chosen under "Resolved school" (adds the spelling as an alias)')
def approve_as_existing(modeladmin, request, queryset):
    done = 0
    for req in queryset.filter(status=SchoolRequest.Status.PENDING).select_related('user', 'resolved_school'):
        if req.resolved_school is None:
            modeladmin.message_user(
                request, f'"{req.name}": pick the existing school under "Resolved school" first, then run this again.',
                messages.WARNING)
            continue
        try:
            services.approve_as_existing(req, req.resolved_school, request.user)
            done += 1
        except services.InvalidRequest as exc:
            modeladmin.message_user(request, f'"{req.name}": {exc}', messages.WARNING)
    if done:
        modeladmin.message_user(request, f'{done} request(s) linked to existing schools and requesters notified.', messages.SUCCESS)


@admin.action(description='Reject (the requester is notified)')
def reject_requests(modeladmin, request, queryset):
    done = 0
    for req in queryset.filter(status=SchoolRequest.Status.PENDING).select_related('user'):
        services.reject(req, request.user)
        done += 1
    if done:
        modeladmin.message_user(request, f'{done} request(s) rejected.', messages.SUCCESS)


@admin.register(SchoolRequest)
class SchoolRequestAdmin(admin.ModelAdmin):
    list_display = ['name', 'school_type', 'region', 'district', 'requested_by', 'status', 'created_at']
    list_filter = ['status', 'school_type']
    search_fields = ['name', 'region', 'user__full_name', 'user__phone_or_email']
    readonly_fields = ['user', 'created_at', 'resolved_by', 'resolved_at']
    autocomplete_fields = ['resolved_school']
    actions = [approve_as_new, approve_as_existing, reject_requests]

    @admin.display(description='Requested by', ordering='user__full_name')
    def requested_by(self, obj):
        return obj.user.full_name or obj.user.phone_or_email


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
