"""What a failure returns, which depends entirely on who is asking.

Every fetch on this site goes through common.js's api(), which calls
res.json() on the response. An HTML error document reaching that produces an
unreadable parse failure instead of a message, so /api/ paths get JSON and
everything else gets the real page.
"""


def test_an_unknown_page_gets_the_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "We couldn't find that page" in body


def test_an_unknown_api_path_gets_json(client):
    response = client.get("/api/no-such-endpoint")
    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["error"]


def test_a_server_error_serves_the_500_page_not_a_traceback(client, monkeypatch):
    import app as app_module

    def broken():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(app_module, "get_db", broken)
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)

    # A route that actually reaches for a session -- /api/categories serves
    # from constants and would never notice the database was gone.
    response = client.get("/organization.html?id=1")
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "Something went wrong on our end" in body
    assert "Traceback" not in body
    assert "simulated database failure" not in body


def test_a_server_error_on_an_api_path_stays_json(client, monkeypatch):
    import app as app_module

    def broken():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(app_module, "get_db", broken)
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)

    response = client.get("/api/organizations/1/public")
    assert response.status_code == 500
    assert response.is_json
    # The message is for a person, and gives nothing about the failure away.
    assert "simulated database failure" not in response.get_data(as_text=True)


def test_shareable_pages_carry_real_open_graph_tags(client, make_org):
    """A link pasted into a chat renders from these, and nothing else."""
    org = make_org(name="pytest OG org", needs=["web_development"],
                   offers=["grant_writing"],
                   description="A description that should reach the preview.")

    body = client.get(f"/organization.html?id={org.id}").get_data(as_text=True)
    assert 'property="og:title"' in body
    assert "pytest OG org" in body
    assert "A description that should reach the preview." in body

    # An unknown id still previews, rather than 404ing the page itself.
    fallback = client.get("/organization.html?id=999999999")
    assert fallback.status_code == 200
    assert 'property="og:title"' in fallback.get_data(as_text=True)
