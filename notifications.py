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
        # Where the homepage contact form is delivered. No default: guessing
        # an address would send someone's message to a stranger, and the
        # sender below would rather log a message it cannot deliver than
        # deliver it to the wrong inbox.
        "contact_to": os.environ.get("CONTACT_EMAIL", "").strip(),
    }


def _send_via_resend(cfg, to_addr, subject, html, text, reply_to=None):
    """POST to Resend. Raises on non-2xx so the caller can log it."""
    payload = {
        "from": cfg["from_addr"],
        "to": [to_addr],
        "subject": subject,
        "html": html,
        "text": text,
    }
    # Only the contact form sets this. The From address has to stay a verified
    # sender -- putting a visitor's address there is what gets a domain
    # rejected -- so the address they typed goes here instead, and Reply
    # reaches them rather than the sending domain.
    if reply_to:
        payload["reply_to"] = reply_to
    body = json.dumps(payload).encode("utf-8")
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


def _send(to_addr, subject, html, text, reply_to=None):
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
        result = _send_via_resend(cfg, to_addr, subject, html, text, reply_to)
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


def _dispatch(to_addr, subject, html, text, reply_to=None):
    """Send in a background thread so the request handler returns promptly."""
    Thread(
        target=_send, args=(to_addr, subject, html, text, reply_to), daemon=True,
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


def notify_completion_marked(proposal, actor):
    """One side marked an agreement complete; the other has to confirm.

    Without this the mutual half of completing does not work at all. Nothing
    on the site tells an organization that a partnership is waiting on its
    confirmation, so it would sit half-closed indefinitely -- the same reason
    notify_proposal_created exists for the propose step.
    """
    other = proposal.counterpart(actor.id)
    if other is None or not other.email_notifications:
        return
    cfg = _config()
    to_addr = other.contact_email or other.email
    review_url = f"{cfg['app_url']}/proposals.html#agreed"

    subject = f"{actor.name} marked your partnership complete"
    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(actor.name)} marked your partnership complete</h1>
  <p class="meta">It closes once you confirm from your side.</p>

  <p>Confirming records that this partnership ran its course. You can also
  say whether {escape(actor.name)} provided what they committed to --
  that stays between the two of you.</p>

  <a class="cta" href="{escape(review_url)}">Review and confirm</a>

  <p class="foot">You are receiving this because you and
  {escape(actor.name)} agreed a partnership through PartnerPortal.</p>
</div></body></html>
"""
    text = (
        f"{actor.name} marked your partnership complete on PartnerPortal.\n"
        f"It closes once you confirm from your side: {review_url}\n"
    )
    _dispatch(to_addr, subject, html, text)


def notify_partnership_completed(proposal, other):
    """Both sides have now confirmed. Tells whoever marked it first."""
    if other is None or not other.email_notifications:
        return
    cfg = _config()
    to_addr = other.contact_email or other.email
    url = (f"{cfg['app_url']}/partnership.html?token={proposal.share_token}"
           if proposal.share_token
           else f"{cfg['app_url']}/proposals.html#agreed")

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Partnership complete</h1>
  <p class="meta">Both organizations have confirmed it ran its course.</p>

  <a class="cta" href="{escape(url)}">View the record</a>

  <p class="foot">The shared summary stays available and now says the
  partnership is complete.</p>
</div></body></html>
"""
    text = (
        "Both organizations have confirmed your partnership is complete on "
        f"PartnerPortal.\nThe shared summary stays available: {url}\n"
    )
    _dispatch(to_addr, "Your partnership is complete", html, text)


def notify_partnership_ended(proposal, actor):
    """One side stopped an agreed partnership.

    Ending does not need the other side's agreement, which is exactly why it
    needs to reach them: otherwise the first they learn of it is a status
    changing on a page they may not open for weeks.
    """
    other = proposal.counterpart(actor.id)
    if other is None or not other.email_notifications:
        return
    cfg = _config()
    to_addr = other.contact_email or other.email
    url = f"{cfg['app_url']}/proposals.html#closed"

    reason_html = (f'<div class="quote">{escape(proposal.end_reason)}</div>'
                   if proposal.end_reason else "")
    reason_text = (f'\nTheir note: "{proposal.end_reason}"\n'
                   if proposal.end_reason else "")

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(actor.name)} ended your partnership</h1>
  <p class="meta">It is no longer active on PartnerPortal.</p>

  {reason_html}

  <a class="cta" href="{escape(url)}">See the details</a>

  <p class="foot">The record of what was agreed stays available. You can
  propose a new partnership with {escape(actor.name)} at any time.</p>
</div></body></html>
"""
    text = (
        f"{actor.name} ended your partnership on PartnerPortal.\n"
        + reason_text
        + f"\nThe record of what was agreed stays available: {url}\n"
    )
    _dispatch(to_addr, f"{actor.name} ended your partnership", html, text)


def notify_message_received(proposal, sender, message):
    """A message arrived in a thread the other side is party to.

    Throttled by the caller rather than here -- see _maybe_notify_message in
    app.py. One email per message would make an ordinary back-and-forth
    unusable and teach people to filter the address, which costs more than
    the notification is worth.

    The body is included. A "you have a new message" with no content is a
    trip to the site to find out whether it mattered, and everything else
    this file sends says what happened.
    """
    other = proposal.counterpart(sender.id)
    if other is None or not other.email_notifications:
        return
    cfg = _config()
    to_addr = other.contact_email or other.email
    thread_url = f"{cfg['app_url']}/proposals.html#messages-{proposal.id}"

    subject = f"{sender.name} sent you a message"
    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(sender.name)} sent you a message</h1>
  <p class="meta">About your partnership on PartnerPortal.</p>

  <div class="quote">{escape(message.body)}</div>

  <a class="cta" href="{escape(thread_url)}">Reply</a>

  <p class="foot">You are receiving this because you and
  {escape(sender.name)} have a proposal open on PartnerPortal. Replies to
  this address are not read -- use the link above.</p>
</div></body></html>
"""
    text = (
        f"{sender.name} sent you a message about your partnership on "
        f"PartnerPortal.\n\n"
        f"{message.body}\n\n"
        f"Reply here: {thread_url}\n"
    )
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


def notify_share_link_changed(proposal, actor, revoked):
    """The other party's copy of the share link has stopped working.

    Either side can rotate or revoke, and the reason to is usually that the
    link has gone somewhere neither of them intended. That is not a decision
    to need permission for -- but the other organization may have the old URL
    in a board pack or a grant application, and finding out it 404s from a
    funder is worse than finding out here.
    """
    other = proposal.counterpart(actor.id)
    if other is None or not other.email_notifications:
        return
    cfg = _config()
    to_addr = other.contact_email or other.email
    url = f"{cfg['app_url']}/proposals.html#agreed"

    what = ("revoked the public link for" if revoked
            else "created a new public link for")
    detail = (
        "The agreement is unchanged and you can both still see it here. There "
        "is no public link at the moment; either of you can create a new one."
        if revoked else
        "The agreement is unchanged. The previous link no longer works, so "
        "anyone you sent it to will need the new one."
    )

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>{escape(actor.name)} {escape(what)} your partnership</h1>
  <p class="meta">{escape(detail)}</p>

  <a class="cta" href="{escape(url)}">Open your partnerships</a>

  <p class="foot">You are receiving this because you and
  {escape(actor.name)} have an agreed partnership on PartnerPortal.</p>
</div></body></html>
"""
    text = (
        f"{actor.name} {what} your partnership on PartnerPortal.\n\n"
        f"{detail}\n\n{url}\n"
    )
    _dispatch(to_addr, f"{actor.name} changed your partnership's public link",
              html, text)


def notify_email_change_requested(org, token):
    """The confirmation link, sent to the address being moved to.

    Deliberately ignores email_notifications, like the other account-security
    mail: this is how somebody proves they own the address, and an account
    that opted out of partnership mail could otherwise never finish a change
    it had started.
    """
    cfg = _config()
    confirm_url = f"{cfg['app_url']}/confirm-email.html?token={token}"

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Confirm your new email address</h1>
  <p class="meta">{escape(org.name)} asked to sign in with this address on
  PartnerPortal. Nothing changes until you open the link below.</p>

  <a class="cta" href="{escape(confirm_url)}">Confirm this address</a>

  <p class="foot">Until then the account keeps signing in with
  {escape(org.email)}. If you were not expecting this, ignore this message --
  the link expires and nothing moves.</p>
</div></body></html>
"""
    text = (
        f"{org.name} asked to sign in with this address on PartnerPortal.\n"
        f"Confirm it here: {confirm_url}\n\n"
        f"Until then the account keeps signing in with {org.email}. If you "
        f"were not expecting this, ignore this message.\n"
    )
    _dispatch(org.pending_email, "Confirm your new PartnerPortal email", html, text)


def notify_email_change_notice(org):
    """Tells the *old* address that a change was requested.

    The one message that has to go to the address being moved away from.
    Changing the login moves where every future password reset goes, so if
    this was not the account holder, nothing else will ever reach them --
    the confirmation link goes to the new inbox and so does everything after
    it. This is the only warning that lands somewhere they still read.
    """
    cfg = _config()
    settings_url = f"{cfg['app_url']}/settings.html"

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Someone asked to change your email address</h1>
  <p class="meta">A request was made to move {escape(org.name)} from
  {escape(org.email)} to {escape(org.pending_email or '')}.</p>

  <p>It does not take effect until the new address is confirmed. If that was
  you, there is nothing to do here -- open the link in the message sent to
  the new address.</p>

  <p class="foot">If it was not you, someone has your password. Sign in and
  change it now, and cancel the pending change from your settings.</p>

  <a class="cta" href="{escape(settings_url)}">Open settings</a>
</div></body></html>
"""
    text = (
        f"A request was made to move {org.name} from {org.email} to "
        f"{org.pending_email}.\n\n"
        f"It does not take effect until the new address is confirmed.\n\n"
        f"If it was not you, someone has your password. Sign in, change it, "
        f"and cancel the pending change: {settings_url}\n"
    )
    _dispatch(org.email, "A change to your PartnerPortal email was requested",
              html, text)


def notify_password_changed(org):
    """Sent by /api/account/password after a successful change.

    Unlike notify_password_reset, an unsolicited send here is not the
    expected case -- change_password requires the current password first, so
    reaching this point means someone already had it. That is exactly why
    this exists: it is the one signal an account owner gets if that someone
    was not them, and the forgot-password link below is the actual recourse,
    since resetting again from the same inbox does not depend on whoever
    just changed the password knowing about it.

    Uses the login email, like the other two account emails, and for the
    same reason -- this is about the account's own credentials.

    Deliberately ignores org.email_notifications, like the other two: that
    setting is about optional partnership mail, not this.
    """
    cfg = _config()
    reset_url = f"{cfg['app_url']}/forgot-password.html"

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>Your password was changed</h1>
  <p class="meta">The password for {escape(org.email)} on PartnerPortal was
  just changed.</p>

  <p class="foot">If this was you, no action is needed. If it was not,
  reset your password right away -- the link below goes to the same inbox
  this message did, regardless of what the password was just changed to.</p>

  <a class="cta" href="{escape(reset_url)}">Reset your password</a>
</div></body></html>
"""
    text = (
        f"The password for {org.email} on PartnerPortal was just changed.\n\n"
        f"If this was you, no action is needed. If it was not, reset your "
        f"password right away: {reset_url}\n"
    )
    _dispatch(org.email, "Your PartnerPortal password was changed", html, text)


def notify_contact_message(*, name, email, phone, message):
    """The homepage "Request a demo" form, delivered to CONTACT_EMAIL.

    Loud when it cannot deliver, unlike every other sender in this file. The
    rest of them are about something already recorded in the database -- a
    proposal exists whether or not its email arrives, and the recipient will
    see it on their dashboard. This one has no row behind it: the form is the
    only copy, and the page it was typed on promises "we read every message".

    So a missing CONTACT_EMAIL logs the whole thing at WARNING rather than
    dropping it, and the same is true of the no-API-key path in _send below.
    A message in the logs is a poor inbox, but it is recoverable, and silence
    is not.
    """
    cfg = _config()
    detail = (
        f"from: {name} <{email}>\n"
        f"phone: {phone or '(none given)'}\n"
        f"--- message ---\n{message}\n---------------"
    )

    if not cfg["contact_to"]:
        log.warning(
            "contact form: CONTACT_EMAIL is not set, so this message could "
            "not be delivered. Recording it here instead:\n%s", detail,
        )
        return

    subject = f"PartnerPortal contact: {name}"
    html = f"""\
<!doctype html><html><head><meta charset="utf-8">{_EMAIL_STYLE}</head>
<body><div class="card">
  <h1>New message from the site</h1>
  <p class="meta">{escape(name)} &lt;{escape(email)}&gt;{
      f" &middot; {escape(phone)}" if phone else ""
  }</p>

  <div class="quote">{escape(message)}</div>

  <p class="foot">Sent from the contact form on PartnerPortal. Replying to
  this message goes to {escape(email)}.</p>
</div></body></html>
"""
    text = f"New message from the PartnerPortal contact form.\n\n{detail}\n"
    # reply_to, not from: the From address must stay a verified sender.
    _dispatch(cfg["contact_to"], subject, html, text, reply_to=email)


def _label(slug):
    """Category labels via the shared vocabulary."""
    from categories import label_for
    return label_for(slug)
