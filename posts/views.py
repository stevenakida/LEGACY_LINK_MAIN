from django.conf import settings
from django.db.models import Count, Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from connections.models import Connection, UserRelationshipOverride
from media_assets import services as media_services
from media_assets.models import MediaAsset
from moderation.models import ModerationHold
from moderation.services import InvalidReportCategory, file_report
from notifications.models import Notification
from notifications.services import notify
from ratelimiting.services import is_rate_limited

from .models import Post, PostComment, PostHiddenFor, PostLike

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
    cohort; Public posts from anyone, as long as approval_status is
    NOT_REQUIRED or APPROVED — pending/rejected Public posts are invisible
    to everyone but their author until a moderator acts on them. Public
    posts get NOT_REQUIRED instead of PENDING at creation time whenever
    settings.FEATURE_PUBLIC_POST_REVIEW_REQUIRED is off (see create_post) —
    this queryset doesn't care why a Public post is NOT_REQUIRED, only that
    it is, so it doesn't need its own flag check.

    All three audiences additionally require approval_status to be
    NOT_REQUIRED or APPROVED (i.e. exclude PENDING/REJECTED) — Connections/
    Cohort default to NOT_REQUIRED and normally never move on their own.
    As of 2026-09-11, report_post no longer sets PENDING itself (a single
    report is logged via ModerationHold/ContentReport for admin review but
    no longer auto-hides the post — see report_post's docstring); PENDING
    on a Connections/Cohort/Public post now only happens when an admin
    deliberately sets it (directly, or via FEATURE_PUBLIC_POST_REVIEW_REQUIRED
    at creation time for Public posts).

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
    not_held = [Post.ApprovalStatus.NOT_REQUIRED, Post.ApprovalStatus.APPROVED]
    return Post.objects.filter(
        Q(author=viewer)
        | Q(audience=Post.Audience.CONNECTIONS, author_id__in=connection_ids, approval_status__in=not_held)
        | Q(audience=Post.Audience.COHORT, author_id__in=cohort_ids, approval_status__in=not_held)
        | Q(audience=Post.Audience.PUBLIC, approval_status__in=not_held)
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
    posts = list(
        _visible_posts_queryset(user)
        .exclude(hidden_for__user=user)
        .exclude(author_id__in=muted_ids)
        .annotate(like_count=Count('likes', distinct=True), comment_count=Count('comments', distinct=True))
        [:limit]
    )
    liked_post_ids = set(
        PostLike.objects.filter(user=user, post_id__in=[p.id for p in posts]).values_list('post_id', flat=True)
    )
    for p in posts:
        p.is_liked_by_viewer = p.id in liked_post_ids
    return posts


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

    # Checked only once every other validation has passed, so a failed
    # attempt (empty body, bad media) never eats into the user's quota —
    # only actual post creations count toward the limit.
    if is_rate_limited(
        request.user, 'create_post',
        limit=settings.RATE_LIMIT_CREATE_POST_MAX,
        window_seconds=settings.RATE_LIMIT_CREATE_POST_WINDOW_SECONDS,
    ):
        return JsonResponse({'error': "You're posting too quickly — please wait a bit before posting again."}, status=429)

    audience = request.POST.get('audience', Post.Audience.CONNECTIONS)
    if audience not in Post.Audience.values:
        audience = Post.Audience.CONNECTIONS

    # Only Public ever needs a human review step before anyone but the
    # author can see it, and only while FEATURE_PUBLIC_POST_REVIEW_REQUIRED
    # is on — Connections/Cohort are always visible immediately.
    approval_status = (
        Post.ApprovalStatus.PENDING
        if audience == Post.Audience.PUBLIC and settings.FEATURE_PUBLIC_POST_REVIEW_REQUIRED
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
    those, matching rule 13.

    Serves the full-resolution processed image by default (the feed used to
    get the 320px thumbnail stretched to card width, which looked blurry).
    `?size=thumb` opts into the small thumbnail, for tiny tiles like the
    profile grid where downloading dozens of full photos would be wasteful."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    post = get_object_or_404(Post.objects.select_related('author', 'media_asset'), pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    asset = post.media_asset
    if asset is None:
        raise Http404('post has no media')

    url = media_services.get_preview_url(asset, full=request.GET.get('size') != 'thumb')
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
    """POST /posts/<id>/delete/ — author-only hard delete. PostLike and
    PostComment both CASCADE off Post, so this stays a straight delete even
    though likes/comments now exist. The attached MediaAsset is left in
    place (on_delete=SET_NULL on Post.media_asset)
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


def report_post(request, post_id):
    """POST /posts/<id>/report/ — file a report against the whole post.
    Records the report and (re)opens a ModerationHold for admin review (see
    moderation.services.file_report) — admins see it via ModerationHold/
    ContentReport in Django admin regardless. Does NOT touch the post's own
    approval_status/visibility: as of 2026-09-11, a single report no longer
    auto-hides the post (previously any one report — even one tap, even by
    mistake — immediately made the post invisible to everyone but its
    author). Matches the same "don't gate on unverified single-user signal,
    only on an admin's actual decision" policy already applied to new-post
    creation (see FEATURE_PUBLIC_POST_REVIEW_REQUIRED). An admin who
    decides a reported post genuinely warrants hiding can still do so
    directly (edit the post in Django admin and set approval_status to
    Pending or Rejected, or use the PostAdmin actions once it's Pending).
    Uses can_view_post (not get_object_or_404) so a post someone isn't
    allowed to see can't be probed for existence via this endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post, pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')
    if post.author_id == request.user.id:
        return JsonResponse({'error': "You can't report your own post."}, status=400)

    category = request.POST.get('category', '')
    description = request.POST.get('description', '')
    try:
        file_report(request.user, post, category, description)
    except InvalidReportCategory:
        return JsonResponse({'error': 'Choose a reason for the report.'}, status=400)

    return JsonResponse({'ok': True})


def report_post_media(request, post_id):
    """POST /posts/<id>/report-media/ — file a report against the post's
    photo specifically, not the whole post. Unlike report_post, this
    leaves the post itself (and its text) fully visible and only pulls the
    image: MediaAsset.moderation_hold=True makes is_downloadable False
    immediately, so post_image starts 404ing for everyone, same as any
    other held asset — no change needed to _visible_posts_queryset for
    this path."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post.objects.select_related('media_asset'), pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')
    if post.author_id == request.user.id:
        return JsonResponse({'error': "You can't report your own photo."}, status=400)
    asset = post.media_asset
    if asset is None:
        raise Http404('post has no media')

    category = request.POST.get('category', '')
    description = request.POST.get('description', '')
    try:
        file_report(request.user, asset, category, description)
    except InvalidReportCategory:
        return JsonResponse({'error': 'Choose a reason for the report.'}, status=400)

    asset.moderation_hold = True
    asset.save(update_fields=['moderation_hold'])
    return JsonResponse({'ok': True})


def toggle_like(request, post_id):
    """POST /posts/<id>/like/ — a single endpoint toggles the requester's
    like on/off (no separate like/unlike routes), matching Instagram's
    one-tap model. Uses can_view_post so a post someone can't see can't be
    probed or liked via this endpoint."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post.objects.select_related('author'), pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    like, created = PostLike.objects.get_or_create(post=post, user=request.user)
    if not created:
        like.delete()

    liked = created
    if liked and post.author_id != request.user.id:
        notify(
            post.author, Notification.Verb.POST_LIKED, actor=request.user, target=post,
            push_title=request.user.full_name, push_body='Liked your post',
        )

    count = post.likes.count()
    sample_names = list(
        post.likes.exclude(user=request.user).select_related('user')
        .order_by('-created_at').values_list('user__full_name', flat=True)[:2]
    )
    return JsonResponse({'liked': liked, 'count': count, 'sample_names': sample_names})


def _serialize_comment(comment, viewer):
    return {
        'id': str(comment.id),
        'author_id': str(comment.author_id),
        'author_name': comment.author.full_name,
        'body': comment.body,
        'created_at': comment.created_at.isoformat(),
        'can_delete': comment.author_id == viewer.id,
    }


def list_comments(request, post_id):
    """GET /posts/<id>/comments/ — comments load on demand rather than
    with the feed itself, so opening the feed never pays for N extra
    queries before anyone's actually asked to see a single comment."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    post = get_object_or_404(Post, pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    comments = post.comments.select_related('author').order_by('created_at')
    return JsonResponse({
        'comments': [_serialize_comment(c, request.user) for c in comments],
        'count': comments.count(),
    })


def add_comment(request, post_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    post = get_object_or_404(Post.objects.select_related('author'), pk=post_id)
    if not can_view_post(request.user, post):
        raise Http404('post not found')

    body = request.POST.get('body', '').strip()[:1000]
    if not body:
        return JsonResponse({'error': 'Write something before posting your comment.'}, status=400)

    if is_rate_limited(
        request.user, 'create_post_comment',
        limit=settings.RATE_LIMIT_CREATE_COMMENT_MAX,
        window_seconds=settings.RATE_LIMIT_CREATE_COMMENT_WINDOW_SECONDS,
    ):
        return JsonResponse({'error': "You're commenting too quickly — please wait a bit."}, status=429)

    comment = PostComment.objects.create(post=post, author=request.user, body=body)

    if post.author_id != request.user.id:
        notify(
            post.author, Notification.Verb.POST_COMMENTED, actor=request.user, target=post,
            push_title=request.user.full_name, push_body=comment.body[:120],
        )

    return JsonResponse({'comment': _serialize_comment(comment, request.user), 'count': post.comments.count()})


def delete_comment(request, comment_id):
    """POST /posts/comments/<id>/delete/ — either the comment's own author
    or the post's author may remove it, matching Instagram's "post owner
    can moderate their own comments" rule."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    comment = get_object_or_404(PostComment.objects.select_related('post'), pk=comment_id)
    if comment.author_id != request.user.id and comment.post.author_id != request.user.id:
        raise Http404('comment not found')

    post_id = comment.post_id
    comment.delete()
    return JsonResponse({'ok': True, 'count': PostComment.objects.filter(post_id=post_id).count()})
