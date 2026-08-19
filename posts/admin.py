from django.contrib import admin

from .models import Post, PostHiddenFor


@admin.action(description='Approve selected Public posts')
def approve_posts(modeladmin, request, queryset):
    queryset.filter(audience=Post.Audience.PUBLIC).update(approval_status=Post.ApprovalStatus.APPROVED)


@admin.action(description='Reject selected Public posts')
def reject_posts(modeladmin, request, queryset):
    queryset.filter(audience=Post.Audience.PUBLIC).update(approval_status=Post.ApprovalStatus.REJECTED)


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
