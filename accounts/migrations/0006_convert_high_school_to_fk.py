# Converts high_school from a free-typed CharField to a controlled
# ForeignKey against alumni.School (school_type='high_school'), matching
# the same pattern used in 0004_convert_schools_to_fk.py for
# primary_school/secondary_school.

import django.db.models.deletion
from django.db import migrations, models


def disable_fk_checks(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.execute("PRAGMA foreign_keys = OFF;")


def enable_fk_checks(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.execute("PRAGMA foreign_keys = ON;")


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_company_name_user_employment_status_and_more'),
        ('alumni', '0003_add_school_metadata'),
    ]

    operations = [
        migrations.RunPython(disable_fk_checks, enable_fk_checks),

        # Existing high_school values are free-typed text and cannot map to
        # a School row. The old column is NOT NULL, so clear it to '' first
        # (satisfies the pre-migration constraint) — the AlterField below
        # rebuilds the column as a nullable FK, and the final RunSQL clears
        # any leftover value once NULL is actually valid.
        migrations.RunSQL(
            "UPDATE accounts_user SET high_school = '';",
            migrations.RunSQL.noop
        ),

        migrations.AlterField(
            model_name='user',
            name='high_school',
            field=models.ForeignKey(blank=True, limit_choices_to={'school_type': 'high_school'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='high_school_alumni', to='alumni.school'),
        ),

        migrations.RunSQL(
            "UPDATE accounts_user SET high_school_id = NULL;",
            migrations.RunSQL.noop
        ),

        migrations.RunPython(enable_fk_checks, disable_fk_checks),
    ]
