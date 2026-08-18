from django.contrib import admin
from .models import Conversation, ConversationMember, Message, MessageHiddenFor


class ConversationMemberInline(admin.TabularInline):
    model = ConversationMember
    extra = 0
    autocomplete_fields = ('user',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'direct_key', 'created_at')
    list_filter = ('type',)
    inlines = [ConversationMemberInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender', 'body_preview', 'has_attachment', 'sent_at', 'is_deleted')
    list_filter = ('sent_at', 'is_deleted')
    search_fields = ('body', 'sender__full_name')

    @admin.display(description='Message')
    def body_preview(self, obj):
        return (obj.body[:60] + '…') if len(obj.body) > 60 else obj.body

    @admin.display(boolean=True, description='Has attachment')
    def has_attachment(self, obj):
        return obj.has_attachment


@admin.register(MessageHiddenFor)
class MessageHiddenForAdmin(admin.ModelAdmin):
    list_display = ('message', 'user', 'hidden_at')
    search_fields = ('user__full_name',)
    autocomplete_fields = ('user',)
