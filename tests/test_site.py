"""The theme switch, crawler files, and the metadata every page carries."""

import json
import re

import pytest
from httpx import AsyncClient

from app.web.site import local_path
from tests.conftest import REFERENCE_FORM

pytestmark = pytest.mark.anyio


async def test_choosing_dark_sets_the_cookie_and_returns_to_the_page(client: AsyncClient) -> None:
    response = await client.post("/theme", data={"mode": "dark", "next": "/planner?capital=1600"})

    assert response.status_code == 303
    assert response.headers["location"] == "/planner?capital=1600"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("theme=dark")
    for attribute in ("HttpOnly", "Path=/", "SameSite=lax", "Max-Age=31536000"):
        assert attribute in cookie

    page = await client.get("/")
    assert '<html lang="en" data-theme="dark">' in page.text
    assert 'value="dark" aria-pressed="true"' in page.text


async def test_the_system_theme_deletes_the_cookie(client: AsyncClient) -> None:
    await client.post("/theme", data={"mode": "light", "next": "/"})
    response = await client.post("/theme", data={"mode": "system", "next": "/"})

    assert response.status_code == 303
    assert 'theme=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    page = await client.get("/")
    assert "data-theme" not in page.text.split("<head>")[0]


async def test_an_unknown_theme_cookie_follows_the_system(client: AsyncClient) -> None:
    client.cookies.set("theme", "neon")
    page = await client.get("/")

    assert '<html lang="en">' in page.text


async def test_the_cookie_is_secure_over_https(client: AsyncClient) -> None:
    response = await client.post(
        "/theme", data={"mode": "dark", "next": "/"}, headers={"x-forwarded-proto": "https"}
    )

    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "next_path",
    ["//evil.example", "https://evil.example", "/\\evil.example", "/\t/evil.example", "evil", ""],
)
async def test_next_must_be_a_local_path(client: AsyncClient, next_path: str) -> None:
    response = await client.post("/theme", data={"mode": "dark", "next": next_path})

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_a_local_path_keeps_its_query() -> None:
    assert local_path("/planner?capital=1600&weekdays=0") == "/planner?capital=1600&weekdays=0"


async def test_the_theme_control_keeps_the_query_string(client: AsyncClient) -> None:
    page = await client.get("/planner?capital=1600&target_capital=2000&risk_1=1")

    assert (
        'name="next" value="/planner?capital=1600&amp;target_capital=2000&amp;risk_1=1"'
        in page.text
    )


async def test_robots_txt(client: AsyncClient) -> None:
    response = await client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert "Allow: /" in lines
    for path in ("/results/", "/history", "/theme", "/api/"):
        assert f"Disallow: {path}" in lines
    assert "Sitemap: http://testserver/sitemap.xml" in lines


async def test_sitemap_lists_the_three_indexable_pages(client: AsyncClient) -> None:
    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert re.findall(r"<loc>(.*?)</loc>", response.text) == [
        "http://testserver/",
        "http://testserver/simulator",
        "http://testserver/planner",
    ]


async def test_per_user_pages_are_noindex_and_the_landing_page_is_not(
    client: AsyncClient,
) -> None:
    created = await client.post("/simulator", data=REFERENCE_FORM)
    result = await client.get(created.headers["location"])
    noindex = '<meta name="robots" content="noindex">'

    assert noindex in result.text
    assert noindex in (await client.get("/history")).text
    assert noindex in (await client.get("/no-such-page")).text
    for path in ("/", "/simulator", "/planner"):
        assert noindex not in (await client.get(path)).text


async def test_the_landing_page_has_one_json_ld_block(client: AsyncClient) -> None:
    page = (await client.get("/")).text
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)

    assert len(blocks) == 1
    data = json.loads(blocks[0])
    assert data["@type"] == "WebApplication"
    assert data["applicationCategory"] == "FinanceApplication"
    assert data["url"] == "http://testserver/"
    # The only script on the site.
    assert page.count("<script") == 1
    assert (await client.get("/simulator")).text.count("<script") == 0


@pytest.mark.parametrize("path", ["/", "/simulator", "/planner", "/history"])
async def test_every_page_carries_its_metadata(client: AsyncClient, path: str) -> None:
    page = (await client.get(path)).text
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    description = re.search(r'<meta name="description" content="(.*?)">', page, re.S)

    assert title and len(title.group(1)) <= 60
    assert description and len(description.group(1)) <= 155
    assert f'<link rel="canonical" href="http://testserver{path}">' in page
    assert 'property="og:image" content="http://testserver/static/img/og.png?v=' in page
    assert '<meta name="twitter:card" content="summary_large_image">' in page
    assert page.count("<h1") == 1
    for landmark in ("<header", "<nav", "<main", "<footer"):
        assert landmark in page


async def test_titles_are_unique(client: AsyncClient) -> None:
    titles = {
        re.search(r"<title>(.*?)</title>", (await client.get(path)).text, re.S).group(1)  # type: ignore[union-attr]
        for path in ("/", "/simulator", "/planner", "/history")
    }
    assert len(titles) == 4


async def test_the_canonical_drops_the_query(client: AsyncClient) -> None:
    page = (await client.get("/planner?capital=1600")).text

    assert '<link rel="canonical" href="http://testserver/planner">' in page


def test_a_missing_static_file_does_not_take_the_page_down() -> None:
    """Its link 404s on its own; the version helper must not raise."""
    from app.web.templates import asset_version

    assert asset_version("css/no-such-file.css") == 0
