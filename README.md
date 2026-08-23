# PartnerPortal

Most partnerships between small organizations fall apart because one side is
doing a favor. PartnerPortal matches organizations on **both** what they need
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
   favor.
3. **Proposing** — open a match and propose a partnership. The terms start
   pre-filled from the overlap that produced the match, and each side can only
   commit to things it actually listed. A term can carry a quantity — "30
   volunteers", "4,000 square feet" — so that what was agreed to is specific
   enough to judge at completion.
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
never create a match; two organizations with nothing to exchange score zero
however much else they have in common), the proposal lifecycle (who may
accept, decline, withdraw, complete or end one, and what a settled proposal
refuses), what one organization can and cannot learn about another, which
rows it may act on, how a profile view is counted, and what the server does
with input it does not recognize.

Several of them exist because the answer is a promise the product makes in
prose. That neither side can be committed to something it never listed. That
an accepted partnership outlives the other organization closing its account,
and that the survivor's own pages still load when it does. That a delivery
verdict and the reason a partnership ended stay between the two parties and
never reach the public summary. That a message thread closes when the
proposal does. That signup costs the same whether or not the address is
taken.

A few tests scope their assertions with a `pytest-` prefix rather than
assuming an empty database: the suite runs against whatever `DATABASE_URL`
names, and the directory endpoint deliberately returns everything.

Outbound email is stubbed for the whole suite, so a test that creates a
proposal records what would have been sent instead of posting it to Resend.

The suite runs against the database in `DATABASE_URL` and leaves nothing
behind: each test runs inside a transaction that is rolled back when it
finishes, and everything it creates is named `pytest-*` so anything that did
escape is obvious. The models use Postgres `ARRAY` columns, so there is no
SQLite mode to fall back to.

Locally that means it points at your own Neon database, and most of its
runtime is network round trips. CI does not: `.github/workflows/tests.yml`
runs Postgres in the runner, builds the schema from zero with
`alembic upgrade head`, and runs the same suite against that -- which also
means a migration that only applies to an already-migrated database fails
there rather than on someone's first deploy.

## Project layout

| File | Purpose |
| --- | --- |
| `app.py` | Routes: auth, onboarding, matching, directory, proposals, messages, static frontend |
| `models.py` | `Organization`, `Partnership`, `Message`, `Event`, `SavedLead`, `ProfileView` |
| `matching.py` | Bidirectional scoring and the reasons shown to users |
| `categories.py` | The shared need/offer vocabulary, focus areas and timelines |
| `units.py` | The units a partnership term may be quantified in, and what may be summed |
| `links.py` | Normalizing and validating the four profile links |
| `moderation.py` | Blocking inappropriate organization names |
| `notifications.py` | Transactional email, and the dry-run fallback without a key |
| `db.py` | Engine and session setup |
| `seed.py` | Demo organizations |
| `migrations/` | Alembic migrations — the schema's source of truth |
| `static/` | The entire frontend — HTML, CSS, JS, and the link-preview card |
| `tests/` | pytest suite — see below |
| `render.yaml` | Deployment blueprint |

Pages, all under `static/`: `index.html` (landing), `pplogin.html`,
`pphelp.html`, `onboarding.html`, `ppsearch.html` (matches, directory and
shortlist), `ppdashboard.html` (dashboard, partnerships and messages),
`analytics.html` (an organization's own numbers), `settings.html`,
`organization.html` (public profile), `partnership.html` (public agreement
summary), and the five token landing pages — `verify-email.html`,
`forgot-password.html`, `reset-password.html`, `confirm-email.html`,
`claim.html` — plus `404.html` and `500.html`.

There is no `proposals.html`: `proposals.js` renders the partnerships list
and the message threads inside `ppdashboard.html`.

The "Get in touch" form is `contact.js` plus a block of modal markup, and any
page can have it by including both — `index.html` and `pphelp.html` do. It
began as part of `pp.js` on the home page only, which left the help page's
Contact button pointing at `index.html#contact`: a fragment matching nothing,
because the form is a modal rather than a section. Sending someone to another
page for a form they asked for on this one is barely better than sending them
nowhere, so the form goes to them. Both copies post to the same `/api/contact`.

The main nav carries Home, Connect and Dashboard. Analytics and Help sit in
the account dropdown instead, below Edit profile and Settings; analytics is
also a button on the dashboard.

For analytics that placement follows the page: the numbers are one
organization's own, nobody signed out has anything to see there, and a link
in the bar would be noise on most of the site. Help is a public page, so the
same argument does not apply to it: the dropdown only renders when somebody
is signed in, and no footer links to `pphelp.html`, so a signed-out visitor
now reaches Help only through a search result or the URL. That is sharpest on
`pplogin.html`, where by definition nobody is signed in yet — someone locked
out of their account has no link to the page that would tell them what to do.
The sitemap still offers it, so it stays findable from outside.

Flask serves `static/` at the site root, so `/ppsearch.html` maps to
`static/ppsearch.html`. The frontend lives in its own directory rather than at
the project root for a reason: Flask hands out **everything** under its
`static_folder` verbatim, so rooting it at the project would publish `.env`,
`app.py` and the rest of the source to anyone who asked for them.

Meetings store a wall-clock date and time plus the IANA zone they were
written in — `15:00` and `America/Chicago` — never a UTC instant. Converting
at write and back at read looks equivalent and is not, for anything in the
future: the offset a zone will have months from now is a prediction, so a
meeting on the far side of a DST boundary silently moves an hour. "Three
o'clock in Austin" has to stay three o'clock in Austin, and the instant is
derived only where one is actually needed. Meetings saved before the column
existed have no zone and are read in the viewer's own, which is the
assumption they were written under.

Each meeting can be downloaded as an `.ics` from `/api/events/<id>.ics` —
behind the session and scoped to its owner, like every other route on that
table. It carries a `VTIMEZONE` built from `tzdata` for the meeting's year
rather than a bare `TZID`, which is what makes it valid rather than merely
widely accepted. A meeting with no recorded zone is written as floating time,
which iCalendar defines as the same wall clock wherever the reader is — an
exact statement of what those rows know. It is a download, not a subscribable
feed: a feed is fetched by a calendar server with no cookie to send, so it
would need a bearer token in the URL, which is a different feature with a
different threat model.

Theme is tri-state: **system** (the default), **light**, **dark**, chosen in
Settings and stored in the browser rather than on the account, because it
describes a screen rather than an organization. An inline script in every
page's `<head>` resolves the three states to a real `data-theme` before the
first stylesheet loads, so the page never paints in one theme and switches.

That resolution happens in the script rather than through a
`prefers-color-scheme` block in the CSS on purpose. There are seven dark
rules across five stylesheets, two of them inside `@media print` blocks whose
selectors are load-bearing on specificity — a parallel copy of each under a
media query is the version that rots the first time one is edited and its
twin is not. Resolving in the script means every one of those rules stays an
ordinary `[data-theme="dark"]` match and none of them had to change. The
cost is that with JavaScript off the theme is light regardless of the OS,
which is exactly what it was before.

Shareable pages carry Open Graph tags, and `static/og-default.png` is the
1200×630 card behind them — one branded image for the whole site, not one
generated per organization. A per-org card means a rendering pipeline and a
cache, and it would put a profile's name into an image that crawlers hotlink
and hosts keep indefinitely, which is the same publishing decision indexing
is. The `og:image` URL is absolute and built from the request: a relative one
is ignored by most crawlers, and a hardcoded origin would outlive a move to a
custom domain.

`/robots.txt` and `/sitemap.xml` are routes rather than files in `static/`,
because both have to name this site's own origin and a file cannot know it.
They are built from `request.url_root`, so moving to a custom domain does not
leave a sitemap advertising the old host. The sitemap offers three pages —
the landing page, the help page and the sign-in page. `organization.html` is
deliberately not among them: public profiles are what a directory would most
want found, but nobody agreed to being published into search results by
filling in onboarding, so listing them wants a per-organization opt-in
driving both the sitemap and the `noindex` tag — the shape `links_public`
already has. Until that exists, the profiles stay out.

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

Working: accounts and sessions (including changing the sign-in address, which
only moves once a link sent to the new one is opened); onboarding;
bidirectional matching; a browsable directory with server-side search,
filters and paging; a private shortlist; public organization profiles;
partnership proposals with mutual confirmation; the lifecycle after that --
completing takes both sides, ending takes one, and each side records whether
the other delivered; shareable agreement summaries whose link can be rotated
or revoked; message threads on a proposal; meetings, with the timezone they
were arranged in and a calendar file per meeting; quantified partnership
terms; inviting an organization that has no account yet and letting it claim
the profile later; an analytics page for an organization's own numbers; and
transactional email for all of it.

Two things are switched off rather than missing, both waiting on a verified
sending domain:

- `REQUIRE_EMAIL_VERIFICATION` is off. The gate is only fair once verification
  mail reliably arrives; on Resend's sandbox sender it reaches nobody but the
  account owner, so enforcing would stop signups rather than spam.
- Signup still answers "that email is already registered". Hiding it means
  answering a taken address exactly as a new one and mailing the existing
  address to say somebody tried — which needs that same working channel. What
  is in place meanwhile is in `app.py` under `MAX_EXISTENCE_DISCLOSURES`: both
  answers cost the same hash and the same write, and one connection is told
  twice an hour before the endpoint closes for every address.

Not built: a block or report on message threads. Exposure is bounded while
threads only exist on a proposal somebody sent you and close when it settles,
but that stops being true if messaging is ever opened up to the directory.

## License

[MIT](https://choosealicense.com/licenses/mit/)
