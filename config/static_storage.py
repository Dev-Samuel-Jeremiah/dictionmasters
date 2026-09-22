"""
Static files in development, with an address that changes when they do.

In production every CSS and JS file is renamed with a fingerprint of its
contents (CompressedManifestStaticFilesStorage), so an updated stylesheet
has a new address and no browser can keep showing the old one.

In development the files are served under their plain names, and browsers
— an installed web-app window especially — happily keep an old copy. A
change to the header's styles then looks like it never happened. Here each
address carries the file's last-changed time (/static/css/ui.css?v=…), so
it changes the moment the file is saved and the browser fetches it again.
"""

import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class FreshStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        address = super().url(name)
        found = finders.find(name)
        if isinstance(found, (list, tuple)):
            found = found[0] if found else None
        if not found:
            return address
        try:
            stamp = int(os.path.getmtime(found))
        except OSError:
            return address
        return f"{address}{'&' if '?' in address else '?'}v={stamp}"
