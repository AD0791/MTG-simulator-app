"""The single Jinja2 environment, and the paths it resolves against.

Both directories are resolved from this module's location so they work the same
whether the app runs from a checkout or from the installed package in the image.
"""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..config import get_settings

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"

THEME_COOKIE = "theme"
THEMES = ("light", "dark")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def theme_of(request: Request) -> str | None:
    """The theme the reader picked, or None to follow the system preference.

    An unknown cookie value is treated as no choice, so a hand-edited cookie can
    only ever fall back to the system theme.
    """
    theme = request.cookies.get(THEME_COOKIE)
    return theme if theme in THEMES else None


def absolute_url(request: Request, path: str) -> str:
    """`path` on the public site: `SITE_URL` when set, else the request's own
    base — which is only right when nothing rewrites the host on the way in."""
    base = get_settings().site_url or str(request.base_url)
    return base.rstrip("/") + path


def asset_version(path: str) -> int:
    """Return a number that changes every time the file is saved.

    Browsers keep a copy of the stylesheet and may reuse it instead of asking
    the server again, so a CSS fix can be live on the server and still invisible
    in the browser. Adding this number to the file's URL (`app.css?v=...`) means
    a changed file gets a new URL, and a new URL is always downloaded fresh.

    We read it on every page render instead of once at startup, because the dev
    server only restarts when Python files change, not when CSS does.
    """
    # A missing file gives 0 rather than an error: its link then 404s on its
    # own and the page still renders. Raising here turned one absent stylesheet
    # into a 500 on every page (found 2026-10-23 by renaming app.css).
    try:
        return (STATIC_DIR / path).stat().st_mtime_ns
    except FileNotFoundError:
        return 0


templates.env.globals["asset_version"] = asset_version
templates.env.globals["theme_of"] = theme_of
templates.env.globals["absolute_url"] = absolute_url
