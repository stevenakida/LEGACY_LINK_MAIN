"""Phase 7 Network web views (Discover / Connected / Pending and their
actions). All rules live in connections.services; these views only parse the
request, call the service, and render a page, a redirect or -- for the
progressive-enhancement JS in static/js/network.js -- a small JSON reply.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from analytics.services import CLIENT_EVENTS, record_event
from connections import matching, services
from moderation.models import ContentReport
from moderation.services import InvalidReportCategory, file_report

User = get_user_model()

TABS = ('discover', 'connected', 'pending')

_ACTION_MESSAGES = {
    'sent': _lazy('Connection request sent to %(name)s.'),
    'not_found': _lazy('That user could not be found.'),
    'self': _lazy("You can't connect with yourself."),
    'blocked': _lazy('You can’t connect with this user.'),
    'already_connected': _lazy('You are already connected with %(name)s.'),
    'already_pending': _lazy('Your request to %(name)s is already pending.'),
    'incoming_pending': _lazy('%(name)s already sent you a request — check your Pending tab.'),
    'declined': _lazy('You can’t send a request to %(name)s.'),
    'rate_limited': _lazy("You're sending requests too quickly — please wait a few minutes."),
    'accepted': _lazy('You are now connected with %(name)s.'),
    'request_declined': _lazy('Declined the request from %(name)s.'),
    'already_resolved': _lazy('That request has already been answered.'),
    'invalid_action': _lazy('Invalid action.'),
    'removed': _lazy('Removed your connection with %(name)s.'),
    'dismissed': _lazy('%(name)s removed from Discover.'),
}


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _safe_next(request, default='connections'):
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    if candidate.startswith('/') and not candidate.startswith('//') and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()},
    ):
        return candidate
    return default


def _message_for(result):
    template = _ACTION_MESSAGES.get(result.code, '')
    name = result.other.full_name if result.other is not None else ''
    return template % {'name': name}


_STATUS_FOR_CODE = {'not_found': 404, 'rate_limited': 429}


def _respond(request, result, extra=None):
    """JSON for XHR callers, flash message + redirect for everyone else."""
    text = _message_for(result)
    if _is_ajax(request):
        payload = {'ok': result.ok, 'code': result.code, 'message': text}
        payload.update(services.network_state(request.user))
        if extra:
            payload.update(extra)
        return JsonResponse(payload, status=200 if result.ok else _STATUS_FOR_CODE.get(result.code, 400))
    if not result.ok:
        messages.error(request, text)
    elif result.code in ('sent', 'accepted'):
        messages.success(request, text)
    else:
        messages.info(request, text)
    return redirect(_safe_next(request))


def _pager_query(request):
    """Current query string minus `page`, for pager links that keep the
    active tab / search / filter."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _login_or_post_guard(request):
    if not request.user.is_authenticated:
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'code': 'auth', 'message': _('Please log in again.')}, status=401)
        return redirect('login')
    if request.method != 'POST':
        return redirect('connections')
    return None


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

def connections(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = services.with_education(request.user)

    tab = request.GET.get('tab')
    if tab not in TABS:
        tab = 'discover'
    level = services.normalize_level_filter(request.GET.get('level'))
    q = (request.GET.get('q') or '').strip()[:80]
    page = request.GET.get('page') or 1

    ctx = {
        'tab': tab,
        'active_tab': 'network',
        'level': level,
        'q': q,
        'pager_qs': _pager_query(request),
        'level_filters': [('all', _('All'))] + [
            (slug, matching.LEVEL_LABELS[lvl]) for slug, lvl in matching.LEVEL_SLUGS.items()
        ],
    }
    ctx.update(services.network_state(user))
    record_event('network_opened', actor=user, tab=tab)

    if tab == 'discover':
        result = services.discover(user, level, q)
        record_event('discover_opened', actor=user, has_results=bool(result.groups),
                     result_count_bucket=services.result_count_bucket(result.total_candidates))
        if q:
            record_event('discover_search', actor=user, has_results=bool(result.groups),
                         result_count_bucket=services.result_count_bucket(result.total_candidates))
        if level != 'all':
            record_event('education_filter_selected', actor=user, tab='discover', education_level=matching.LEVEL_SLUGS[level])
        anchor = result.groups[0] if result.groups else None
        ctx['result'] = result
        if anchor is not None:
            invite = services.whatsapp_invite_url(request, anchor.institution_name, anchor.cohort_year if anchor.mode == 'cohort' else None)
        elif result.empty_context is not None:
            invite = services.whatsapp_invite_url(request, result.empty_context.institution_name, result.empty_context.cohort_year)
        else:
            invite = services.whatsapp_invite_url(request)
        ctx['invite_url'] = invite
        ctx['empty_record'] = result.empty_context
    elif tab == 'connected':
        ctx['page_obj'] = services.connected_page(user, level, q, page)
        if level != 'all':
            record_event('education_filter_selected', actor=user, tab='connected', education_level=matching.LEVEL_SLUGS[level])
    else:
        record_event('pending_opened', actor=user)
        ctx['page_obj'] = services.pending_page(user, page)

    return render(request, 'connections.html', ctx)


def discover_group(request, level_slug, institution_id, mode):
    if not request.user.is_authenticated:
        return redirect('login')
    user = services.with_education(request.user)
    q = (request.GET.get('q') or '').strip()[:80]
    found = services.discover_group_page(user, level_slug, institution_id, mode, q, request.GET.get('page') or 1)
    if found is None:
        raise Http404('No such group')
    group, page_obj = found
    record_event('discover_group_view_all', actor=user, education_level=matching.LEVEL_SLUGS[level_slug])
    ctx = {
        'group': group,
        'page_obj': page_obj,
        'q': q,
        'pager_qs': _pager_query(request),
        'active_tab': 'network',
        'invite_url': services.whatsapp_invite_url(
            request, group.institution_name, group.cohort_year if group.mode == 'cohort' else None,
        ),
    }
    ctx.update(services.network_state(user))
    return render(request, 'network/discover_group.html', ctx)


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

def send_connection_web(request, user_id):
    guard = _login_or_post_guard(request)
    if guard is not None:
        return guard
    result = services.send_request(request.user, user_id, request.POST.get('message', ''))
    return _respond(request, result)


def respond_connection_web(request, connection_id):
    guard = _login_or_post_guard(request)
    if guard is not None:
        return guard
    return _respond(request, services.respond_to_request(request.user, connection_id, request.POST.get('action')))


def remove_connection_web(request, connection_id):
    guard = _login_or_post_guard(request)
    if guard is not None:
        return guard
    return _respond(request, services.remove_connection(request.user, connection_id))


def dismiss_discover_web(request, user_id):
    guard = _login_or_post_guard(request)
    if guard is not None:
        return guard
    return _respond(request, services.dismiss_suggestion(request.user, user_id))


# ---------------------------------------------------------------------------
# report a person (reuses the Phase 4 ContentReport / ModerationHold system)
# ---------------------------------------------------------------------------

def report_user_web(request, user_id):
    if not request.user.is_authenticated:
        return redirect('login')
    target = get_object_or_404(User, id=user_id, is_active=True)
    next_url = _safe_next(request)
    if target.id == request.user.id:
        messages.error(request, _("You can't report yourself."))
        return redirect(next_url)

    error = None
    if request.method == 'POST':
        try:
            file_report(
                request.user, target, request.POST.get('category', ''), request.POST.get('description', ''),
            )
        except InvalidReportCategory:
            error = _('Please choose a reason for your report.')
        else:
            messages.success(request, _('Thanks — your report was sent to our moderators.'))
            return redirect(next_url)

    return render(request, 'network/report_user.html', {
        'target': target,
        'categories': ContentReport.Category.choices,
        'next_url': next_url,
        'error': error,
        'active_tab': 'network',
    })


# ---------------------------------------------------------------------------
# client-side event beacon (allowlisted events only)
# ---------------------------------------------------------------------------

def track_event(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    if request.method != 'POST':
        return HttpResponse(status=405)
    name = request.POST.get('event', '')
    if name not in CLIENT_EVENTS:
        return HttpResponse(status=400)
    record_event(name, actor=request.user)
    return HttpResponse(status=204)
