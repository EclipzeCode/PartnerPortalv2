"""Transactional email for partnership events.

Without this, a proposal sits invisible until the recipient happens to open
their dashboard. Real organizations do not check daily, and the whole
propose → confirm loop silently fails to run.

Delivery goes through Resend when RESEND_API_KEY is set. Otherwise -- during
local development, or if the key is missing in production -- the email is
written to stderr instead, so the flow still works and the content can be
inspected without signing up for anything or spending free-tier credits.

Sending is fire-and-forget: an SMTP hiccup or a Resend rate limit must not
fail the proposal itself. Every send is wrapped, and failures are logged and
swallowed. The user's action succeeds either way.

NOTE: this file is intentionally NOT named email.py -- that name shadows the
stdlib `email` package that other libraries pull in.
"""

import json
import logging
import os
import urllib.request
import urllib.error
from html import escape
from threading import Thread

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _config():
    """Read email settings fresh every call.

    Reading at call time (rather than caching at import) means the fallback
    stays honest during tests, and rotating the API key does not require a
    restart to take effect.
    """
    return {
        "api_key": os.environ.get("RESEND_API_KEY", "").strip(),
        # Must be a verified sender in your Resend project. Resend's own
        # sandbox `onboarding@resend.dev` works out of the box for testing.
        "from_addr": (os.environ.get("EMAIL_FROM") or
                      "PartnerPortal <onboarding@resend.dev>"),
        # Where the "View proposal" links point. Defaults to localhost so
        # local development stays self-contained.
        "app_url": (os.environ.get("APP_BASE_URL") or
                    "http://127.0.0.1:5001").rstrip("/"),
    }


def _send_via_resend(cfg, to_addr, subject, html, text):
    """POST to Resend. Raises on non-2xx so the caller can log it."""
    body = json.dumps({
        "from": cfg["from_addr"],
        "to": [to_addr],
        "subject": subject,
        "html": html,
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(
        RESEND_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            # Cloudflare (Resend's CDN) blocks the default `Python-urllib/x.y`
            # user agent with error 1010. Any real UA works.
            "User-Agent": "PartnerPortal/1.0 (+partnerportal-j6x1.onrender.com)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send(to_addr, subject, html, text):
    """Actual sender. Called on a background thread so the request returns
    without waiting for Resend.
    """
    cfg = _config()

    if not to_addr:
        log.warning("email: skipped, recipient has no address (subject: %s)", subject)
        return

    if not cfg["api_key"]:
        # Development fallback: show what would have been sent. Kept short so
        # dev logs stay readable; the HTML body is not printed.
        log.info(
            "email (dry-run, no RESEND_API_KEY):\n"
            "  to:      %s\n"
            "  from:    %s\n"
            "  subject: %s\n"
            "  --- text ---\n%s\n  ------------",
            to_addr, cfg["from_addr"], subject, text,
        )
        return

    try:
        result = _send_via_resend(cfg, to_addr, subject, html, text)
        log.info("email sent to %s (id=%s)", to_addr, result.get("id"))
    except urllib.error.HTTPError as e:
        # A 401 means a bad or missing key; a 403 usually means the from
        # address is not verified. Log the response body so the fix is
        # obvious, but do not raise.
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = "<no body>"
        log.error("email to %s failed: HTTP %s — %s", to_addr, e.code, detail)
    except Exception as e:
        log.exception("email to %s failed: %s", to_addr, e)


def _dispatch(to_addr, subject, html, text):
    """Send in a background thread so the request handler returns promptly."""
    Thread(
        target=_send, args=(to_addr, subject, html, text), daemon=True,
    ).start()


# --- Templates --------------------------------------------------------------
# HTML is written by hand rather than through a template engine: two short
# messages don't earn a Jinja dependency, and inline styles are what most
# email clients actually respect.

_EMAIL_STYLE = """\
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         line-height: 1.6; color: #2b2d42; background: #f5f7ff; margin: 0; padding: 24px; }
  .card { max-width: 560px; margin: 0 auto; background: #fff;
          border-radius: 12px; padding: 28px; box-shadow: 0 4px 20px rgba(0,0,0,.06); }
  h1 { font-size: 20px; margin: 0 0 8px; color: #1a1a2e; }
  .meta { color: #8d99ae; font-size: 14px; margin-bottom: 20px; }
  .terms { background: #f7f9ff; border-radius: 8px; padding: 16px; margin: 18px 0; }
  .terms h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
              color: #8d99ae; margin: 0 0 8px; font-weight: 700; }
  .terms ul { margin: 0; padding-left: 20px; }
  .terms li { margin-bottom: 4px; }
  .cta { display: inline-block; background: #4361ee; color: #fff !important;
         text-decoration: none; padding: 12px 24px; border-radius: 8px;
         font-weight: 600; margin-top: 12px; }
  .quote { border-left: 3px solid #e0e0e0; padding: 4px 0 4px 14px;
           color: #4a4a4a; font-style: italic; margin: 16px 0; }
  .foot { color: #8d99ae; font-size: 12px; text-align: center; margin-top: 24px; }
  a { color: #4361ee; }
</style>
"""


def _terms_block(title, items):
    if not items:
        return ""
    lis_html = "".join(f"<li>{escape(x)}</li>" for x in items)
    return (f'<div class="terms"><h3>{escape(title)}</h3>'
            f'<ul>{lis_html}</ul></div>')


def _terms_text(title, items):
    if not items:
        return ""
    return f"{title}:\n" + "\n".join(f"  • {x}" for x in items) + "\n"


def notify_proposal_created(proposal):
    """The recipient gets an email when someone proposes a partnership.

    Called after commit so the proposal.id and share_token are stable.
    """
    if not proposal.recipient.email_notifications:
        return
    cfg = _config()
    to_addr = proposal.recipient.contact_email or proposal.recipient.email
    proposer = proposal.proposer.name

    subject = f"{proposer} proposed a partnership with you"
    review_url = f"{cfg['app_url']}/proposals.html#incoming"

    they_give_labels = [
        # public_summary is heavier than we need here; format the two lists
        # directly off the model.
        _label(s) for s in (proposal.proposer_gives or [])
    ]
    you_give_labels = [_label(s) for s in (proposal.recipient_gives or [])]

    quote_html = (
        f'<div class="quote">{escape(proposal.message)}</div>'
        if proposal.message else ""
    )
    quote_text = f'\nTheir note: "{proposal.message}"\n' if proposal.message else ""

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(proposer)} proposed a partnership</h1>
  <p class="meta">On PartnerPortal — accept, decline, or ignore.</p>

  {_terms_block("They would provide", they_give_labels)}
  {_terms_block("You would provide", you_give_labels)}
  {quote_html}

  <a class="cta" href="{escape(review_url)}">Review proposal</a>

  <p class="foot">You are receiving this because {escape(proposer)}
  proposed a partnership with {escape(proposal.recipient.name)} on
  PartnerPortal. Sign in to accept or decline.</p>
</div></body></html>
"""

    text = (
        f"{proposer} proposed a partnership with {proposal.recipient.name} "
        f"on PartnerPortal.\n\n"
        + _terms_text("They would provide", they_give_labels)
        + _terms_text("You would provide", you_give_labels)
        + quote_text
        + f"\nReview it here: {review_url}\n"
    )
    _dispatch(to_addr, subject, html, text)


def notify_proposal_responded(proposal):
    """The proposer gets an email when the recipient accepts or declines."""
    if not proposal.proposer.email_notifications:
        return
    cfg = _config()
    to_addr = proposal.proposer.contact_email or proposal.proposer.email
    responder = proposal.recipient.name
    accepted = proposal.status == "accepted"

    subject = (f"{responder} accepted your partnership proposal"
               if accepted
               else f"{responder} declined your partnership proposal")

    quote_html = (
        f'<div class="quote">{escape(proposal.response_message)}</div>'
        if proposal.response_message else ""
    )
    quote_text = (f'\nTheir note: "{proposal.response_message}"\n'
                  if proposal.response_message else "")

    if accepted:
        share_url = (f"{cfg['app_url']}/partnership.html?"
                     f"token={proposal.share_token}") if proposal.share_token else None
        headline = "Both sides confirmed. You have a partnership."
        cta_label = "View the agreement"
        cta_url = share_url or f"{cfg['app_url']}/proposals.html#agreed"
        text_body = (
            f"{responder} accepted your partnership proposal on PartnerPortal.\n"
            f"You can now share the agreement summary with anyone: {cta_url}\n"
        )
    else:
        headline = f"{responder} said no this time."
        cta_label = "See details"
        cta_url = f"{cfg['app_url']}/proposals.html#closed"
        text_body = (
            f"{responder} declined your partnership proposal on PartnerPortal.\n"
            f"You can propose again to them later, or find other partners: "
            f"{cta_url}\n"
        )

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(headline)}</h1>
  <p class="meta">Response from {escape(responder)}.</p>

  {quote_html}

  <a class="cta" href="{escape(cta_url)}">{escape(cta_label)}</a>

  <p class="foot">You are receiving this because you proposed a partnership
  with {escape(responder)} on PartnerPortal.</p>
</div></body></html>
"""

    text = text_body + quote_text
    _dispatch(to_addr, subject, html, text)


def notify_email_verification(org, token):
    """Sent after registration, and again on request from the settings page.

    Uses the login email, not contact_email: on the signup path contact_email
    has not been set yet (it defaults to the login email during onboarding),
    and this message is about the account itself, not the profile a partner
    would see. On a resend the two are often both set and different, and the
    login address is still the right one -- it is what this link confirms.

    Deliberately ignores org.email_notifications, which the other two senders
    here honour. That setting covers optional partnership mail; this is how
    someone proves the address is theirs, and it now gates whether they can
    propose a partnership at all. An org that had turned notifications off
    could otherwise never verify, and never find out why.
    """
    cfg = _config()
    verify_url = f"{cfg['app_url']}/verify-email.html?token={token}"

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Verify your email</h1>
  <p class="meta">One click confirms {escape(org.email)} is really you.</p>

  <a class="cta" href="{escape(verify_url)}">Verify email</a>

  <p class="foot">You are receiving this because this address was used to
  register {escape(org.name)} on PartnerPortal. If that was not you, no
  further action is needed -- the link expires and nothing is shared until
  it is used.</p>
</div></body></html>
"""
    text = (
        f"Confirm {org.email} is really you: {verify_url}\n\n"
        f"You are receiving this because this address was used to register "
        f"{org.name} on PartnerPortal. If that was not you, no further "
        f"action is needed.\n"
    )
    _dispatch(org.email, "Verify your email for PartnerPortal", html, text)


def notify_password_reset(org, token):
    """Sent by /forgot-password. The link is the only credential the reset
    endpoint checks, so this is the one email on the site where an
    unsolicited send is the expected case, not a bug: anyone can type in
    anyone else's address, and the reassurance that nothing happens without
    the click is the point of the footer note below, not filler.

    Uses the login email, like notify_email_verification, and for the same
    reason -- this is about the account's own credentials, not the profile a
    partner would see.

    Deliberately ignores org.email_notifications for the same reason
    notify_email_verification does: that setting is about optional
    partnership mail, and an account-security action is not optional.
    """
    cfg = _config()
    reset_url = f"{cfg['app_url']}/reset-password.html?token={token}"

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Reset your password</h1>
  <p class="meta">Someone asked to reset the password for {escape(org.email)}
  on PartnerPortal. This link expires in 1 hour.</p>

  <a class="cta" href="{escape(reset_url)}">Choose a new password</a>

  <p class="foot">If you did not request this, no action is needed -- your
  password has not been changed, and it will not change unless this link is
  used.</p>
</div></body></html>
"""
    text = (
        f"Reset the password for {org.email} on PartnerPortal: {reset_url}\n"
        f"This link expires in 1 hour.\n\n"
        f"If you did not request this, no action is needed -- your password "
        f"has not been changed.\n"
    )
    _dispatch(org.email, "Reset your PartnerPortal password", html, text)


def _label(slug):
    """Category labels via the shared vocabulary."""
    from categories import label_for
    return label_for(slug)
