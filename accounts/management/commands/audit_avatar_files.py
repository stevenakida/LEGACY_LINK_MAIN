from django.core.management.base import BaseCommand

from accounts.models import User

SAFE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


class Command(BaseCommand):
    """Read-only audit: lists any stored avatar whose filename extension
    isn't one of the image formats the upload path is supposed to allow.
    Run this once after deploying the avatar validation fix, since it only
    blocks *new* uploads — anything uploaded before the fix (e.g. an HTML
    file hosted under /media/avatars/ or the R2 equivalent) is still live
    in storage and needs to be removed by hand. Prints only; deletes nothing."""
    help = 'List avatars whose file extension is not a recognized image format.'

    def handle(self, *args, **options):
        suspects = []
        for user in User.objects.exclude(avatar='').exclude(avatar__isnull=True):
            name = user.avatar.name or ''
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext not in SAFE_EXTENSIONS:
                suspects.append((user, name, ext))

        if not suspects:
            self.stdout.write(self.style.SUCCESS('No suspicious avatar files found.'))
            return

        self.stdout.write(self.style.WARNING(f'{len(suspects)} suspicious avatar(s) found:'))
        for user, name, ext in suspects:
            try:
                url = user.avatar.url
            except Exception:
                url = '(could not resolve URL)'
            self.stdout.write(
                f'  user={user.id} phone_or_email={user.phone_or_email} '
                f'ext="{ext}" name={name} url={url}'
            )
