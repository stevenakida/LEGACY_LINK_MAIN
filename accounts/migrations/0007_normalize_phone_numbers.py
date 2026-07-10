from django.db import migrations
from accounts.models import normalize_identifier


def normalize_existing(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.all():
        normalized = normalize_identifier(user.phone_or_email)
        if normalized != user.phone_or_email:
            # Guard against collapsing two differently-formatted rows into
            # the same value (would violate the unique constraint) — leave
            # the older row's value untouched if that ever happens; it needs
            # a human to pick which record to keep, same as the Lucy/Lusia
            # duplicate found on 2026-07-10.
            if User.objects.filter(phone_or_email=normalized).exclude(pk=user.pk).exists():
                continue
            user.phone_or_email = normalized
            user.save(update_fields=['phone_or_email'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_convert_high_school_to_fk'),
    ]

    operations = [
        migrations.RunPython(normalize_existing, migrations.RunPython.noop),
    ]
