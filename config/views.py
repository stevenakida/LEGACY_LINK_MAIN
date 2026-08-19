import logging
import threading
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from accounts.models import User, normalize_identifier
from alumni.models import School
from connections.models import Connection, UserRelationshipOverride
from feedback.models import Feedback
from opportunities.models import Opportunity, OpportunityInterest
from media_assets import services as media_services
from media_assets.models import MediaAsset
from messaging.models import (
    Conversation, ConversationMember, Message as ChatMessage, MessageAttachment, MessageHiddenFor,
)
from posts.views import get_feed_for_user

logger = logging.getLogger(__name__)


def _set_language_cookie(response, code):
    """Django 6 dropped session-based language storage (LANGUAGE_SESSION_KEY
    no longer exists) — LocaleMiddleware now reads the language purely from
    the `django_language` cookie, so persisting a chosen language means
    setting that cookie on the response, same as django.views.i18n.set_language."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        code,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


def _annotate_connection_status(user, people):
    """Attach a `.connection_status` ('none' / 'pending' / 'accepted' /
    'declined') to each User instance in `people`, based on any existing
    Connection with `user` — so templates can show Connect vs. Pending vs.
    Connected instead of always offering to send a duplicate request."""
    people = list(people)
    if not people:
        return people
    ids = [p.id for p in people]
    existing = Connection.objects.filter(
        (Q(requester=user) & Q(receiver_id__in=ids)) | (Q(receiver=user) & Q(requester_id__in=ids))
    )
    status_map = {}
    for c in existing:
        other_id = c.receiver_id if c.requester_id == user.id else c.requester_id
        status_map[other_id] = c.status
    for p in people:
        p.connection_status = status_map.get(p.id, 'none')
    return people


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
            # Returning users land in their saved language immediately,
            # without needing to re-toggle EN/SW after every login.
            translation.activate(user.preferred_language)
            return _set_language_cookie(redirect('dashboard'), user.preferred_language)
        else:
            # Check if user exists for better error messaging
            try:
                User.objects.get(phone_or_email__iexact=normalize_identifier(phone_or_email))
                messages.error(request, 'Invalid password. Please check your password and try again.')
            except User.DoesNotExist:
                messages.error(request, f'No account found for {phone_or_email}. Please register first.')

        return render(request, 'login.html', {
            'submitted_username': phone_or_email,
            'submitted_password': password,
        })

    return render(request, 'login.html')


def set_language_web(request):
    """POST /set-language/ — the top nav EN/SW toggle. Activates the language
    for this request/session immediately (so the reload the caller triggers
    picks it up) and, for logged-in users, persists it on the User row so it
    survives across devices/sessions instead of just this browser."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    code = request.POST.get('language', '')
    if code not in dict(settings.LANGUAGES):
        return JsonResponse({'error': 'Unsupported language'}, status=400)

    translation.activate(code)

    if request.user.is_authenticated:
        request.user.preferred_language = code
        request.user.save(update_fields=['preferred_language'])

    return _set_language_cookie(JsonResponse({'language': code}), code)


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

    # Exclude blocked users same as the Discover tab (connections()) — a
    # blocked person shouldn't be suggested here either.
    blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    cohort_full_qs = user.cohort_queryset().exclude(id__in=blocked_ids)
    cohort_count = cohort_full_qs.count()
    cohort_users = _annotate_connection_status(user, cohort_full_qs[:4])

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

    active_opportunities = Opportunity.objects.filter(is_active=True)
    opportunities_count = active_opportunities.exclude(type='event').count()
    upcoming_events = list(
        active_opportunities.filter(type='event', event_date__gte=timezone.now()).order_by('event_date')[:3]
    )
    events_count = active_opportunities.filter(type='event').count()

    feed_posts = get_feed_for_user(user)

    return render(request, 'dashboard.html', {
        'user': user,
        'connections_count': connections_count,
        'pending_count': pending_count,
        'cohort_count': cohort_count,
        'cohort_users': cohort_users,
        'identity_score': user.identity_score,
        'identity_score_suggestions': user.identity_score_suggestions[:4],
        'greeting': greeting,
        'first_name': first_name,
        'opportunities_count': opportunities_count,
        'events_count': events_count,
        'upcoming_events': upcoming_events,
        'feed_posts': feed_posts,
        'active_tab': 'home',
    })

def view_profile(request, user_id):
    """Read-only preview of another user's profile — reachable from any of
    the Connections tabs (Pending/Connected/Discover) so someone can check a
    person's education history, bio, join date, and mutual connections
    before deciding to accept/send a request. No editing, and no contact
    info (phone/email) is shown here regardless of connection status."""
    if not request.user.is_authenticated:
        return redirect('login')
    if str(user_id) == str(request.user.id):
        return redirect('profile')

    try:
        profile_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'That profile could not be found.')
        return redirect('connections')

    school_confirmed = bool(profile_user.secondary_school and profile_user.secondary_completion_year)
    accepted_count = Connection.objects.filter(
        (Q(requester=profile_user) | Q(receiver=profile_user)) & Q(status='accepted')
    ).count()
    community_confirmed = accepted_count > 0
    if school_confirmed:
        trust_label = 'School Verified'
    elif community_confirmed:
        trust_label = 'Community Verified'
    else:
        trust_label = 'Getting Started'

    mutual_count = len(_mutual_connection_ids(request.user) & _mutual_connection_ids(profile_user))

    conn = Connection.objects.filter(
        (Q(requester=request.user) & Q(receiver=profile_user)) | (Q(requester=profile_user) & Q(receiver=request.user))
    ).first()
    connection_status = conn.status if conn else 'none'
    # Only surface Accept/Decline here when *this* user is the one who needs
    # to respond — i.e. the pending request was sent TO them, not BY them.
    incoming_pending = conn if (conn and conn.status == 'pending' and conn.receiver_id == request.user.id) else None

    next_url = request.GET.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = '/connections/'

    is_blocked = UserRelationshipOverride.objects.filter(
        actor=request.user, target=profile_user, type=UserRelationshipOverride.Type.BLOCK
    ).exists()
    is_muted = UserRelationshipOverride.objects.filter(
        actor=request.user, target=profile_user, type=UserRelationshipOverride.Type.MUTE
    ).exists()

    return render(request, 'public_profile.html', {
        'profile_user': profile_user,
        'trust_label': trust_label,
        'school_confirmed': school_confirmed,
        'community_confirmed': community_confirmed,
        'mutual_count': mutual_count,
        'connection': conn,
        'connection_status': connection_status,
        'incoming_pending': incoming_pending,
        'is_blocked': is_blocked,
        'is_muted': is_muted,
        'next_url': next_url,
        'active_tab': 'network',
    })

def profile(request):
    """View-mode: how the user's own profile looks to others (avatar, bio,
    verified badge, education timeline, profile-strength ring). Editing
    happens at /profile/edit/ (see profile_edit)."""
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    connections_count = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).count()
    school_confirmed = bool(user.secondary_school and user.secondary_completion_year)
    community_confirmed = connections_count > 0
    if school_confirmed:
        trust_label = 'School Verified'
    elif community_confirmed:
        trust_label = 'Community Verified'
    else:
        trust_label = 'Getting Started'

    return render(request, 'profile.html', {
        'user': user,
        'identity_score': user.identity_score,
        'identity_score_suggestions': user.identity_score_suggestions[:4],
        'school_confirmed': school_confirmed,
        'community_confirmed': community_confirmed,
        'trust_label': trust_label,
        'active_tab': 'profile',
    })


def profile_edit(request):
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
        return redirect('profile')
    user = request.user
    # If the user hasn't filled in phone_number/email yet, default whichever
    # one matches what they registered with (phone_or_email) — they only
    # need to type the one they didn't already give us at signup.
    phone_number_value = user.phone_number or ('' if '@' in user.phone_or_email else user.phone_or_email)
    email_value = user.email or (user.phone_or_email if '@' in user.phone_or_email else '')
    return render(request, 'profile_edit.html', {
        'user': request.user,
        'phone_number_value': phone_number_value,
        'email_value': email_value,
        'employment_status_choices': User.EMPLOYMENT_STATUS_CHOICES,
        'active_tab': 'profile',
    })

def opportunities_page(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user

    opp_type = request.GET.get('type', 'all')
    if opp_type not in dict(Opportunity.TYPE_CHOICES):
        opp_type = 'all'
    school_only = request.GET.get('school') == 'mine'

    opportunities_qs = Opportunity.objects.filter(is_active=True).select_related('school_scope', 'posted_by')
    if opp_type != 'all':
        opportunities_qs = opportunities_qs.filter(type=opp_type)
    if school_only:
        my_school_ids = [
            sid for sid in (user.primary_school_id, user.secondary_school_id, user.high_school_id, user.tertiary_school_id)
            if sid
        ]
        opportunities_qs = opportunities_qs.filter(school_scope_id__in=my_school_ids)

    opportunities_list = list(opportunities_qs)
    interested_ids = set(
        OpportunityInterest.objects.filter(user=user, opportunity__in=opportunities_list).values_list('opportunity_id', flat=True)
    )
    for opp in opportunities_list:
        opp.user_interested = opp.id in interested_ids

    return render(request, 'opportunities.html', {
        'user': user,
        'opportunities': opportunities_list,
        'opp_type': opp_type,
        'school_only': school_only,
        'active_tab': 'opportunities',
    })


def toggle_opportunity_interest(request, opportunity_id):
    """POST-only: Apply/Join/RSVP toggle — creates or removes a lightweight
    OpportunityInterest row, same shape as the Connect button's
    send_connection_web. Not a full application workflow."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('opportunities')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'opportunities'

    try:
        opportunity = Opportunity.objects.get(id=opportunity_id, is_active=True)
    except Opportunity.DoesNotExist:
        messages.error(request, 'That opportunity could not be found.')
        return redirect(next_url)

    interest, created = OpportunityInterest.objects.get_or_create(opportunity=opportunity, user=request.user)
    if not created:
        interest.delete()

    return redirect(next_url)

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

def _mutual_connection_ids(user):
    """Set of user ids `user` has an accepted connection with."""
    pairs = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).values_list('requester_id', 'receiver_id')
    ids = set()
    for a, b in pairs:
        ids.update((a, b))
    ids.discard(user.id)
    return ids


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

    # Discover: cohort matches (same school+year) who aren't already pending/
    # accepted/declined with this user, and aren't blocked in either
    # direction — surfacing a blocked person as a suggestion would defeat
    # the point of blocking them.
    blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    discover_users = _annotate_connection_status(user, user.cohort_queryset())
    discover_users = [p for p in discover_users if p.connection_status == 'none' and p.id not in blocked_ids]

    # Mutual-connection count per discover candidate — one query per
    # candidate, intentionally simple at current scale rather than a bulk
    # join, since this list is small (cohort matches only).
    my_accepted_ids = _mutual_connection_ids(user)
    for person in discover_users:
        person.mutual_count = len(my_accepted_ids & _mutual_connection_ids(person))

    requested_tab = request.GET.get('tab', 'pending')
    if requested_tab not in ('pending', 'connected', 'discover'):
        requested_tab = 'pending'

    return render(request, 'connections.html', {
        'connections': accepted_connections,
        'pending_connections': pending_connections,
        'discover_users': discover_users,
        'accepted_count': accepted_connections.count(),
        'pending_count': pending_connections.count(),
        'discover_count': len(discover_users),
        'connections_tab': requested_tab,
        'active_tab': 'network',
    })

def send_connection_web(request, user_id):
    """POST-only: send a connection request from the logged-in user to
    another user, used by the 'Connect' buttons on the dashboard's
    Suggested for You carousel and the cohort page's classmate cards."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        receiver = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'That user could not be found.')
        return redirect(next_url)

    if receiver.id == request.user.id:
        messages.error(request, "You can't connect with yourself.")
        return redirect(next_url)

    if UserRelationshipOverride.is_blocked(request.user, receiver):
        messages.error(request, 'You can’t connect with this user.')
        return redirect(next_url)

    existing = Connection.objects.filter(
        (Q(requester=request.user) & Q(receiver=receiver)) | (Q(requester=receiver) & Q(receiver=request.user))
    ).first()
    if existing:
        messages.info(request, f'You already have a connection with {receiver.full_name}.')
    else:
        Connection.objects.create(requester=request.user, receiver=receiver)
        messages.success(request, f'Connection request sent to {receiver.full_name}.')

    return redirect(next_url)

def respond_connection_web(request, connection_id):
    """POST-only: accept or decline a connection request that was sent to
    the logged-in user. Used by the Accept/Decline buttons on the
    Pending Requests section of /connections/."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    # Scoped to receiver=request.user so only the actual recipient of the
    # request can accept/decline it, not just anyone who knows the id.
    try:
        conn = Connection.objects.get(id=connection_id, receiver=request.user)
    except Connection.DoesNotExist:
        messages.error(request, 'That connection request could not be found.')
        return redirect(next_url)

    action = request.POST.get('action')
    if action == 'accept':
        conn.status = 'accepted'
        conn.save()
        messages.success(request, f'You are now connected with {conn.requester.full_name}.')
    elif action == 'decline':
        conn.status = 'declined'
        conn.save()
        messages.info(request, f'Declined the request from {conn.requester.full_name}.')
    else:
        messages.error(request, 'Invalid action.')

    return redirect(next_url)

def remove_connection_web(request, connection_id):
    """POST-only: remove an existing (accepted) connection — used by the
    'Remove' button on the Connected tab, e.g. when someone turns out not to
    be who they claimed. Scoped to requester-or-receiver so only the two
    people in the connection can remove it. This deletes the Connection row
    outright rather than adding a new status, so the two can reconnect later
    if it was a mistake; it does not touch or hide the message thread between
    them, if any."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        conn = Connection.objects.get(
            Q(id=connection_id) & (Q(requester=request.user) | Q(receiver=request.user)),
            status='accepted',
        )
    except Connection.DoesNotExist:
        messages.error(request, 'That connection could not be found.')
        return redirect(next_url)

    other = conn.receiver if conn.requester == request.user else conn.requester
    conn.delete()
    messages.info(request, f'Removed your connection with {other.full_name}.')

    return redirect(next_url)

def dismiss_discover_web(request, user_id):
    """POST-only: dismiss a suggested classmate on the Discover tab ('not
    interested in connecting') — the red X next to Connect. Recorded as a
    one-sided 'declined' Connection (no request was ever sent, so nothing is
    sent to the other person / no notification), which reuses the same
    filter that already hides declined connections from Discover."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect(next_url)

    if other.id == request.user.id:
        return redirect(next_url)

    # Check both directions, not just requester=me — a row could already
    # exist the other way round (e.g. they'd sent me a request), and
    # get_or_create only matching one direction would create a duplicate
    # row for the same pair instead of respecting the existing one.
    existing = Connection.objects.filter(
        (Q(requester=request.user) & Q(receiver=other)) | (Q(requester=other) & Q(receiver=request.user))
    ).first()
    if not existing:
        Connection.objects.create(requester=request.user, receiver=other, status='declined')

    messages.info(request, f'{other.full_name} removed from Discover.')

    return redirect(next_url)

def block_user_web(request, user_id):
    """POST-only: block another user — severs any existing Connection
    between the two (pending or accepted; a block supersedes it outright,
    same reasoning as remove_connection_web deleting rather than
    soft-declining) and, going forward, hides both users' posts from each
    other (posts._visible_posts_queryset), blocks new connection requests
    in either direction, and blocks new messages between them
    (messages_send). Existing message history stays readable — block cuts
    off new contact, it doesn't erase the past."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'That user could not be found.')
        return redirect(next_url)

    if other.id == request.user.id:
        messages.error(request, "You can't block yourself.")
        return redirect(next_url)

    UserRelationshipOverride.objects.get_or_create(
        actor=request.user, target=other, type=UserRelationshipOverride.Type.BLOCK
    )
    Connection.objects.filter(
        (Q(requester=request.user) & Q(receiver=other)) | (Q(requester=other) & Q(receiver=request.user))
    ).delete()

    messages.success(request, f'{other.full_name} has been blocked.')
    return redirect(next_url)

def unblock_user_web(request, user_id):
    """POST-only: undo block_user_web. Only removes the override row this
    user created — if the other person also has an independent block row
    pointed the other way (they blocked first, then this user blocked
    back), that row is untouched and the block stays in effect from their
    side, matching how a one-sided unblock should behave."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect(next_url)

    UserRelationshipOverride.objects.filter(
        actor=request.user, target=other, type=UserRelationshipOverride.Type.BLOCK
    ).delete()
    messages.info(request, f'{other.full_name} has been unblocked.')
    return redirect(next_url)

def mute_user_web(request, user_id):
    """POST-only: mute another user — their posts stop appearing in this
    user's feed (posts.get_feed_for_user only). One-directional, silent
    (the muted user is never told), and has no effect on messaging,
    connections, or the muted user's own view of anything."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'That user could not be found.')
        return redirect(next_url)

    if other.id == request.user.id:
        messages.error(request, "You can't mute yourself.")
        return redirect(next_url)

    UserRelationshipOverride.objects.get_or_create(
        actor=request.user, target=other, type=UserRelationshipOverride.Type.MUTE
    )
    messages.success(request, f'{other.full_name} has been muted.')
    return redirect(next_url)

def unmute_user_web(request, user_id):
    """POST-only: undo mute_user_web."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    next_url = request.POST.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = 'connections'

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect(next_url)

    UserRelationshipOverride.objects.filter(
        actor=request.user, target=other, type=UserRelationshipOverride.Type.MUTE
    ).delete()
    messages.info(request, f'{other.full_name} has been unmuted.')
    return redirect(next_url)

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
        return redirect('opportunities')

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


MESSAGES_PAGE_SIZE = 30
SEND_RATE_LIMIT = 20  # messages per user per rolling minute


def _has_accepted_connection(user_a, user_b):
    return Connection.objects.filter(
        (Q(requester=user_a) & Q(receiver=user_b)) | (Q(requester=user_b) & Q(receiver=user_a)),
        status='accepted',
    ).exists()


def _mark_read(conversation, user):
    ConversationMember.objects.filter(conversation=conversation, user=user).update(last_read_at=timezone.now())


def _message_image_url(message):
    if not message.has_attachment:
        return None
    return reverse('message_attachment_image', kwargs={'message_id': message.id})


def _message_reply_preview(message):
    """Small quoted-reply summary for JSON payloads — None when the
    message isn't a reply, or when the original was hard-deleted
    (reply_to is SET_NULL in that case, not an error)."""
    original = message.reply_to
    if original is None:
        return None
    return {
        'id': str(original.id),
        'sender_name': original.sender.full_name,
        'snippet': (original.body[:80] if original.body else '📷 Photo'),
    }


def messages_inbox(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    conversations = Conversation.objects.filter(participants__user=user).distinct().prefetch_related('participants__user', 'messages__sender')
    memberships_by_conv = {
        m.conversation_id: m for m in ConversationMember.objects.filter(user=user, conversation__in=conversations)
    }

    rows = []
    for conv in conversations:
        other = conv.other_participant(user)
        if not other:
            continue
        visible_messages = conv.messages.exclude(hidden_for__user=user)
        last_message = visible_messages.select_related('attachment').order_by('-sent_at').first()
        last_read_at = memberships_by_conv[conv.id].last_read_at if conv.id in memberships_by_conv else None
        unread_qs = visible_messages.exclude(sender=user)
        if last_read_at:
            unread_qs = unread_qs.filter(sent_at__gt=last_read_at)
        rows.append({
            'conversation': conv,
            'other': other,
            'last_message': last_message,
            'unread_count': unread_qs.count(),
        })
    rows.sort(key=lambda r: r['last_message'].sent_at if r['last_message'] else r['conversation'].created_at, reverse=True)

    return render(request, 'messages.html', {
        'conversation_rows': rows,
        'active_tab': 'messages',
    })


def messages_start(request, user_id):
    """POST-only: start (or resume) a conversation with another user — only
    allowed when an accepted Connection exists between them, per the
    roadmap's 'restrict to accepted connections' rule. Used by the Message
    button on the Connections page's Connected tab.

    Looked up/created by `direct_key` (a DB-unique "minId:maxId" pair key)
    rather than a filter-then-create query — that avoids a race condition
    where two near-simultaneous clicks could otherwise create two separate
    conversations for the same pair."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')

    try:
        other = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'That user could not be found.')
        return redirect('connections')

    if not _has_accepted_connection(request.user, other):
        messages.error(request, 'You can only message accepted connections.')
        return redirect('connections')

    key = Conversation.direct_key_for(request.user, other)
    conversation, created = Conversation.objects.get_or_create(
        direct_key=key, defaults={'type': Conversation.ConversationType.DIRECT}
    )
    if created:
        ConversationMember.objects.create(conversation=conversation, user=request.user)
        ConversationMember.objects.create(conversation=conversation, user=other)

    return redirect('messages_thread', conversation_id=conversation.id)


def messages_thread(request, conversation_id):
    if not request.user.is_authenticated:
        return redirect('login')
    try:
        conversation = Conversation.objects.get(id=conversation_id, participants__user=request.user)
    except Conversation.DoesNotExist:
        messages.error(request, 'Conversation not found.')
        return redirect('messages_inbox')

    other = conversation.other_participant(request.user)
    visible_messages = conversation.messages.exclude(hidden_for__user=request.user)
    # Latest page only; older messages load via messages_earlier on scroll.
    latest_messages = list(
        visible_messages.select_related('sender', 'attachment', 'reply_to__sender').order_by('-sent_at')[:MESSAGES_PAGE_SIZE]
    )
    latest_messages.reverse()
    has_earlier = visible_messages.count() > len(latest_messages)
    _mark_read(conversation, request.user)

    # One query for the forward-target list, not one per conversation —
    # c.other_participant(user) each does its own exclude().first() query,
    # which doesn't benefit from prefetch_related since exclude() builds a
    # fresh queryset rather than reusing the prefetched cache.
    other_memberships = ConversationMember.objects.filter(
        conversation__in=Conversation.objects.filter(participants__user=request.user).exclude(id=conversation.id)
    ).exclude(user=request.user).select_related('user', 'conversation')
    other_conversations = [
        {'id': str(m.conversation_id), 'name': m.user.full_name} for m in other_memberships
    ]

    return render(request, 'chat.html', {
        'conversation': conversation,
        'other': other,
        'thread_messages': latest_messages,
        'has_earlier': has_earlier,
        'other_conversations': other_conversations,
        'active_tab': 'messages',
    })


def messages_earlier(request, conversation_id):
    """GET ?before=<message_id> — session-authenticated JSON endpoint for
    'load earlier' when the chat thread's JS detects a scroll-to-top.
    Returns up to MESSAGES_PAGE_SIZE messages older than `before`."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    try:
        conversation = Conversation.objects.get(id=conversation_id, participants__user=request.user)
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    visible_messages = conversation.messages.exclude(hidden_for__user=request.user)
    older_messages = visible_messages.select_related('sender', 'attachment', 'reply_to__sender').order_by('-sent_at')
    before = request.GET.get('before')
    if before:
        try:
            before_msg = ChatMessage.objects.get(id=before)
            older_messages = older_messages.filter(sent_at__lt=before_msg.sent_at)
        except (ChatMessage.DoesNotExist, ValueError):
            pass

    page = list(older_messages[:MESSAGES_PAGE_SIZE])
    page.reverse()
    has_earlier = visible_messages.filter(sent_at__lt=page[0].sent_at).exists() if page else False

    return JsonResponse({
        'has_earlier': has_earlier,
        'messages': [
            {
                'id': str(m.id), 'body': m.body, 'is_me': m.sender_id == request.user.id,
                'sent_at': m.sent_at.strftime('%H:%M'), 'image_url': _message_image_url(m),
                'reply_to': _message_reply_preview(m), 'is_forwarded': m.forwarded_from_id is not None,
            }
            for m in page
        ],
    })


def messages_poll(request, conversation_id):
    """GET ?after=<message_id> — session-authenticated JSON endpoint the
    chat thread's JS polls every few seconds. Simple polling, not Channels/
    WebSockets, per the roadmap doc's own recommendation and this project's
    lack of any channels/redis infra."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    try:
        conversation = Conversation.objects.get(id=conversation_id, participants__user=request.user)
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    new_messages = conversation.messages.exclude(hidden_for__user=request.user) \
        .select_related('sender', 'attachment', 'reply_to__sender').order_by('sent_at')
    after = request.GET.get('after')
    if after:
        try:
            after_msg = ChatMessage.objects.get(id=after)
            new_messages = new_messages.filter(sent_at__gt=after_msg.sent_at)
        except (ChatMessage.DoesNotExist, ValueError):
            pass

    new_messages = list(new_messages)
    if new_messages:
        _mark_read(conversation, request.user)

    return JsonResponse({'messages': [
        {
            'id': str(m.id), 'body': m.body, 'is_me': m.sender_id == request.user.id,
            'sent_at': m.sent_at.strftime('%H:%M'), 'image_url': _message_image_url(m),
            'reply_to': _message_reply_preview(m), 'is_forwarded': m.forwarded_from_id is not None,
        }
        for m in new_messages
    ]})


def messages_send(request, conversation_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        conversation = Conversation.objects.get(id=conversation_id, participants__user=request.user)
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    # messages_start already refuses to open a NEW conversation once
    # block_user_web has severed the underlying Connection, but an
    # already-open thread from before the block still exists and would
    # otherwise let either side keep sending — check block here too so an
    # existing thread can't be used to route around it. Reading history and
    # delete-for-me stay unaffected; only new sends are cut off.
    other = conversation.other_participant(request.user)
    if other and UserRelationshipOverride.is_blocked(request.user, other):
        return JsonResponse({'error': 'You can’t message this user.'}, status=403)

    recent_count = ChatMessage.objects.filter(
        sender=request.user, sent_at__gte=timezone.now() - timezone.timedelta(minutes=1)
    ).count()
    if recent_count >= SEND_RATE_LIMIT:
        return JsonResponse({'error': "You're sending messages too fast — please wait a moment."}, status=429)

    body = request.POST.get('body', '').strip()
    media_id = request.POST.get('media_id', '').strip()

    media_asset = None
    if media_id:
        try:
            media_asset = MediaAsset.objects.get(id=media_id)
        except (MediaAsset.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Media not found'}, status=404)
        # Fail-closed: only the sender's own, fully-processed, non-held
        # asset may be attached — never trust the client on ownership or
        # status (same rule posts.views.create_post applies).
        if media_asset.owner_id != request.user.id:
            return JsonResponse({'error': 'Media not found'}, status=404)
        if not media_asset.is_downloadable:
            return JsonResponse({'error': 'Media is not ready yet'}, status=400)

    if not body and not media_asset:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)

    reply_to = None
    reply_to_id = request.POST.get('reply_to', '').strip()
    if reply_to_id:
        try:
            # Must belong to this same conversation — a reply can't quote
            # a message from somewhere else, even one this user can see.
            reply_to = ChatMessage.objects.get(id=reply_to_id, conversation=conversation)
        except (ChatMessage.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Original message not found'}, status=404)

    message = ChatMessage.objects.create(
        conversation=conversation, sender=request.user, body=body[:4000], reply_to=reply_to
    )
    image_url = None
    if media_asset is not None:
        MessageAttachment.objects.create(message=message, media_asset=media_asset)
        media_asset.mark_attached()
        image_url = reverse('message_attachment_image', kwargs={'message_id': message.id})

    return JsonResponse({
        'id': str(message.id),
        'body': message.body,
        'is_me': True,
        'sent_at': message.sent_at.strftime('%H:%M'),
        'image_url': image_url,
        'reply_to': _message_reply_preview(message),
        'is_forwarded': False,
    })


def messages_delete_for_me(request, message_id):
    """POST /messages/<id>/hide/ — per-user 'delete for me' (MessageHiddenFor),
    not the global moderation is_deleted flag. Idempotent: hiding an
    already-hidden message just succeeds again."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    message = get_object_or_404(
        ChatMessage.objects.select_related('conversation'), pk=message_id
    )
    if not message.conversation.participants.filter(user=request.user).exists():
        raise Http404('message not found')

    MessageHiddenFor.objects.get_or_create(message=message, user=request.user)
    return JsonResponse({'ok': True})


def messages_forward(request, message_id):
    """POST /messages/<id>/forward/ — body: target_conversation_id.
    Deliberately narrower-but-different authorization from messages_send's
    attach check: the requester must be a participant of the *source*
    message's conversation (proof they were allowed to see it) and of the
    *target* conversation, but does NOT need to own the attached
    MediaAsset — it's already legitimately visible to them via the
    message they're forwarding, so re-attaching the same asset to a new
    MessageAttachment in the target conversation is the correct boundary,
    not a re-upload."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    original = get_object_or_404(
        ChatMessage.objects.select_related('conversation', 'attachment__media_asset', 'sender'), pk=message_id
    )
    if not original.conversation.participants.filter(user=request.user).exists():
        raise Http404('message not found')

    target_id = request.POST.get('target_conversation_id', '').strip()
    try:
        target = Conversation.objects.get(id=target_id, participants__user=request.user)
    except (Conversation.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Conversation not found'}, status=404)

    forwarded = ChatMessage.objects.create(
        conversation=target, sender=request.user, body=original.body, forwarded_from=original
    )
    image_url = None
    original_attachment = getattr(original, 'attachment', None)
    if original_attachment is not None and original_attachment.media_asset is not None:
        # Re-check is_downloadable at forward time, not just at the
        # original send — a moderator could have placed the asset under
        # moderation_hold since then. get_preview_url/get_download_url
        # already fail closed on this (so nothing was ever actually
        # exposed), but there's no reason to create a MessageAttachment
        # pointing at content that's now unviewable — fail closed here too.
        if original_attachment.media_asset.is_downloadable:
            MessageAttachment.objects.create(message=forwarded, media_asset=original_attachment.media_asset)
            original_attachment.media_asset.mark_attached()
            image_url = reverse('message_attachment_image', kwargs={'message_id': forwarded.id})

    return JsonResponse({
        'id': str(forwarded.id),
        'conversation_id': str(target.id),
        'body': forwarded.body,
        'image_url': image_url,
    })


def _get_authorized_attachment(request, message_id):
    """Shared lookup + "conversation participant" authorization for both
    message_attachment_image and message_attachment_download — keeps the
    two endpoints' access rules from being able to drift apart. Raises
    Http404 (fail-closed, rule 13) on anything not authorized; returns the
    MediaAsset otherwise."""
    message = get_object_or_404(
        ChatMessage.objects.select_related('attachment__media_asset'), pk=message_id
    )
    if not message.conversation.participants.filter(user=request.user).exists():
        raise Http404('message not found')

    attachment = getattr(message, 'attachment', None)
    if attachment is None or attachment.media_asset is None:
        raise Http404('message has no attachment')
    return attachment.media_asset


def message_attachment_image(request, message_id):
    """GET /messages/attachment/<id>/ — a chat bubble's <img src>. Same
    "layer authorization on top of MediaAsset's owner-only floor" pattern
    as posts.views.post_image, except the authorization here is
    "conversation participant" (the same check messages_thread/poll/earlier
    already use) rather than "can see this post". Redirects to a signed
    preview URL — no Content-Disposition, meant for inline rendering.
    `?full=1` serves the actual processed image instead of the 320x320
    thumbnail, for the lightbox/full-screen viewer."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    asset = _get_authorized_attachment(request, message_id)
    url = media_services.get_preview_url(asset, full=request.GET.get('full') == '1')
    if not url:
        raise Http404('media is not currently available')
    return HttpResponseRedirect(url)


def message_attachment_download(request, message_id):
    """GET /messages/attachment/<id>/download/ — same authorization as
    message_attachment_image, but redirects to a signed URL carrying
    Content-Disposition: attachment (media_services.get_download_url),
    so a real top-level navigation to it (the chat lightbox's plain <a
    href>, not fetch/XHR) triggers an actual save/download — both in a
    normal browser and, via the Android app's WebView DownloadListener,
    on-device."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    asset = _get_authorized_attachment(request, message_id)
    url = media_services.get_download_url(asset)
    if not url:
        raise Http404('media is not currently available')
    return HttpResponseRedirect(url)