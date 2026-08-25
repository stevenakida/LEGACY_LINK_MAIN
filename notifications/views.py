from django.http import JsonResponse

from .models import DeviceToken


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
