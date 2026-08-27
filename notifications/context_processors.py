from .models import Notification


def total_unread_notifications(request):
    """Drives the topnav bell badge, now that the bell is a real
    notification center rather than a mislabeled shortcut to Messages —
    same shape as messaging.context_processors.total_unread_messages."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    total = Notification.objects.filter(recipient=user, read_at__isnull=True).count()
    return {'total_unread_notifications': total}
