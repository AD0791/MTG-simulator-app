"""The single Jinja2 environment, and the paths it resolves against.

Both directories are resolved from this module's location so they work the same
whether the app runs from a checkout or from the installed package in the image.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

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
