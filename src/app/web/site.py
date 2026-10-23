"""Site-wide routes that are not pages: the theme switch, robots.txt and the
sitemap. In the web router because they need the site URL and the cookies,
not because anything here renders a template.
"""

from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from . import form_state
from .templates import THEME_COOKIE, THEMES, absolute_url

router = APIRouter(include_in_schema=False)

# The pages worth indexing. Results and history are per-reader, ephemeral runs.
SITEMAP_PATHS = ("/", "/simulator", "/planner")


def local_path(next_path: str) -> str:
    """`next_path` when it is a path on this site, else `/` — the open-redirect guard.

    `//host` and `/\\host` are both read by browsers as another origin, and a
    browser strips tabs and newlines from a URL before reading it, so `/\\t/host`
    would become `//host`. Any control character or backslash is refused.
    """
    if (
        not next_path.startswith("/")
        or next_path.startswith("//")
        or "\\" in next_path
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in next_path)
    ):
        return "/"
    return next_path


@router.post("/theme", summary="Choose light, dark, or the system theme")
def choose_theme(
    request: Request,
    mode: Annotated[str, Form()] = "system",
    next: Annotated[str, Form()] = "/",
) -> Response:
    response = RedirectResponse(local_path(next), status_code=status.HTTP_303_SEE_OTHER)
    if mode in THEMES:
        form_state.remember(response, request, THEME_COOKIE, mode, form_state.THEME_MAX_AGE)
    else:
        form_state.forget(response, request, THEME_COOKIE)
    return response


@router.get("/robots.txt", summary="Crawler rules")
def robots(request: Request) -> Response:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /results/",
        "Disallow: /history",
        "Disallow: /theme",
        "Disallow: /api/",
        "",
        f"Sitemap: {absolute_url(request, '/sitemap.xml')}",
        "",
    ]
    return PlainTextResponse("\n".join(lines))


@router.get("/sitemap.xml", summary="The indexable pages")
def sitemap(request: Request) -> Response:
    urls = "".join(
        f"  <url><loc>{escape(absolute_url(request, path))}</loc></url>\n" for path in SITEMAP_PATHS
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )
    return Response(body, media_type="application/xml")
