"""What the name filter refuses, what it lets through, and what it marks.

The filter used to have one list and one answer, and the answer for every
match was no. That is the wrong answer often enough to matter: three of the
names below belong to real places and a real charity, and every one of them
was refused at signup with a message that named no reason and offered no way
forward. The split these tests pin is between a term with no innocent reading
and a term with one -- and the rule that the second kind is *allowed*, and
merely recorded.
"""

import pytest

from moderation import name_problem, screen_name


# --- Refused ---------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Nigger Falls Trust",
    "The Kike Foundation",
    "Faggot Society",
    "Chink Community Fund",
    "Retard Support Network",
])
def test_a_term_with_no_innocent_reading_is_refused(name):
    problem, flagged = screen_name(name)
    assert problem is not None
    # Refused rather than flagged: there is nothing for a reviewer to weigh.
    assert flagged is False


@pytest.mark.parametrize("name", [
    "N1gg3r Falls Trust",        # leetspeak
    "ＦＡＧＧＯＴ Society",         # fullwidth
    "Ｎ1ＧＧＥＲ Trust",            # both at once
])
def test_obfuscation_does_not_get_past_the_hard_list(name):
    assert screen_name(name)[0] is not None


# --- Allowed, and marked ---------------------------------------------------

@pytest.mark.parametrize("name", [
    # A registered charity. A directory that refuses this is wrong about its
    # own sector, which is the whole reason vulgarity is not a hard block.
    "Fuck Cancer",
    "Shit Happens Collective",
    "The Bitch Fund",
])
def test_deliberate_vulgarity_is_allowed_and_marked(name):
    problem, flagged = screen_name(name)
    assert problem is None
    assert flagged is True


@pytest.mark.parametrize("name", [
    "Dick Smith Memorial Trust",     # a given name
    "Gypsy Arts Collective",         # a term its own community uses
    "Dyke Housing Association",      # also an embankment
])
def test_an_ambiguous_term_is_allowed_and_marked(name):
    problem, flagged = screen_name(name)
    assert problem is None
    assert flagged is True


# --- Allowed, and not even marked ------------------------------------------

@pytest.mark.parametrize("name", [
    "Coon Rapids Food Shelf",        # Minnesota
    "Cripple Creek Community Fund",  # Colorado
    "Gypsy Moth Research Group",
    "Coon Valley Historical Society",
])
def test_a_known_innocent_phrase_is_not_even_flagged(name):
    """These are the names that made this worth changing.

    Allowed is the minimum; unflagged is the point. A review queue that fills
    up with Minnesota townships is one nobody reads.
    """
    problem, flagged = screen_name(name)
    assert problem is None
    assert flagged is False


def test_an_allowed_phrase_does_not_cover_the_whole_name():
    """The phrase is removed, not used to wave the rest of the name through."""
    problem, flagged = screen_name("Coon Rapids Bitch Fund")
    assert problem is None
    assert flagged is True


def test_matching_is_on_whole_words_and_does_not_stem():
    """"Fuckery" is not "fuck", and this filter does not pretend otherwise.

    Documented rather than incidental: matching on stems is what starts
    catching Scunthorpe. The cost is that an inflection nobody listed goes
    unflagged, which is the direction this filter is meant to err in.
    """
    assert screen_name("The Fuckery Collective") == (None, False)


@pytest.mark.parametrize("name", [
    "Scunthorpe Community Trust",
    "Assistant Dogs of America",
    "Classical Music Outreach",
    "Riverside Tech",
    "Bridgewater Community Arts",
])
def test_an_ordinary_name_is_untouched(name):
    assert screen_name(name) == (None, False)


# --- The wrapper -----------------------------------------------------------

def test_name_problem_reports_only_the_refusal():
    assert name_problem("Riverside Tech") is None
    assert name_problem("Fuck Cancer") is None          # flagged, not refused
    assert name_problem("The Kike Foundation") is not None


def test_the_refusal_says_what_happened_and_where_to_go():
    """A dead end is what made the old message a bug in its own right."""
    problem = name_problem("The Kike Foundation")
    assert "blocked" in problem.lower()
    assert "get in touch" in problem.lower()


# --- Through the routes ----------------------------------------------------

def test_registering_a_refused_name_says_which_field(client):
    response = client.post("/register", json={
        "name": "Nigger Falls Trust",
        "email": "pytest-blocked@example.com",
        "password": "Test1234!verify",
    })
    assert response.status_code == 400
    assert response.get_json()["field"] == "name"


def test_registering_a_flagged_name_succeeds_and_marks_the_row(client, session):
    from models import Organization

    response = client.post("/register", json={
        "name": "Fuck Cancer",
        "email": "pytest-flagged@example.com",
        "password": "Test1234!verify",
    })
    assert response.status_code == 201, response.get_data(as_text=True)

    org = session.query(Organization).filter(
        Organization.email == "pytest-flagged@example.com").one()
    assert org.name_flagged is True


def test_an_ordinary_signup_is_not_marked(client, session):
    from models import Organization

    response = client.post("/register", json={
        "name": "Coon Rapids Food Shelf",
        "email": "pytest-innocent@example.com",
        "password": "Test1234!verify",
    })
    assert response.status_code == 201, response.get_data(as_text=True)

    org = session.query(Organization).filter(
        Organization.email == "pytest-innocent@example.com").one()
    assert org.name_flagged is False


def test_onboarding_points_at_the_name_field(client, login, make_org):
    """The refusal is answered on its own rather than folded into the
    'please provide a, b and c' list, which is for things that are missing."""
    login(make_org(onboarding_complete=False))
    response = client.post("/api/onboarding", json={
        "organization_name": "The Kike Foundation",
        "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["volunteers"],
        "offers": ["mentors"],
    })
    assert response.status_code == 400
    assert response.get_json()["field"] == "organization_name"


def test_onboarding_marks_a_flagged_name(client, login, make_org, session):
    org = make_org(onboarding_complete=False)
    login(org)
    response = client.post("/api/onboarding", json={
        "organization_name": "Fuck Cancer",
        "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["volunteers"],
        "offers": ["mentors"],
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    # The handler holds its own session on this connection, and this one was
    # built with expire_on_commit=False -- so without the refresh this reads
    # the value the row had before the request.
    session.refresh(org)
    assert org.name_flagged is True


def test_inviting_under_a_refused_name_is_turned_away(client, login, make_org):
    login(make_org())
    response = client.post("/api/invites", json={"name": "Nigger Falls Trust"})
    assert response.status_code == 400
    assert response.get_json()["field"] == "name"


def test_a_refusal_carries_the_contact_address_when_one_is_set(
        client, monkeypatch):
    """The dead end is the half of this that word lists cannot fix.

    Pointed at the address rather than the contact form on purpose: the form
    is delivered by outbound mail, and outbound mail does not leave this app
    yet.
    """
    import app as app_module
    monkeypatch.setattr(app_module, "CONTACT_EMAIL", "help@example.org")

    response = client.post("/register", json={
        "name": "The Kike Foundation",
        "email": "pytest-contactable@example.com",
        "password": "Test1234!verify",
    })
    assert response.status_code == 400
    assert "help@example.org" in response.get_json()["error"]


def test_a_refusal_still_reads_as_a_sentence_without_one(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "CONTACT_EMAIL", "")

    response = client.post("/register", json={
        "name": "The Kike Foundation",
        "email": "pytest-uncontactable@example.com",
        "password": "Test1234!verify",
    })
    error = response.get_json()["error"]
    assert response.status_code == 400
    assert error.endswith(".")
    assert "@" not in error
