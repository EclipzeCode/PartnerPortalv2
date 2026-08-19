# PartnerPortal

Most partnerships between small organizations fall apart because one side is
doing a favour. PartnerPortal matches organizations on **both** what they need
and what they can offer, so both sides walk in with something to gain — then
gives them a way to write the exchange down and agree to it.

Built for nonprofits, community organizations, and small businesses that want
to trade resources with each other.

## How it works

1. **Onboarding** — an organization says what it needs and what it can offer,
   choosing from a shared vocabulary of ~30 categories.
2. **Matching** — every other organization is ranked by how well the two
   profiles fit *in both directions*. An org that offers what you need **and**
   needs what you offer is a two-way match and ranks far above one that only
   satisfies one direction, because a one-sided match is just a request for a
   favour.
3. **Proposing** — open a match and propose a partnership. The terms start
   pre-filled from the overlap that produced the match, and each side can only
   commit to things it actually listed.
4. **Confirming** — the receiving organization accepts or declines. Acceptance
   generates a public summary page, shareable with a board or a funder without
   anyone needing an account.

## Stack

- **Backend** — Python / Flask, SQLAlchemy, Alembic migrations
- **Database** — PostgreSQL (Neon). Needs and offers are `text[]` columns with
  GIN indexes, so finding candidate matches is an indexed `&&` overlap query
  rather than a scan.
- **Frontend** — vanilla HTML/CSS/JS, no build step. Served by Flask itself, so
  the API is same-origin and there is no CORS layer.
- **Auth** — signed session cookies (HttpOnly, SameSite=Lax), bcrypt passwords.

## Running it locally

Requires Python 3.11+ and a Postgres database. No local Postgres install is
needed if you use a hosted one — `psycopg[binary]` bundles its own client
library.

```bash
python3 -m venv venv && source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` and `SECRET_KEY`.
The app refuses to start without a database URL.

Create the schema:

```bash
alembic upgrade head
```

Optionally load a dozen fictional organizations, built to demonstrate two-way
matches:

```bash
python seed.py
```

Then start the server and open <http://127.0.0.1:5001>:

```bash
python app.py
```

Flask serves the frontend as well as the API, so there is nothing else to run.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

They cover the rules that would otherwise break quietly: the matching
invariants (a two-way match outranks a one-sided one; shared causes rank but
never create a match), the proposal lifecycle (who may accept, decline or
withdraw, and what a settled proposal refuses), what one organization can and
cannot learn about another, which rows it may act on, how a profile view is
counted, and what the server does with input it does not recognise.

Outbound email is stubbed for the whole suite, so a test that creates a
proposal records what would have been sent instead of posting it to Resend.

The suite runs against the database in `DATABASE_URL` and leaves nothing
behind: each test runs inside a transaction that is rolled back when it
finishes, and everything it creates is named `pytest-*` so anything that did
escape is obvious. The models use Postgres `ARRAY` columns, so there is no
SQLite mode to fall back to.

## Project layout

| File | Purpose |
| --- | --- |
| `app.py` | Routes: auth, onboarding, matching, proposals, static frontend |
| `models.py` | `Organization` and `Partnership` |
| `matching.py` | Bidirectional scoring and the reasons shown to users |
| `categories.py` | The shared need/offer vocabulary and timeline options |
| `db.py` | Engine and session setup |
| `seed.py` | Demo organizations |
| `migrations/` | Alembic migrations — the schema's source of truth |
| `static/` | The entire frontend — HTML, CSS, JS |
| `tests/` | pytest suite — matching, privacy, ownership, validation |
| `render.yaml` | Deployment blueprint |

Pages, all under `static/`: `index.html` (landing), `onboarding.html`,
`ppsearch.html` (matches), `proposals.html` (partnerships),
`ppdashboard.html`, `partnership.html` (public agreement summary).

Flask serves `static/` at the site root, so `/ppsearch.html` maps to
`static/ppsearch.html`. The frontend lives in its own directory rather than at
the project root for a reason: Flask hands out **everything** under its
`static_folder` verbatim, so rooting it at the project would publish `.env`,
`app.py` and the rest of the source to anyone who asked for them.

## Data model note

`organizations` is a single table covering accounts, profiles, and the
searchable directory. An earlier version split these across `users`,
`onboarding_profiles`, and `partners`, which meant an organization that signed
up and completed onboarding was invisible to everyone else's search. An account
*is* an organization here.

Profiles can exist without a password (`password_hash` is nullable). Those are
unclaimed profiles — useful for pre-creating an entry for an organization you
are recruiting, which they can claim later.

## Status

Working: accounts and sessions, onboarding, bidirectional matching, partnership
proposals with mutual confirmation, and public agreement summaries.

Not built yet: in-app messaging, email notifications, and public organization
profile pages.

## License

[MIT](https://choosealicense.com/licenses/mit/)
