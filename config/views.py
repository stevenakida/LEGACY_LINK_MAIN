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
from opportunities.models import Opportunity, OpportunityInterest
from messaging.models import Conversation, ConversationMember, Message as ChatMessage

logger = logging.getLogger(__name__)


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

    cohort_full_qs = user.cohort_queryset()
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
        'active_tab': 'home',
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
    # accepted/declined with this user.
    discover_users = _annotate_connection_status(user, user.cohort_queryset())
    discover_users = [p for p in discover_users if p.connection_status == 'none']

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
        last_message = conv.messages.order_by('-sent_at').first()
        last_read_at = memberships_by_conv[conv.id].last_read_at if conv.id in memberships_by_conv else None
        unread_qs = conv.messages.exclude(sender=user)
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
    # Latest page only; older messages load via messages_earlier on scroll.
    latest_messages = list(conversation.messages.select_related('sender').order_by('-sent_at')[:MESSAGES_PAGE_SIZE])
    latest_messages.reverse()
    has_earlier = conversation.messages.count() > len(latest_messages)
    _mark_read(conversation, request.user)

    return render(request, 'chat.html', {
        'conversation': conversation,
        'other': other,
        'thread_messages': latest_messages,
        'has_earlier': has_earlier,
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

    older_messages = conversation.messages.select_related('sender').order_by('-sent_at')
    before = request.GET.get('before')
    if before:
        try:
            before_msg = ChatMessage.objects.get(id=before)
            older_messages = older_messages.filter(sent_at__lt=before_msg.sent_at)
        except (ChatMessage.DoesNotExist, ValueError):
            pass

    page = list(older_messages[:MESSAGES_PAGE_SIZE])
    page.reverse()
    has_earlier = conversation.messages.filter(sent_at__lt=page[0].sent_at).exists() if page else False

    return JsonResponse({
        'has_earlier': has_earlier,
        'messages': [
            {'id': str(m.id), 'body': m.body, 'is_me': m.sender_id == request.user.id, 'sent_at': m.sent_at.strftime('%H:%M')}
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

    new_messages = conversation.messages.select_related('sender').order_by('sent_at')
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
        {'id': str(m.id), 'body': m.body, 'is_me': m.sender_id == request.user.id, 'sent_at': m.sent_at.strftime('%H:%M')}
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

    recent_count = ChatMessage.objects.filter(
        sender=request.user, sent_at__gte=timezone.now() - timezone.timedelta(minutes=1)
    ).count()
    if recent_count >= SEND_RATE_LIMIT:
        return JsonResponse({'error': "You're sending messages too fast — please wait a moment."}, status=429)

    body = request.POST.get('body', '').strip()
    if not body:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)

    message = ChatMessage.objects.create(conversation=conversation, sender=request.user, body=body[:4000])
    return JsonResponse({
        'id': str(message.id),
        'body': message.body,
        'is_me': True,
        'sent_at': message.sent_at.strftime('%H:%M'),
    })