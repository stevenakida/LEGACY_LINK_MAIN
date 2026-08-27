from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from moderation.models import ModerationHold
from notifications.models import Notification
from notifications.services import notify

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


def _notify_authors(posts, verb, actor):
    """Phase 4B: notify each post's author their post was resolved. Takes
    already-fetched Post instances (see call sites below) rather than a
    queryset, since the caller's bulk .update() that follows would
    otherwise make a second queryset evaluation return the already-changed
    rows — snapshotting first avoids that ordering trap."""
    for post in posts:
        notify(
            post.author, verb, actor=actor, target=post,
            push_title='LegacyLink Africa',
            push_body='Your post was approved.' if verb == Notification.Verb.POST_APPROVED else 'Your post was not approved.',
        )


@admin.action(description='Approve selected posts (clears review/report hold)')
def approve_posts(modeladmin, request, queryset):
    # Scoped to PENDING rather than audience=PUBLIC: Phase 4 Step 4's
    # report_post can put a Connections/Cohort post under review too (see
    # posts.views.report_post), so this action now clears any post's hold,
    # not just the original Public-audience review queue's.
    queryset = queryset.filter(approval_status=Post.ApprovalStatus.PENDING)
    posts = list(queryset.select_related('author'))
    _resolve_holds(queryset, ModerationHold.Status.APPROVED, request.user if request else None)
    queryset.update(approval_status=Post.ApprovalStatus.APPROVED)
    _notify_authors(posts, Notification.Verb.POST_APPROVED, request.user if request else None)


@admin.action(description='Reject selected posts (keeps them hidden)')
def reject_posts(modeladmin, request, queryset):
    queryset = queryset.filter(approval_status=Post.ApprovalStatus.PENDING)
    posts = list(queryset.select_related('author'))
    _resolve_holds(queryset, ModerationHold.Status.REJECTED, request.user if request else None)
    queryset.update(approval_status=Post.ApprovalStatus.REJECTED)
    _notify_authors(posts, Notification.Verb.POST_REJECTED, request.user if request else None)


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
