from django.db import migrations

from alumni.alias_seed import seed


def seed_aliases(apps, schema_editor):
    seed(apps.get_model('alumni', 'School'), apps.get_model('alumni', 'SchoolAlias'))


class Migration(migrations.Migration):

    dependencies = [
        ('alumni', '0004_schoolalias_schoolrequest'),
    ]

    operations = [
        migrations.RunPython(seed_aliases, migrations.RunPython.noop),
    ]
