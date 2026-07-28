from .models import ConversationMember


def unread_message_count(request):
    """Makes the bottom nav's Messages badge work on every page, not just the
    inbox, without every view having to compute and pass it. This counts
    contacts with at least one unread
    message, not total unread messages — e.g. 5 unread messages from the same
    person is still "1", matching what the badge is meant to communicate.
    Unread is per-conversation (last_read_at on the membership row), so this
    loops per-conversation rather than one flat query — the user's
    conversation count is small at this scale."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    contacts_with_unread = 0
    memberships = ConversationMember.objects.filter(user=user).select_related('conversation')
    for member in memberships:
        unread_qs = member.conversation.messages.exclude(sender=user)
        if member.last_read_at:
            unread_qs = unread_qs.filter(sent_at__gt=member.last_read_at)
        if unread_qs.exists():
            contacts_with_unread += 1
    return {'unread_message_count': contacts_with_unread}
