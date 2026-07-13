from .models import ConversationMember


def unread_message_count(request):
    """Makes the bottom nav's Messages badge work on every page, not just
    the inbox, without every view having to compute and pass it. Unread is
    per-conversation (last_read_at on the membership row), so this sums a
    small per-conversation loop rather than one flat query — the user's
    conversation count is small at this scale."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    total = 0
    memberships = ConversationMember.objects.filter(user=user).select_related('conversation')
    for member in memberships:
        unread_qs = member.conversation.messages.exclude(sender=user)
        if member.last_read_at:
            unread_qs = unread_qs.filter(sent_at__gt=member.last_read_at)
        total += unread_qs.count()
    return {'unread_message_count': total}
