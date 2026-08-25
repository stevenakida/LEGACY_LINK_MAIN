from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from moderation.models import ModerationHold

from .models import Post, PostHiddenFor


def _resolve_holds(queryset, status, resolved_by):
    """Keep moderation.ModerationHold in sync with the approval_status
    bulk-update below — same (content_type, object_id) rows opened by
    ModerationHold.open_or_reopen() in posts.views.create_post. A plain
    bulk .update() rather than looping+resolve() since every row gets the
    same status/resolver/timestamp here."""
    content_type = ContentType.objects.get_for_model(Post)
    ModerationHold.objects.filter(
        content_type=content_type, object_id__in=queryset.values_list('pk', flat=True)
    ).update(status=status, resolved_at=timezone.now(), resolved_by=resolved_by)


@admin.action(description='Approve selected Public posts')
def approve_posts(modeladmin, request, queryset):
    queryset = queryset.filter(audience=Post.Audience.PUBLIC)
    _resolve_holds(queryset, ModerationHold.Status.APPROVED, request.user if request else None)
    queryset.update(approval_status=Post.ApprovalStatus.APPROVED)


@admin.action(description='Reject selected Public posts')
def reject_posts(modeladmin, request, queryset):
    queryset = queryset.filter(audience=Post.Audience.PUBLIC)
    _resolve_holds(queryset, ModerationHold.Status.REJECTED, request.user if request else None)
    queryset.update(approval_status=Post.ApprovalStatus.REJECTED)


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('author', 'audience', 'approval_status', 'created_at', 'has_media')
    list_filter = ('audience', 'approval_status', 'created_at')
    search_fields = ('author__full_name', 'body')
    autocomplete_fields = ('author',)
    actions = [approve_posts, reject_posts]

    @admin.display(boolean=True, description='Has media')
    def has_media(self, obj):
        return obj.media_asset_id is not None


@admin.register(PostHiddenFor)
class PostHiddenForAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'hidden_at')
    search_fields = ('user__full_name',)
    autocomplete_fields = ('user',)
