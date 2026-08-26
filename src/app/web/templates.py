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
