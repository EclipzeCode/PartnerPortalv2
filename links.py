"""Normalising and validating the optional links on an organization profile.

Everything here is stored as a full canonical URL so the profile page can put
it straight into an href without reassembling anything at render time. People
type these four fields in wildly different shapes -- "@handle", "handle",
"instagram.com/handle", the full https URL with tracking query string -- so
each parser accepts all of those and returns one canonical form.

Two things this is deliberately strict about:

1. Scheme. Every value here ends up inside an href. `javascript:` (and
   `data:`, `vbscript:`) in an href executes on click, and HTML-escaping does
   not stop it -- escaping protects the attribute's quoting, not its
   contents. So the scheme is allowlisted to http/https rather than
   blocklisting the dangerous ones, and the social parsers never trust the
   input's scheme at all: they extract a handle and rebuild the URL against a
   hardcoded host.

2. Host. A "social" field that accepts any URL is a phishing surface -- a
   profile could point its Instagram link at somewhere else entirely, wearing
   an Instagram icon. Each social parser only accepts its own domain.
"""

import re
from urllib.parse import urlsplit

# Matches the String(255) columns these are stored in.
MAX_URL_LENGTH = 255

ALLOWED_SCHEMES = ("http", "https")

# Anything with a scheme-ish prefix ("https:", "javascript:", "mailto:").
_HAS_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Whitespace and control characters have no business in a URL and are a
# classic way to smuggle something past a naive parser.
_CONTROL_RE = re.compile(r"[\s\x00-\x1f\x7f]")

# Instagram: letters, digits, periods, underscores, up to 30.
_INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
# X: letters, digits, underscores, up to 15.
_X_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
# LinkedIn: /company/<slug>, /in/<slug>, /school/<slug>.
_LINKEDIN_PATH_RE = re.compile(
    r"^/(company|in|school)/([A-Za-z0-9\-._%]{1,100})/?$"
)
# A hostname with at least one dot and a plausible TLD. Keeps "localhost",
# bare words and "http://192.168.0.1" out of the website field without
# pretending to be a full public-suffix check.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


class LinkError(ValueError):
    """Raised with a message written for the person filling in the form.

    `field` is set by parse_links once it knows which input failed, so the
    caller can highlight that input instead of showing a page-level message.
    """

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _clean(raw):
    """Trim, and reject anything with whitespace or control characters."""
    value = (raw or "").strip()
    if not value:
        return ""
    if _CONTROL_RE.search(value):
        raise LinkError("That link contains spaces or invalid characters.")
    if len(value) > MAX_URL_LENGTH:
        raise LinkError(f"That link is too long (maximum {MAX_URL_LENGTH} characters).")
    return value


def _split(value):
    """Parse into (host, path), tolerating a missing scheme.

    urlsplit reads "instagram.com/foo" as a bare path with no host, so a
    scheme is added first when one is absent. A present scheme is checked
    against the allowlist before anything else happens with it.
    """
    if _HAS_SCHEME_RE.match(value):
        parts = urlsplit(value)
        if parts.scheme.lower() not in ALLOWED_SCHEMES:
            raise LinkError("Links must start with http:// or https://.")
    else:
        parts = urlsplit("https://" + value)

    host = (parts.hostname or "").lower()
    if not host:
        raise LinkError("That does not look like a valid link.")
    return host, parts.path or ""


def _strip_www(host):
    return host[4:] if host.startswith("www.") else host


def _looks_like_host(value, host_suffixes):
    """True if the bare value is one of these domains rather than a handle.

    Needed because Instagram handles may contain periods, so "instagram.com"
    typed on its own would otherwise pass as the handle "instagram.com" and
    be stored as instagram.com/instagram.com.
    """
    bare = _strip_www(value.lower().rstrip("/"))
    return any(bare == s or bare.endswith("." + s) for s in host_suffixes)


def _handle_from(value, host_suffixes, handle_re, what):
    """Pull a handle out of either a bare handle or a URL on an allowed host."""
    candidate = value

    # A bare "@handle" or "handle", with no host at all.
    if (not _HAS_SCHEME_RE.match(candidate) and "/" not in candidate
            and not _looks_like_host(candidate, host_suffixes)):
        handle = candidate.lstrip("@")
        if not handle_re.match(handle):
            raise LinkError(f"That does not look like a valid {what} username.")
        return handle

    host, path = _split(candidate)
    bare_host = _strip_www(host)
    # Accept country subdomains (uk.linkedin.com) as well as the bare domain.
    if not any(bare_host == s or bare_host.endswith("." + s) for s in host_suffixes):
        allowed = " or ".join(host_suffixes)
        raise LinkError(f"That link is not on {allowed}. Use your {what} profile link.")

    handle = path.strip("/").split("/")[0].lstrip("@")
    if not handle_re.match(handle):
        raise LinkError(f"That does not look like a valid {what} username.")
    return handle


def parse_instagram(raw):
    value = _clean(raw)
    if not value:
        return None
    handle = _handle_from(
        value, ("instagram.com",), _INSTAGRAM_HANDLE_RE, "Instagram"
    )
    return f"https://instagram.com/{handle}"


def parse_x(raw):
    value = _clean(raw)
    if not value:
        return None
    # twitter.com still resolves and is what plenty of people have saved.
    handle = _handle_from(value, ("x.com", "twitter.com"), _X_HANDLE_RE, "X")
    return f"https://x.com/{handle}"


def parse_linkedin(raw):
    value = _clean(raw)
    if not value:
        return None
    # No bare-handle form here: "acme" is ambiguous between /company/acme and
    # /in/acme, and guessing wrong points at a stranger.
    if not _HAS_SCHEME_RE.match(value) and "/" not in value:
        raise LinkError(
            "Paste the full LinkedIn URL, e.g. linkedin.com/company/your-org."
        )

    host, path = _split(value)
    bare_host = _strip_www(host)
    if not (bare_host == "linkedin.com" or bare_host.endswith(".linkedin.com")):
        raise LinkError("That is not a LinkedIn link.")

    match = _LINKEDIN_PATH_RE.match(path if path.startswith("/") else "/" + path)
    if not match:
        raise LinkError(
            "Use a LinkedIn company or profile URL, "
            "e.g. linkedin.com/company/your-org."
        )
    kind, slug = match.groups()
    return f"https://www.linkedin.com/{kind}/{slug}"


def parse_website(raw):
    value = _clean(raw)
    if not value:
        return None

    had_scheme = bool(_HAS_SCHEME_RE.match(value))
    host, path = _split(value)
    if not _HOSTNAME_RE.match(host):
        raise LinkError("That does not look like a valid website address.")

    # The path is kept here (unlike the socials, which are rebuilt from a
    # handle) because a real site may live on one -- a page on a shared
    # community host, say. The scheme has already passed _split's allowlist.
    parts = urlsplit(value if had_scheme else "https://" + value)
    scheme = parts.scheme.lower() if had_scheme else "https"
    url = f"{scheme}://{host}{(parts.path or '').rstrip('/')}"
    if parts.query:
        url += "?" + parts.query
    return url


# Field name -> (parser, label used in error messages). The keys match both
# the JSON keys the onboarding endpoint accepts and the Organization columns.
LINK_FIELDS = {
    "website_url": (parse_website, "Website"),
    "instagram_url": (parse_instagram, "Instagram"),
    "x_url": (parse_x, "X"),
    "linkedin_url": (parse_linkedin, "LinkedIn"),
}


def parse_links(data):
    """Normalise every link field present in `data`.

    Returns {column_name: url_or_None}. Raises LinkError naming the field that
    failed, so the caller can point the form at it.
    """
    out = {}
    for field, (parser, label) in LINK_FIELDS.items():
        try:
            out[field] = parser(data.get(field))
        except LinkError as e:
            raise LinkError(f"{label}: {e}", field=field) from None
    return out
