"""Cookies that remember a reader's choices between visits.

Every cookie here is set the same way — Path=/, SameSite=Lax, HttpOnly, and
Secure when the request arrived over https — so the policy is written once.
Nothing here logs a cookie's contents: they are the reader's own figures.
"""

from fastapi import Request, Response

THEME_MAX_AGE = 365 * 24 * 60 * 60
FORM_MAX_AGE = 30 * 24 * 60 * 60

SIMULATOR_COOKIE = "simulator_form"
PLANNER_COOKIE = "planner_form"


def _is_https(request: Request) -> bool:
    # Behind a TLS-terminating proxy the app sees http; the forwarded header is
    # trusted only to make the cookie stricter, never looser.
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def remember(response: Response, request: Request, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        samesite="lax",
        httponly=True,
        secure=_is_https(request),
    )


def forget(response: Response, request: Request, name: str) -> None:
    response.delete_cookie(name, path="/", samesite="lax", httponly=True, secure=_is_https(request))
