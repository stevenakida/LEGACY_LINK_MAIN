from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['avatar_preview', 'full_name', 'phone_or_email', 'primary_school', 'secondary_school', 'onboarding_complete', 'connections_count']
    list_filter = ['primary_school', 'secondary_school', 'onboarding_complete']
    search_fields = ['full_name', 'phone_or_email']
    ordering = ['-created_at']
    readonly_fields = ['avatar_preview']
    filter_horizontal = ['groups', 'user_permissions']
    fieldsets = (
        (None, {'fields': ('phone_or_email', 'password')}),
        ('Identity', {'fields': ('avatar_preview', 'avatar', 'full_name', 'bio', 'current_role', 'current_location')}),
        ('Education', {'fields': ('primary_school', 'primary_completion_year', 'secondary_school', 'secondary_completion_year', 'high_school', 'high_school_completion_year')}),
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

    @admin.display(description='Connections')
    def connections_count(self, obj):
        return obj.sent_connections.filter(status='accepted').count() + obj.received_connections.filter(status='accepted').count()
