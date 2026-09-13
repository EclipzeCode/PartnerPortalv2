// Reading this session's CSRF token back out of the cookie the server set.
//
// The server mints a token into the signed session and publishes a readable
// copy as `pp_csrf` (see send_csrf_cookie in app.py). Every state-changing
// request has to echo it back in the X-CSRF-Token header; a cross-site page
// cannot, because the same-origin policy will not let it read this cookie.
//
// Its own file rather than a function inside common.js, because the pages
// that most need it are the ones that do not load common.js. claim.html,
// confirm-email.html and reset-password.html are deliberately standalone --
// they are reached from a link in an email by somebody who may not be signed
// in, and they have no nav to wire up -- but they all POST. Three inline
// copies of a cookie parser is how one of them ends up subtly different from
// the other two.

(() => {
    const COOKIE = 'pp_csrf';

    // fetch() with a ceiling on how long it may hang. common.js gives api()
    // one (REQUEST_TIMEOUT_MS, same twenty seconds and the same reasoning:
    // past a cold Neon start, short of forever); the standalone pages that
    // load this file instead of common.js had none, so a connection that
    // opened and stalled left them on "Loading..." indefinitely. The abort
    // surfaces as a rejected promise, which every caller already catches
    // with a "could not reach PartnerPortal" message. Lives here for the
    // same reason the cookie parser does: it is the one script all of those
    // pages share.
    const TIMEOUT_MS = 20000;
    window.timedFetch = function timedFetch(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
        return fetch(url, { ...options, signal: controller.signal })
            .finally(() => clearTimeout(timer));
    };

    // document.cookie is one string of "a=1; b=2". Split on the separator
    // rather than matching the name loosely: a cookie called "other_pp_csrf"
    // would otherwise satisfy a naive indexOf and hand back the wrong value.
    window.csrfToken = function csrfToken() {
        const jar = document.cookie ? document.cookie.split('; ') : [];
        for (const entry of jar) {
            const eq = entry.indexOf('=');
            if (eq < 0) continue;
            if (entry.slice(0, eq) === COOKIE) {
                try {
                    return decodeURIComponent(entry.slice(eq + 1));
                } catch {
                    // A malformed value is not a token; asking the server
                    // with it would fail anyway, and failing here would take
                    // the page down instead.
                    return '';
                }
            }
        }
        return '';
    };

    // Headers for a mutating request, with whatever else the caller wanted.
    //
    // The token is omitted rather than sent empty when there is none: an
    // absent header and an empty one are refused identically by the server,
    // and sending an empty one implies this knew something it did not.
    window.csrfHeaders = function csrfHeaders(extra = {}) {
        const token = window.csrfToken();
        return token ? { ...extra, 'X-CSRF-Token': token } : { ...extra };
    };
})();
