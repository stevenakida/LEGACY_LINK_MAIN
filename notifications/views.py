from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import DeviceToken, Notification


def register_device(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    token = request.POST.get('token', '').strip()
    platform = request.POST.get('platform', 'android').strip()
    if not token:
        return JsonResponse({'error': 'token is required'}, status=400)

    DeviceToken.objects.update_or_create(
        token=token,
        defaults={'user': request.user, 'platform': platform},
    )
    return JsonResponse({'status': 'ok'})


def notifications_list(request):
    """GET /notifications/ — the topnav bell's real destination (Phase 4B).
    A plain newest-first slice, no infinite scroll this pass, matching the
    rest of the app's list views (e.g. posts.views.get_feed_for_user).
    Visiting marks every unread row read, the same way opening a
    conversation marks it read in messaging — so the bell badge clears
    just by looking at the page, no explicit 'mark as read' action needed."""
    if not request.user.is_authenticated:
        return redirect('login')

    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())

    notifications = list(
        Notification.objects.filter(recipient=request.user).select_related('actor')[:50]
    )
    return render(request, 'notifications.html', {'notifications': notifications})
