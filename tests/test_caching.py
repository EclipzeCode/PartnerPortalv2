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


def _bundle(html):
    """The stylesheet bundle a page links, or None.

    Stylesheets are no longer referenced individually: a run of them is
    collapsed into one `bundle-<digest>.css`, and the digest is taken over
    every member's name and content hash. So the thing these tests used to
    watch -- "does the URL the page asks for change when the file changes" --
    is now watched here instead of on nav.css itself. The property is the
    same one and it matters for the same reason; only the URL carrying it
    has moved.
    """
    found = re.findall(r'href="(bundle-[0-9a-f]+\.css)"', html)
    return found[0] if found else None


def test_html_is_always_revalidated(client):
    """The page carries the hashes, so a stale copy points at stale assets."""
    for path in ("/", "/index.html", "/pplogin.html", "/organization.html?id=1"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["Cache-Control"] == "no-cache", path


def test_local_asset_references_are_stamped(client):
    """Every local css/js in a served page names its version.

    Scripts still say so with a ?v=; stylesheets say it through the bundle
    digest, which is the same claim made once for all of them.
    """
    html = client.get("/ppdashboard.html").get_data(as_text=True)
    refs = _refs(html)
    # The dashboard is the heaviest page and pulls the most files.
    for expected in ("common.js", "ppdashboard.js", "proposals.js"):
        assert expected in refs, f"{expected} was not stamped"
        assert refs[expected] == app_module.asset_version(expected)

    # Nothing local is left unstamped. The bundle is excluded because its
    # filename *is* its version -- a ?v= on top would say the same thing
    # twice -- and it is the only reference allowed to look bare.
    unstamped = [
        name for name in
        re.findall(r'(?:href|src)="([A-Za-z0-9._-]+\.(?:css|js))"', html)
        if not name.startswith(app_module.BUNDLE_PREFIX)
    ]
    assert unstamped == [], unstamped


def test_stylesheets_are_bundled_into_one_request(client):
    """The dashboard's stylesheets arrive as one file, in order.

    Order is the part worth pinning. These sheets override each other by
    document order -- shared.css is written expecting to come after ink.css
    -- so a bundle that concatenated them in any other order would restyle
    the site while every individual file stayed correct.
    """
    html = client.get("/ppdashboard.html").get_data(as_text=True)
    name = _bundle(html)
    assert name, "the dashboard's stylesheets were not bundled"

    response = client.get("/" + name)
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    members = re.findall(r'/\* --- (\S+) --- \*/', body)
    for expected in ("tokens.css", "ppdashboard.css", "shared.css",
                     "forms.css", "proposals.css", "nav.css"):
        assert expected in members, f"{expected} missing from the bundle"
    assert members.index("ink.css") < members.index("shared.css")

    # Named by its contents, so it can be kept for a year.
    assert "immutable" in response.headers["Cache-Control"]


def test_a_bundle_keeps_font_urls_resolvable(client):
    """Why the bundle is served from the root and not from a /bundle/ path.

    boxicons.css and fonts.css both carry `url(fonts/...woff2)`, which a
    browser resolves against the stylesheet's own URL. Served from a
    subdirectory those become /bundle/fonts/... and every glyph on the site
    silently disappears.
    """
    name = _bundle(client.get("/index.html").get_data(as_text=True))
    assert name and "/" not in name, name
    body = client.get("/" + name).get_data(as_text=True)
    assert "url(fonts/" in body


def test_a_bundle_nobody_asks_for_is_not_served(client):
    """A digest from a stale page names a combination that no longer exists."""
    assert client.get("/bundle-000000000000dead.css").status_code == 404


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
    # nav.css is inside index.html's bundle, so the URL that has to move is
    # the bundle's. The digest covers every member's content hash precisely
    # so that editing any one of them is a different URL for all of them.
    before = _bundle(client.get("/index.html").get_data(as_text=True))
    assert before
    try:
        open(path, "ab").write(b"\n/* pytest cache probe */\n")
        after = _bundle(client.get("/index.html").get_data(as_text=True))
        assert after != before
    finally:
        open(path, "wb").write(original)

    # Content-addressed, not mtime-addressed: putting the bytes back gives
    # the original stamp, so a revert does not strand anyone on a third URL.
    restored = _bundle(client.get("/index.html").get_data(as_text=True))
    assert restored == before


def test_a_changed_stylesheet_reaches_someone_who_already_has_the_page(client):
    """The bug the first version of this shipped with.

    Serving the page with send_from_directory and rewriting it afterward
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

    before = _bundle(first.get_data(as_text=True))
    try:
        open(path, "ab").write(b"\n/* pytest: a real change */\n")
        again = client.get("/index.html", headers={"If-None-Match": etag})
        assert again.status_code == 200, "returning visitor was fobbed off with a 304"
        # ...and the page they now hold points at the new stylesheet. The
        # bundled sheets are deliberately part of the page's cache key even
        # though the served markup no longer names them -- without that, this
        # is exactly the bug above with one more layer of indirection on top.
        after = _bundle(again.get_data(as_text=True))
        assert after and after != before
        assert client.get("/" + after).status_code == 200
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

    # *args, because the rewriter now takes the pattern to apply as well --
    # HTML references its stylesheets, and a stylesheet references its fonts.
    def counted(html, *args, **kwargs):
        calls.append(html)
        return real(html, *args, **kwargs)

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
    html = response.get_data(as_text=True)
    # Its stylesheets go through the same bundling as any other page, and its
    # scripts through the same stamping.
    assert _bundle(html), "the 404 page's stylesheets were not bundled"
    assert "common.js?v=" in html


def test_a_missing_asset_reference_is_left_as_written(client):
    """A typo'd filename should not become a 500 in the rewriter."""
    assert app_module.asset_version("no-such-file.css") is None
    body, assets = app_module._stamp_asset_refs('<link href="no-such-file.css">')
    assert body == '<link href="no-such-file.css">'
    # Recorded with a None version, so the page cache invalidates the day the
    # file appears rather than serving an unstamped reference to it forever.
    assert assets == (("no-such-file.css", None),)


# --- Fonts -----------------------------------------------------------------
# The stamps chain one level further than they used to: a page names a
# stylesheet, and a stylesheet names a font. Without that second hop the
# woff2 files were the only thing here served unversioned, which meant the
# only thing that could not be kept for a year -- on files that never change.

def _font_stamp(client, sheet="/boxicons.css"):
    import re
    body = client.get(sheet).get_data(as_text=True)
    found = re.search(r"url\(fonts/[A-Za-z0-9._-]+\?v=([0-9a-f]+)\)", body)
    return found.group(1) if found else None


def test_a_stylesheet_stamps_the_fonts_it_names(client):
    assert _font_stamp(client) is not None


def test_a_stamped_font_is_kept_for_a_year(client):
    import app as app_module
    version = app_module.asset_version("fonts/boxicons.woff2")
    response = client.get(f"/fonts/boxicons.woff2?v={version}")
    assert response.status_code == 200
    assert "max-age=31536000" in response.headers["Cache-Control"]
    assert "immutable" in response.headers["Cache-Control"]


def test_replacing_a_font_moves_the_stylesheet_its_own_version(client, tmp_path):
    """The reason a stylesheet's hash covers its fonts.

    Re-running the subset script can leave boxicons.css byte-identical while
    the font behind it differs. If the sheet's own version did not move, every
    returning visitor would keep a cached copy naming a font that is no longer
    there -- pinned for a year by the header the stamp exists to make safe.
    """
    import os
    import shutil
    import app as app_module

    path = os.path.join(app_module.STATIC_DIR, "fonts/boxicons.woff2")
    backup = tmp_path / "boxicons.woff2"
    shutil.copy(path, backup)

    before_sheet = app_module.asset_version("boxicons.css")
    before_font = _font_stamp(client)
    try:
        with open(path, "ab") as f:
            f.write(b"\x00")
        assert _font_stamp(client) != before_font
        assert app_module.asset_version("boxicons.css") != before_sheet
    finally:
        shutil.copy(backup, path)


def test_a_timestamp_alone_does_not_move_a_stamp(client, tmp_path):
    """A checkout writes every file fresh.

    Hashing mtimes would hand every stylesheet a new version on every deploy,
    which is the caching scheme undone by the thing meant to protect it.
    """
    import os
    import app as app_module

    path = os.path.join(app_module.STATIC_DIR, "fonts/boxicons.woff2")
    before = (app_module.asset_version("boxicons.css"), _font_stamp(client))
    os.utime(path, None)
    assert (app_module.asset_version("boxicons.css"), _font_stamp(client)) == before


def test_an_unknown_stylesheet_is_a_404(client):
    """The route interpolates into a path, so it is held to the same frozen
    allowlist the pages are."""
    assert client.get("/nope.css").status_code == 404
