from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html
from .models import User


@admin.action(description='Mark school as verified (you have checked the secondary school and year)')
def verify_school(modeladmin, request, queryset):
    eligible = queryset.filter(secondary_school__isnull=False, secondary_completion_year__isnull=False)
    done = eligible.update(school_verified_at=timezone.now())
    skipped = queryset.count() - done
    if done:
        modeladmin.message_user(request, f'{done} school(s) marked as verified.', messages.SUCCESS)
    if skipped:
        modeladmin.message_user(
            request, f'{skipped} skipped: they have no secondary school and year to verify.', messages.WARNING)


@admin.action(description='Remove school verification')
def unverify_school(modeladmin, request, queryset):
    done = queryset.filter(school_verified_at__isnull=False).update(school_verified_at=None)
    modeladmin.message_user(request, f'{done} school verification(s) removed.', messages.SUCCESS)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['avatar_preview', 'full_name', 'phone_or_email', 'email', 'email_verified', 'primary_school', 'secondary_school', 'school_verified', 'onboarding_complete', 'connections_count']
    list_filter = ['onboarding_complete', 'email_verified', ('school_verified_at', admin.EmptyFieldListFilter)]
    actions = [verify_school, unverify_school]
    search_fields = ['full_name', 'phone_or_email', 'email']
    ordering = ['-created_at']
    readonly_fields = ['avatar_preview', 'school_verified_at']
    filter_horizontal = ['groups', 'user_permissions']
    autocomplete_fields = ['primary_school', 'secondary_school', 'high_school', 'tertiary_school']
    fieldsets = (
        (None, {'fields': ('phone_or_email', 'password')}),
        ('Identity', {'fields': ('avatar_preview', 'avatar', 'full_name', 'bio', 'current_role', 'current_location')}),
        ('Contact', {'fields': ('phone_number', 'email', 'email_verified')}),
        ('Education', {'fields': ('primary_school', 'primary_completion_year', 'secondary_school', 'secondary_completion_year', 'school_verified_at', 'high_school', 'high_school_completion_year')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_or_email', 'full_name', 'password1', 'password2'),
        }),
    )

    @admin.display(description='Photo')
    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html('<img src="{}" style="width:36px;height:36px;border-radius:50%;object-fit:cover;" />', obj.avatar.url)
        return '—'

    @admin.display(description='School verified', boolean=True)
    def school_verified(self, obj):
        return obj.school_is_verified

    @admin.display(description='Connections')
    def connections_count(self, obj):
        return obj.sent_connections.filter(status='accepted').count() + obj.received_connections.filter(status='accepted').count()
