# Converts high_school from a free-typed CharField to a controlled
# ForeignKey against alumni.School (school_type='high_school'), matching
# the same pattern used in 0004_convert_schools_to_fk.py for
# primary_school/secondary_school.
#
# Uses RemoveField + AddField rather than AlterField: an in-place
# CharField -> ForeignKey AlterField makes Postgres rename the column and
# cast it with `high_school_id::bigint`, which fails for any existing
# non-numeric text (and even for cleared '' values — '' isn't castable to
# bigint either). Dropping and re-adding avoids the cast entirely; the new
# column simply starts NULL for every row.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_company_name_user_employment_status_and_more'),
        ('alumni', '0003_add_school_metadata'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='high_school',
        ),
        migrations.AddField(
            model_name='user',
            name='high_school',
            field=models.ForeignKey(blank=True, limit_choices_to={'school_type': 'high_school'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='high_school_alumni', to='alumni.school'),
        ),
    ]
