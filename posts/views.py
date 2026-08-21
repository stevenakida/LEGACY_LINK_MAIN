from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from connections.models import Connection, UserRelationshipOverride
from media_assets import services as media_services
from media_assets.models import MediaAsset
from moderation.models import ModerationHold

from .models import Post, PostHiddenFor

FEED_PAGE_SIZE = 20


def _accepted_connection_ids(user):
    """IDs of users `user` has an accepted connection with, via the
    centralized Connection.accepted_between() (Phase 0's prerequisite
    refactor for anything that needs to reason about "who is user
    connected to")."""
    ids = set()
    for c in Connection.accepted_between(user):
        ids.add(c.receiver_id if c.requester_id == user.id else c.requester_id)
    return ids


def _cohort_author_ids(user):
    """IDs of users who share a cohort (same school + completion year at
    any of the four levels) with `user` — symmetric, so this doubles as
    "whose cohort-audience posts should `user` see" and "who shares a
    cohort with `user`"."""
    return set(user.cohort_queryset().values_list('id', flat=True))


def _visible_posts_queryset(viewer):
    """Single source of truth for "which posts can `viewer` see" — both
    the feed listing and post_image's authorization check go through this,
    so they can never drift apart (a post visible in the feed always has a
    viewable image, and vice versa).

    Rules: always your own posts (any audience/status, so you can see your
    own pending/rejected Public posts); connections-audience posts from an
    accepted connection; cohort-audience posts from anyone who shares your
    cohort; Public posts from anyone, but only once approval_status is
    APPROVED — pending/rejected Public posts are invisible to everyone but
    their author until a moderator acts on them.

    Deliberately does NOT factor in PostHiddenFor — "hidden" is a feed
    display preference, not an access grant, so a hidden post must stay
    just as viewable/authorizable as before it was hidden (post_image
    keeps working, and re-hiding an already-hidden post via hide_post
    below stays idempotent instead of 404ing the second time). Only
    get_feed_for_user applies the hidden-post exclusion.

    DOES factor in a Block (UserRelationshipOverride) — unlike hide/mute,
    block is authorization, not just a feed preference, so it belongs here
    rather than only in get_feed_for_user: a blocked pair must not be able
    to reach each other's posts via post_image either, not just have them
    absent from the feed listing."""
    connection_ids = _accepted_connection_ids(viewer)
    cohort_ids = _cohort_author_ids(viewer)
    blocked_ids = UserRelationshipOverride.blocked_partner_ids(viewer)
    return Post.objects.filter(
        Q(author=viewer)
        | Q(audience=Post.Audience.CONNECTIONS, author_id__in=connection_ids)
        | Q(audience=Post.Audience.COHORT, author_id__in=cohort_ids)
        | Q(audience=Post.Audience.PUBLIC, approval_status=Post.ApprovalStatus.APPROVED)
    ).exclude(author_id__in=blocked_ids).select_related('author', 'media_asset')


def get_feed_for_user(user, limit=FEED_PAGE_SIZE):
    """Newest-first slice of everything `user` is allowed to see, minus
    anything they've hidden or muted. Mute (unlike block) only ever applies
    here — it's a feed display preference, not an access grant, so a muted
    author's posts stay reachable via a direct link/post_image the same way
    a hidden post does. A plain slice rather than a real paginator —
    matches the rest of Home (cohort_users[:4], upcoming_events[:3]); no
    infinite scroll this pass."""
    muted_ids = UserRelationshipOverride.muted_author_ids(user)
    return list(
        _visible_posts_queryset(user)
        .exclude(hidden_for__user=user)
        .exclude(author_id__in=muted_ids)[:limit]
    )


def can_view_post(viewer, post):
    return _visible_posts_queryset(viewer).filter(pk=post.pk).exists()


def create_post(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    body = request.POST.get('body', '').strip()[:2000]
    media_id = request.POST.get('media_id', '').strip()

    media_asset = None
    if media_id:
        try:
            media_asset = MediaAsset.objects.get(id=media_id)
        except (MediaAsset.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Media not found'}, status=404)
        # Fail-closed: only the owner's own, fully-processed, non-held asset
        # may be attached — never trust the client on ownership or status.
        if media_asset.owner_id != request.user.id:
            return JsonResponse({'error': 'Media not found'}, status=404)
        if not media_asset.is_downloadable:
            return JsonResponse({'error': 'Media is not ready yet'}, status=400)

    if not body and not media_asset:
        return JsonResponse({'error': 'Add some text or a photo before posting.'}, status=400)

    audience = request.POST.get('audience', Post.Audience.CONNECTIONS)
    if audience not in Post.Audience.values:
        audience = Post.Audience.CONNECTIONS

    # Only Public needs a human review step before anyone but the author
    # can see it — Connections/Cohort are visible immediately.
    approval_status = (
        Post.ApprovalStatus.PENDING if audience == Post.Audience.PUBLIC
        else Post.ApprovalStatus.NOT_REQUIRED
    )

    post = Post.objects.create(
        author=request.user,
        body=body,
        media_asset=media_asset,
        audience=audience,
        approval_status=approval_status,
    )
    if media_asset is not None:
        media_asset.mark_attached()

    if approval_status == Post.ApprovalStatus.PENDING:
        # Phase 4 Step 3: back the Public-audience review gate with the
        # generalized ModerationHold record (see moderation/models.py) —
        # Post.approval_status stays the fast-path field the feed queries
        # filter on; this is the parallel audit-trail row Step 4's report
        # flow will reuse instead of inventing its own status field.
        ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)

    return JsonResponse({
        'id': str(post.id),
        'body': post.body,
        'author_name': request.user.full_name,
        'image_url': reverse('post_image', kwargs={'post_id': post.id}) if post.media_asset_id else None,
        'created_at': post.created_at.isoformat(),
        'audience': post.audience,
        'approval_status': post.approval_status,
    })


def post_image(request, post_id):
    """GET /posts/<id>/image/ — the feed's <img src>. MediaAsset's own
    preview/download endpoints are owner-only by design (see that model's
    docstring); a post's image needs to be viewable by anyone who can see
    the post itself, so this is the "layer authorization on top" hand-off
    that model documents: post exists, requester can see the post per
    _visible_posts_queryset (same rules the feed itself uses), asset is
    actually attached to *this* post and still downloadable — only then
    redirect to a short-lived signed URL. Fails closed (404) on any of
    those, matching rule 13."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    post = get_object_or_404(Post.objects.select_related('author', 'media_asset'), pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    asset = post.media_asset
    if asset is None:
        raise Http404('post has no media')

    url = media_services.get_preview_url(asset)
    if not url:
        raise Http404('media is not currently available')
    return HttpResponseRedirect(url)


def edit_post(request, post_id):
    """POST /posts/<id>/edit/ — author-only, text only. Media/audience are
    not editable this pass (deliberately narrow, matches the pilot's
    text-or-photo composer rather than a full re-compose flow); a post can
    only go from having a body to having a different body. Setting
    edited_at is what drives the "Edited" label, so it's only touched here,
    never on create."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post, pk=post_id)
    if post.author_id != request.user.id:
        raise Http404('post not found')

    body = request.POST.get('body', '').strip()[:2000]
    if not body and not post.media_asset_id:
        return JsonResponse({'error': 'A post needs text or a photo.'}, status=400)

    post.body = body
    post.edited_at = timezone.now()
    post.save(update_fields=['body', 'edited_at'])

    return JsonResponse({
        'id': str(post.id),
        'body': post.body,
        'edited_at': post.edited_at.isoformat(),
    })


def delete_post(request, post_id):
    """POST /posts/<id>/delete/ — author-only hard delete. No comments/
    likes exist yet to cascade (Phase 4 build order builds post lifecycle
    before engagement features for exactly this reason), so a straight
    delete is safe today; revisit if/when child rows exist. The attached
    MediaAsset is left in place (on_delete=SET_NULL on Post.media_asset)
    rather than deleted, matching how MessageAttachment handles the same
    relationship — the asset just becomes unattached/orphaned rather than
    destroyed."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post, pk=post_id)
    if post.author_id != request.user.id:
        raise Http404('post not found')

    post.delete()
    return JsonResponse({'ok': True})


def hide_post(request, post_id):
    """POST /posts/<id>/hide/ — per-viewer 'hide from my feed'
    (PostHiddenFor), not a delete. Mirrors config.views.messages_delete_for_me.
    Idempotent: hiding an already-hidden post just succeeds again. Uses
    can_view_post rather than a plain get_object_or_404 so a post someone
    isn't allowed to see can't be probed for existence via this endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post, pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    PostHiddenFor.objects.get_or_create(post=post, user=request.user)
    return JsonResponse({'ok': True})
