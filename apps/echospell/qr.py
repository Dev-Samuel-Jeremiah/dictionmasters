"""
A QR code for every EchoSpell card.

Each card — one category inside one group inside one level — has its own
address, so it has its own code. Printed beside that card in the book, it
takes a phone straight to the card on the site; anyone not signed in is
asked to sign in first and then lands on the same card.

The code is drawn as SVG on the page (crisp at any size, and it prints
properly) and offered as a PNG for dropping into a book layout. Nothing
is stored: a QR code is a few milliseconds of arithmetic, and the last
few are kept in memory.
"""

import io
import re
from functools import lru_cache

import qrcode
from qrcode.image.svg import SvgPathImage

# Room for a logo or a scuff on a printed page: "M" allows a quarter of
# the code to be damaged and still read.
ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_M
BORDER = 2          # quiet zone, in modules — the code needs clear space around it
BOX_SIZE = 10       # PNG pixels per module


def public_url(path):
    """`path` on the real site, whatever host this page is being viewed on,
    so a code made on a laptop still works from a printed book."""
    from django.conf import settings

    return f"{settings.SITE_URL}{path}"


def _code(text):
    maker = qrcode.QRCode(error_correction=ERROR_CORRECTION, border=BORDER, box_size=BOX_SIZE)
    maker.add_data(text)
    maker.make(fit=True)
    return maker


_SIZED = re.compile(r'^<svg width="[^"]*" height="[^"]*"')


@lru_cache(maxsize=256)
def svg(text, size=140):
    """The code as inline SVG markup, `size` pixels square."""
    image = _code(text).make_image(image_factory=SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    markup = buffer.getvalue().decode("utf-8")
    markup = markup[markup.index("<svg"):]
    # The library measures in millimetres; on screen it should simply fit
    # the space it is given, and be read aloud sensibly.
    return _SIZED.sub(f'<svg width="{size}" height="{size}" role="img"', markup, count=1)


@lru_cache(maxsize=256)
def png(text):
    """The code as PNG bytes, for putting in a printed book."""
    buffer = io.BytesIO()
    _code(text).make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()
