"""The single Jinja2 environment, and the paths it resolves against.

Both directories are resolved from this module's location so they work the same
whether the app runs from a checkout or from the installed package in the image.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def asset_version(path: str) -> int:
    """Return a number that changes every time the file is saved.

    Browsers keep a copy of the stylesheet and may reuse it instead of asking
    the server again, so a CSS fix can be live on the server and still invisible
    in the browser. Adding this number to the file's URL (`app.css?v=...`) means
    a changed file gets a new URL, and a new URL is always downloaded fresh.

    We read it on every page render instead of once at startup, because the dev
    server only restarts when Python files change, not when CSS does.
    """
    return (STATIC_DIR / path).stat().st_mtime_ns


templates.env.globals["asset_version"] = asset_version


# Past a trillion a figure stops being money anyone holds and starts bursting
# its table cell -- doubling for 200 entries reaches 10^61.
_COMPACT_FROM = 1e12
_SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def money(value: float) -> Markup:
    """A dollar figure to two places, or 4.50 times 10 to the 15 written with
    the multiplication sign and a superscript once it is past a trillion --
    with a spoken reading beside it, since superscripts are not reliably
    announced."""
    if abs(value) < _COMPACT_FROM:
        return Markup("%.2f") % value
    mantissa, exponent = f"{value:.2e}".split("e")
    power = str(int(exponent))
    return Markup(
        '<span aria-hidden="true">{m} \N{MULTIPLICATION SIGN} 10{sup}</span>'
        '<span class="visually-hidden">{m} times 10 to the {p}</span>'
    ).format(m=mantissa, p=power, sup=power.translate(_SUPERSCRIPT))


templates.env.filters["money"] = money
