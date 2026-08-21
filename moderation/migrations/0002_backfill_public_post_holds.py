from django.db import migrations


def backfill_holds(apps, schema_editor):
    """Phase 4 Step 3: any Public-audience Post created before this
    migration (approval flow shipped 2026-08-18, this migration lands
    2026-08-21 — a real production gap) never got a ModerationHold row,
    since posts.views.create_post only started opening one in this same
    change. Backfill so the new table reflects reality for existing posts,
    not just ones created from here on."""
    Post = apps.get_model('posts', 'Post')
    ModerationHold = apps.get_model('moderation', 'ModerationHold')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    # get_or_create rather than get_for_model()/get(): the contenttypes
    # framework normally populates this row via a post_migrate signal that
    # hasn't necessarily fired yet at this point in a migration run (e.g.
    # building a fresh test database), so it may not exist.
    content_type, _ = ContentType.objects.get_or_create(app_label='posts', model='post')
    for post in Post.objects.filter(audience='public'):
        resolved = post.approval_status != 'pending'
        ModerationHold.objects.update_or_create(
            content_type=content_type, object_id=post.pk,
            defaults={
                'reason': 'public_audience_review',
                'status': post.approval_status,
                'resolved_at': post.created_at if resolved else None,
            },
        )


def noop_reverse(apps, schema_editor):
    """Reversible per project convention (rule 7) — deliberately a no-op
    rather than deleting the backfilled rows: reversing this migration only
    means "stop requiring this data to exist," not "destroy the audit trail
    it created," and ModerationHold rows are harmless to leave in place
    even if 0001 were later unapplied for schema reasons."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('moderation', '0001_initial'),
        ('posts', '0003_post_edited_at_posthiddenfor'),
    ]

    operations = [
        migrations.RunPython(backfill_holds, noop_reverse),
    ]
