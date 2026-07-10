import logging
import threading
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from accounts.models import User, normalize_identifier
from alumni.models import School
from connections.models import Connection
from feedback.models import Feedback

logger = logging.getLogger(__name__)


def _send_feedback_notification(subject, message, from_email, recipient_list, feedback_id):
    """Runs on a background thread so a slow/stalled Gmail SMTP call never
    blocks the feedback-submission HTTP response (see submit_feedback)."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
    except Exception:
        # Feedback is already saved; a broken/misconfigured mail server
        # shouldn't fail the user-facing submission.
        logger.exception('Failed to send feedback notification email for Feedback %s', feedback_id)


def _send_password_reset_email(to_email, full_name, reset_url):
    """Runs on a background thread — same reasoning as _send_feedback_notification:
    never let a slow Gmail SMTP call block the HTTP response."""
    try:
        send_mail(
            subject='Reset your LegacyLink Africa password',
            message=(
                f'Hi {full_name},\n\n'
                f'We received a request to reset your LegacyLink Africa password. '
                f'Click the link below to choose a new one:\n\n'
                f'{reset_url}\n\n'
                f"If you didn't request this, you can safely ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Failed to send password reset email to %s', to_email)

def home(request):
    # If user is already authenticated, redirect to dashboard
    # Otherwise, redirect to login page
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')

def login_view(request):
    """Custom login view that handles phone_or_email authentication"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        phone_or_email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        # Try to authenticate
        user = authenticate(request, username=phone_or_email, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            # Check if user exists for better error messaging
            try:
                User.objects.get(phone_or_email__iexact=normalize_identifier(phone_or_email))
                messages.error(request, 'Invalid password. Please check your password and try again.')
            except User.DoesNotExist:
                messages.error(request, f'No account found for {phone_or_email}. Please register first.')
    
    return render(request, 'login.html')

def forgot_password(request):
    """GET shows the request form; POST sends a reset link if the entered
    address matches an email-registered account. Only works for accounts
    registered with an email for now (phone-only accounts have no channel
    to deliver a reset link to yet — SMS OTP is a future addition)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        identifier = normalize_identifier(request.POST.get('email', '').strip())
        if '@' in identifier:
            try:
                user = User.objects.get(phone_or_email__iexact=identifier)
                if user.has_usable_password():
                    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                    token = default_token_generator.make_token(user)
                    reset_url = request.build_absolute_uri(f'/reset-password/{uidb64}/{token}/')
                    threading.Thread(
                        target=_send_password_reset_email,
                        kwargs=dict(to_email=user.phone_or_email, full_name=user.full_name, reset_url=reset_url),
                        daemon=True,
                    ).start()
            except User.DoesNotExist:
                pass
        # Same message regardless of whether the account exists, so this
        # form can't be used to check which emails are registered.
        messages.success(request, "If that email is registered with us, we've sent a link to reset your password.")
        return redirect('login')

    return render(request, 'forgot_password.html')

def reset_password_confirm(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        messages.error(request, 'This password reset link is invalid or has expired. Please request a new one.')
        return redirect('forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            user.set_password(password)
            user.save()
            messages.success(request, 'Your password has been reset. Please sign in.')
            return redirect('login')

    return render(request, 'reset_password_confirm.html', {'uidb64': uidb64, 'token': token})

def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        phone_or_email = request.POST.get('phone_or_email')
        full_name = request.POST.get('full_name')
        password = request.POST.get('password')
        agree_terms = request.POST.get('agree_terms')

        if not agree_terms:
            messages.error(request, 'You must accept the Terms of Use, Privacy and Data Usage Policy to create an account.')
            return render(request, 'register.html')

        try:
            user = User.objects.create_user(phone_or_email, password, full_name=full_name)
            login(request, user)
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f'Registration failed: {str(e)}')
            return render(request, 'register.html')
    return render(request, 'register.html')

def terms(request):
    return render(request, 'terms.html')

def dashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')

    user = request.user
    accepted_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).select_related('requester', 'receiver')

    pending_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='pending')
    ).select_related('requester', 'receiver')

    cohort_users = User.objects.none()
    cohort_count = 0
    if user.secondary_school and user.secondary_completion_year:
        cohort_users = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id)[:4]
        cohort_count = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id).count()

    connections_count = accepted_connections.count()
    pending_count = pending_connections.count()

    hour = timezone.localtime().hour
    if hour < 12:
        greeting = 'Good Morning'
    elif hour < 17:
        greeting = 'Good Afternoon'
    else:
        greeting = 'Good Evening'

    first_name = (user.full_name or user.phone_or_email).split(' ')[0]

    school_confirmed = bool(user.secondary_school and user.secondary_completion_year)
    community_confirmed = connections_count > 0
    if school_confirmed:
        trust_label = 'School Verified'
    elif community_confirmed:
        trust_label = 'Community Verified'
    else:
        trust_label = 'Getting Started'

    return render(request, 'dashboard.html', {
        'user': user,
        'connections_count': connections_count,
        'pending_count': pending_count,
        'cohort_count': cohort_count,
        'cohort_users': cohort_users,
        'identity_score': user.identity_score,
        'identity_score_suggestions': user.identity_score_suggestions[:4],
        'accepted_connections': accepted_connections,
        'greeting': greeting,
        'first_name': first_name,
        'school_confirmed': school_confirmed,
        'community_confirmed': community_confirmed,
        'trust_label': trust_label,
    })

def profile(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method == 'POST':
        user = request.user
        user.full_name = request.POST.get('full_name', user.full_name)
        user.bio = request.POST.get('bio', user.bio)
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        user.email = request.POST.get('email', user.email)
        user.current_role = request.POST.get('current_role', user.current_role)
        user.current_location = request.POST.get('current_location', user.current_location)
        
        # Educational background
        primary_school_id = request.POST.get('primary_school')
        if primary_school_id:
            try:
                user.primary_school = School.objects.get(id=primary_school_id, school_type='primary')
            except School.DoesNotExist:
                user.primary_school = None
        else:
            user.primary_school = None
        user.primary_completion_year = request.POST.get('primary_completion_year') or None
        
        secondary_school_id = request.POST.get('secondary_school')
        if secondary_school_id:
            try:
                user.secondary_school = School.objects.get(id=secondary_school_id, school_type='secondary')
            except School.DoesNotExist:
                user.secondary_school = None
        else:
            user.secondary_school = None
        user.secondary_completion_year = request.POST.get('secondary_completion_year') or None

        high_school_id = request.POST.get('high_school')
        if high_school_id:
            try:
                user.high_school = School.objects.get(id=high_school_id, school_type='high_school')
            except School.DoesNotExist:
                user.high_school = None
        else:
            user.high_school = None
        user.high_school_completion_year = request.POST.get('high_school_completion_year') or None

        tertiary_school_id = request.POST.get('tertiary_school')
        if tertiary_school_id:
            try:
                user.tertiary_school = School.objects.get(id=tertiary_school_id, school_type='university')
            except School.DoesNotExist:
                user.tertiary_school = None
        else:
            user.tertiary_school = None
        user.tertiary_completion_year = request.POST.get('tertiary_completion_year') or None

        user.employment_status = request.POST.get('employment_status', user.employment_status)
        user.company_name = request.POST.get('company_name', user.company_name)

        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        user.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('dashboard')
    user = request.user
    # If the user hasn't filled in phone_number/email yet, default whichever
    # one matches what they registered with (phone_or_email) — they only
    # need to type the one they didn't already give us at signup.
    phone_number_value = user.phone_number or ('' if '@' in user.phone_or_email else user.phone_or_email)
    email_value = user.email or (user.phone_or_email if '@' in user.phone_or_email else '')
    return render(request, 'profile.html', {
        'user': request.user,
        'phone_number_value': phone_number_value,
        'email_value': email_value,
        'employment_status_choices': User.EMPLOYMENT_STATUS_CHOICES,
    })

def schools(request):
    if not request.user.is_authenticated:
        return redirect('login')
    # For now, returning empty opportunities list as template has mock data
    # In future, this can be populated from an Opportunities model
    return render(request, 'schools.html', {'user': request.user})

def school_search(request):
    """GET /schools/search/?type=primary&q=Jangwani — session-authenticated
    JSON lookup for the school autocomplete fields. Kept as a plain Django
    view (not the DRF API) since the DRF endpoints are JWT-only and this is
    called from the browser using the logged-in session."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    query = request.GET.get('q', '').strip()
    school_type = request.GET.get('type', '').strip()
    if not query or school_type not in dict(School.TYPE_CHOICES):
        return JsonResponse({'results': []})

    matches = School.objects.filter(
        is_active=True, school_type=school_type, name__icontains=query
    ).order_by('name')[:20]

    results = [
        {
            'id': s.id,
            'name': s.name,
            'region': s.region,
            'district': s.district,
        }
        for s in matches
    ]
    return JsonResponse({'results': results})

def submit_feedback(request):
    """POST /feedback/submit/ — session-authenticated JSON endpoint used by the
    floating feedback widget on the main app pages. Kept as a plain Django
    view (like school_search) since it's called from in-page JS using the
    logged-in session, not the JWT-only DRF API."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    message = request.POST.get('message', '').strip()
    if not message:
        return JsonResponse({'error': 'Please enter a message before sending.'}, status=400)

    category = request.POST.get('category', 'other')
    if category not in dict(Feedback.CATEGORY_CHOICES):
        category = 'other'

    entry = Feedback.objects.create(
        user=request.user,
        category=category,
        message=message[:2000],
        page_path=request.POST.get('page_path', '')[:300],
    )

    if settings.FEEDBACK_NOTIFY_EMAIL:
        threading.Thread(
            target=_send_feedback_notification,
            kwargs=dict(
                subject=f'[LegacyLink Feedback] {entry.get_category_display()} from {request.user.full_name}',
                message=(
                    f'{entry.get_category_display()} from {request.user.full_name} '
                    f'({request.user.phone_or_email})\n'
                    f'Page: {entry.page_path or "unknown"}\n\n'
                    f'{entry.message}'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.FEEDBACK_NOTIFY_EMAIL],
                feedback_id=entry.id,
            ),
            daemon=True,
        ).start()

    return JsonResponse({'ok': True})

def connections(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    accepted_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).select_related('requester', 'receiver')
    pending_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='pending')
    ).select_related('requester', 'receiver')

    return render(request, 'connections.html', {
        'connections': accepted_connections,
        'pending_connections': pending_connections,
        'accepted_count': accepted_connections.count(),
        'pending_count': pending_connections.count(),
    })

def select_school(request, school_id):
    if not request.user.is_authenticated:
        return redirect('login')
    try:
        school = School.objects.get(id=school_id, school_type='secondary')
        user = request.user
        user.secondary_school = school
        user.save()
        messages.success(request, f'School updated to {school.name}')
        return redirect('profile')
    except School.DoesNotExist:
        messages.error(request, 'School not found.')
        return redirect('schools')

def cohort(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    cohort_users = User.objects.none()
    cohort_count = 0
    
    if user.secondary_school and user.secondary_completion_year:
        cohort_users = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id)
        cohort_count = cohort_users.count()
    
    return render(request, 'cohort.html', {
        'cohort_users': cohort_users,
        'cohort_count': cohort_count,
        'user': user
    })

def onboarding(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method == 'POST':
        user = request.user
        school_id = request.POST.get('school')
        graduation_year = request.POST.get('graduation_year')
        if school_id and graduation_year:
            try:
                user.secondary_school = School.objects.get(id=school_id, school_type='secondary')
                user.secondary_completion_year = int(graduation_year)
                user.onboarding_complete = True
                user.save()
                messages.success(request, 'Onboarding completed!')
                return redirect('dashboard')
            except (School.DoesNotExist, ValueError):
                messages.error(request, 'Invalid school or graduation year.')
        else:
            messages.error(request, 'Please fill all fields.')
    return render(request, 'onboarding.html')