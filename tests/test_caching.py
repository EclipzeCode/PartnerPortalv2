"""What may be cached, for how long, and how a change still gets through.

Nothing set a cache policy, so every asset was revalidated on every
navigation -- eight conditional requests on a dashboard load, each a round
trip. A long max-age was not available as a fix while the filenames never
changed: ship a year on pp.css and a fix to pp.css reaches nobody who has
already visited.

So the version travels in the URL. These tests pin the two halves that make
that safe: a served page always carries the current hash of every local
asset it references, and only a request that names a version is answered as
immutable. The third test is the one that matters most -- editing a file has
to change what the HTML asks for, or the year-long cache becomes a trap.
"""

import re

import app as app_module


def _refs(html):
    return dict(re.findall(r'(?:href|src)="([A-Za-z0-9._-]+\.(?:css|js))\?v=([a-f0-9]+)"',
                           html))


def test_html_is_always_revalidated(client):
    """The page carries the hashes, so a stale copy points at stale assets."""
    for path in ("/", "/index.html", "/pplogin.html", "/organization.html?id=1"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["Cache-Control"] == "no-cache", path


def test_local_asset_references_are_stamped(client):
    """Every local css/js in a served page names its version."""
    html = client.get("/ppdashboard.html").get_data(as_text=True)
    refs = _refs(html)
    # The dashboard is the heaviest page and pulls the most files.
    for expected in ("tokens.css", "ppdashboard.css", "shared.css",
                     "forms.css", "proposals.css", "nav.css",
                     "common.js", "ppdashboard.js", "proposals.js"):
        assert expected in refs, f"{expected} was not stamped"
        assert refs[expected] == app_module.asset_version(expected)

    # Nothing local is left unstamped.
    unstamped = re.findall(
        r'(?:href|src)="([A-Za-z0-9._-]+\.(?:css|js))"', html)
    assert unstamped == [], unstamped


def test_absolute_urls_are_left_alone(client):
    """Stamping a URL on someone else's host would simply break it."""
    html = client.get("/pplogin.html").get_data(as_text=True)
    for url in re.findall(r'https://[^"\']+', html):
        assert "?v=" not in url, url


def test_editing_a_file_changes_what_the_page_asks_for(client, tmp_path):
    """The whole basis of the year-long cache.

    If this ever stops holding, every returning visitor is pinned to the
    assets they first downloaded, and a CSS fix reaches nobody.
    """
    import os
    path = os.path.join(app_module.STATIC_DIR, "nav.css")
    original = open(path, "rb").read()
    before = _refs(client.get("/index.html").get_data(as_text=True))["nav.css"]
    try:
        open(path, "ab").write(b"\n/* pytest cache probe */\n")
        after = _refs(client.get("/index.html").get_data(as_text=True))["nav.css"]
        assert after != before
    finally:
        open(path, "wb").write(original)

    # Content-addressed, not mtime-addressed: putting the bytes back gives
    # the original stamp, so a revert does not strand anyone on a third URL.
    restored = _refs(client.get("/index.html").get_data(as_text=True))["nav.css"]
    assert restored == before


def test_a_changed_stylesheet_reaches_someone_who_already_has_the_page(client):
    """The bug the first version of this shipped with.

    Serving the page with send_from_directory and rewriting it afterwards
    looks equivalent and is not: Flask builds the ETag from the HTML file's
    own mtime and size, and answers the conditional request before any
    after_request hook runs. Editing nav.css therefore left index.html's
    ETag unchanged, a returning visitor was told 304, and they kept the copy
    carrying the old stamp -- so they held the old stylesheet for a year,
    pinned there by the cache header meant to make changes safe. A first-time
    visitor got the new one, which is what makes this the kind of bug nobody
    reproduces.
    """
    import os
    path = os.path.join(app_module.STATIC_DIR, "nav.css")
    original = open(path, "rb").read()

    first = client.get("/index.html")
    etag = first.headers["ETag"]

    # Nothing has changed: revalidating costs a 304 and no body.
    assert client.get("/index.html", headers={"If-None-Match": etag}).status_code == 304

    try:
        open(path, "ab").write(b"\n/* pytest: a real change */\n")
        again = client.get("/index.html", headers={"If-None-Match": etag})
        assert again.status_code == 200, "returning visitor was fobbed off with a 304"
        assert _refs(again.get_data(as_text=True))["nav.css"] == \
            app_module.asset_version("nav.css")
    finally:
        open(path, "wb").write(original)


def test_the_page_itself_is_not_re_stamped_on_every_request(client):
    """The point of the page cache: serving is a dict lookup, not a rebuild.

    The body and the ETag are both pure functions of the file plus the assets
    it references, and a page is read far more often than it is edited. If
    this stops holding, every request pays a file read, a regex rewrite over
    the whole page and a SHA-256 of the result -- which is what it did before.
    """
    calls = []
    real = app_module._stamp_asset_refs

    def counted(html):
        calls.append(html)
        return real(html)

    app_module._stamp_asset_refs = counted
    try:
        client.get("/index.html")
        after_first = len(calls)
        client.get("/index.html")
        client.get("/index.html")
        assert len(calls) == after_first, "the page was rebuilt on an unchanged file"
    finally:
        app_module._stamp_asset_refs = real


def test_editing_the_page_itself_is_noticed_too(client):
    """The other half of the cache key.

    The asset hashes are the subtle half and have their own tests above. This
    is the obvious half, and worth pinning precisely because it is obvious:
    keying only on the assets would serve the old HTML forever to anyone
    editing a page without touching a stylesheet -- which is most edits.
    """
    import os
    path = os.path.join(app_module.STATIC_DIR, "pphelp.html")
    original = open(path, "rb").read()

    first = client.get("/pphelp.html")
    etag = first.headers["ETag"]
    assert "pytest cache probe" not in first.get_data(as_text=True)

    try:
        open(path, "wb").write(
            original.replace(b"</body>", b"<!-- pytest cache probe --></body>")
        )
        again = client.get("/pphelp.html", headers={"If-None-Match": etag})
        assert again.status_code == 200, "returning visitor was fobbed off with a 304"
        assert "pytest cache probe" in again.get_data(as_text=True)
        assert again.headers["ETag"] != etag
    finally:
        open(path, "wb").write(original)

    assert client.get("/pphelp.html").headers["ETag"] == etag


def test_only_a_versioned_request_is_immutable(client):
    """A bare URL may be for a file that has since changed."""
    version = app_module.asset_version("nav.css")

    versioned = client.get(f"/nav.css?v={version}")
    assert versioned.status_code == 200
    assert "immutable" in versioned.headers["Cache-Control"]
    assert f"max-age={app_module.ASSET_CACHE_SECONDS}" in versioned.headers["Cache-Control"]

    bare = client.get("/nav.css")
    assert bare.status_code == 200
    assert "immutable" not in bare.headers["Cache-Control"]
    assert f"max-age={app_module.UNVERSIONED_CACHE_SECONDS}" in bare.headers["Cache-Control"]


def test_per_account_api_responses_are_never_stored(client, login, make_org):
    """A dashboard is per-account; a shared proxy must not hand it on."""
    assert client.get("/api/me").headers["Cache-Control"] == "no-store"

    login(make_org())
    for path in ("/api/dashboard", "/api/matches", "/api/saved", "/api/proposals"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["Cache-Control"] == "no-store", path


def test_the_category_vocabulary_is_cacheable(client):
    """The one /api/ response that is not about anybody.

    /api/categories is built from the constants in categories.py: no database,
    no session, and the same bytes for every caller. It used to be swept up by
    the blanket no-store for /api/, so every search and onboarding load spent a
    round trip re-reading a constant -- which on a remote database host is the
    part you feel.

    This is the carve-out, and the test is here to make sure the carve-out
    stays exactly that size. The one above is the other half: everything that
    is about somebody must still be no-store.
    """
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert "public" in response.headers["Cache-Control"]
    assert (f"max-age={app_module.UNVERSIONED_CACHE_SECONDS}"
            in response.headers["Cache-Control"])
    assert response.headers.get("ETag")

    # The ETag is what keeps the window cheap rather than absolute: once the
    # max-age lapses the browser revalidates and gets nothing back.
    again = client.get(
        "/api/categories",
        headers={"If-None-Match": response.headers["ETag"]},
    )
    assert again.status_code == 304
    assert not again.get_data()

    # And it is still the vocabulary the rest of the app is built on.
    payload = response.get_json()
    assert payload["groups"] and payload["organization_types"]
    assert payload["timelines"] and payload["focus_areas"]


def test_error_pages_are_served_and_stamped(client):
    """404 and 500 load the nav too, and were easy to leave out of the policy."""
    response = client.get("/definitely-not-a-page.html")
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-cache"
    assert "nav.css?v=" in response.get_data(as_text=True)


def test_a_missing_asset_reference_is_left_as_written(client):
    """A typo'd filename should not become a 500 in the rewriter."""
    assert app_module.asset_version("no-such-file.css") is None
    body, assets = app_module._stamp_asset_refs('<link href="no-such-file.css">')
    assert body == '<link href="no-such-file.css">'
    # Recorded with a None version, so the page cache invalidates the day the
    # file appears rather than serving an unstamped reference to it forever.
    assert assets == (("no-such-file.css", None),)
