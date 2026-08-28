// Shared behavior loaded on every page.
// Must be included BEFORE the page-specific script.

// Flask serves these files itself now, so the API is same-origin and the base
// is always empty. The old localhost:5000 switch is gone, along with the CORS
// setup and the macOS AirPlay port collision that came with it.
window.API_BASE = '';

// One round trip, before any policy is applied to it. Kept separate from
// api() below so the same response can be handed to two callers that disagree
// about what a 401 means -- see the /api/me note.
//
// The body is held as text rather than as parsed JSON: two callers sharing one
// response must not share one mutable object, or whichever of them edits it
// first silently edits the other's copy.
// How long any one request may hang before it is given up on.
//
// fetch() has no timeout of its own: a connection that opens and then stalls
// -- a phone moving between networks, a proxy holding the socket, Render
// asleep behind a request that will never be answered -- leaves the promise
// pending forever. Every caller here awaits that promise to decide what to
// draw, so a stalled request is a page that shows its loading skeletons
// permanently, with no error, no retry, and nothing to click.
//
// Generous, because the floor is not the network: Neon scales to zero and a
// cold start behind a warm-up request has been measured near ten seconds
// (see the note on the /api/me memo below), and render.yaml gives gunicorn
// `--timeout 120` for exactly that reason. Twenty seconds is comfortably
// past the slow-but-working case and well short of the forever this
// replaces.
const REQUEST_TIMEOUT_MS = 20000;

async function rawRequest(path, opts) {
    // AbortSignal.timeout() is not in every browser this needs to run in, so
    // the controller is driven by hand where it is missing.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    let res;
    try {
        res = await fetch(`${window.API_BASE}${path}`,
                          { ...opts, signal: controller.signal });
    } catch (err) {
        // An abort is this timeout firing, and it reaches the caller as a
        // DOMException named AbortError -- which reads as "Aborted" or as
        // nothing at all wherever error.message is shown to a person. Said
        // in words instead, and marked so a caller that wants to tell a
        // timeout from a refusal can.
        if (err && err.name === 'AbortError') {
            const timeout = new Error(
                'That took too long to answer. Check your connection and '
                + 'try again.');
            timeout.timeout = true;
            throw timeout;
        }
        // Offline, DNS, TLS, connection refused. fetch rejects with
        // "Failed to fetch", which names the API rather than the problem.
        const offline = new Error(
            'Could not reach the server. Check your connection and try '
            + 'again.');
        offline.offline = true;
        throw offline;
    } finally {
        clearTimeout(timer);
    }

    let text = '';
    try {
        text = await res.text();
    } catch {
        // Body already consumed or the connection dropped mid-read.
    }
    return { status: res.status, ok: res.ok, text };
}

// GET /api/me, shared for the life of the page.
//
// Every page with an account slot in the nav asks for it once from
// updateNavForSession(), and then the page's own script asks again --
// ppsearch.js, settings.js and onboarding.js all do. Two identical requests,
// and /api/me is @login_required, so each one resolves the session with a
// database query. Against a scale-to-zero Postgres that measured 1.6-3.8s
// warm and 9.7s cold, which is a lot to pay twice for the same bytes.
//
// This is deliberately a promise, not a result: the second caller usually
// arrives while the first request is still in flight, so it joins that request
// rather than starting another. Nothing is cached across page loads -- the
// memo dies with the document, so a session that ends elsewhere is still
// noticed on the next navigation.
let meRequest = null;

// For callers that need the current answer rather than the page's first one.
// refreshNavCounts() is the case this exists for: it runs after the visitor
// has just read a thread or answered a proposal, and the whole point is that
// the badge stops claiming something is waiting.
window.invalidateMe = function invalidateMe() {
    meRequest = null;
};

// Single place where session expiry is handled. Every API call goes through
// this, so a 401 sends the user to the login page instead of leaving a screen
// of empty widgets with no explanation.
window.api = async function api(path, options = {}) {
    const opts = {
        // Cookies are the session, so they must ride along. Same-origin is
        // fetch's default, but stating it means a future move to a separate
        // API host does not silently break auth.
        credentials: 'same-origin',
        ...options,
    };

    if (opts.body && !(opts.headers && opts.headers['Content-Type'])) {
        opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
        if (typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    }

    // The CSRF token on anything that can change something. Attached here,
    // in the one place every call in the app already passes through, rather
    // than at each of the sixty-odd call sites -- a scheme that has to be
    // remembered per request is one that gets forgotten on the request that
    // matters. The server refuses an unsafe method without it; see
    // require_csrf_token in app.py.
    //
    // Read per request, not captured once: the cookie is replaced when a
    // session is created or rotated (signing in does both), and a token
    // captured at page load would be the previous session's.
    const unsafe = !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(
        (opts.method || 'GET').toUpperCase());
    if (unsafe && window.csrfHeaders) {
        opts.headers = window.csrfHeaders(opts.headers || {});
    }

    // `fresh` opts out of the shared request and replaces it, so whoever asks
    // next gets the new answer rather than the one being replaced.
    const method = (opts.method || 'GET').toUpperCase();
    const shared = path === '/api/me' && method === 'GET' && !opts.body && !opts.fresh;
    if (path === '/api/me' && opts.fresh) meRequest = null;

    let result;
    if (shared) {
        if (!meRequest) meRequest = rawRequest(path, opts);
        try {
            result = await meRequest;
        } catch (err) {
            // A failed request must not be remembered as this page's answer.
            meRequest = null;
            throw err;
        }
    } else {
        result = await rawRequest(path, opts);
        if (path === '/api/me' && method === 'GET' && !opts.body) {
            meRequest = Promise.resolve(result);
        }
    }

    let data = null;
    try {
        data = result.text ? JSON.parse(result.text) : null;
    } catch {
        // Non-JSON response (a proxy error page, say). Leave data null and let
        // the status drive the error message.
    }

    // Applied per caller, not once on the shared response: updateNavForSession
    // passes allowUnauthenticated and wants a null back, while a page script
    // wants the redirect. Sharing the round trip must not mean sharing this
    // decision, or a signed-out visitor would sit on a half-built page instead
    // of being sent to sign in.
    if (result.status === 401 && !opts.allowUnauthenticated) {
        const here = encodeURIComponent(location.pathname.replace(/^\//, ''));
        location.href = `pplogin.html?next=${here}`;
        // Never resolves; the navigation is already underway.
        return new Promise(() => {});
    }

    if (!result.ok) {
        const error = new Error((data && data.error) || `Request failed (${result.status})`);
        error.status = result.status;
        error.data = data;
        throw error;
    }

    return data;
};

// Escapes text before it goes anywhere near innerHTML. Organization names and
// notes are user-supplied, so this is the difference between a profile and
// stored XSS.
window.escapeHtml = function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
};

// --- Toasts -----------------------------------------------------------
// Several actions here succeed by navigating: sending a proposal lands you on
// the dashboard, deleting an account lands you on the home page. The
// navigation was the only feedback, which reads as "something happened" but
// never says what, or whether it worked.
//
// A toast shown before a redirect would be destroyed by that redirect, so
// toastAfterRedirect() parks it in sessionStorage and the next page picks it
// up on load. sessionStorage rather than localStorage: it is scoped to this
// tab, so a queued message cannot surface in an unrelated one, and it dies
// with the tab rather than waiting around for the next visit.
const TOAST_HANDOFF_KEY = 'partnerPortalPendingToast';
const TOAST_DURATION_MS = 5000;

function toastStack() {
    let stack = document.querySelector('.toast-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'toast-stack';
        // polite, not assertive: these confirm something the user just did,
        // so they should wait their turn rather than interrupt.
        stack.setAttribute('role', 'status');
        stack.setAttribute('aria-live', 'polite');
        document.body.appendChild(stack);
    }
    return stack;
}

window.toast = function toast(message, kind = 'ok') {
    if (!message) return;

    const el = document.createElement('div');
    el.className = `toast ${kind}`;

    const icon = document.createElement('i');
    icon.className = kind === 'error' ? 'bx bx-error-circle' : 'bx bx-check-circle';
    icon.setAttribute('aria-hidden', 'true');

    // textContent, not innerHTML: messages interpolate organization names.
    const text = document.createElement('p');
    text.textContent = message;

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.innerHTML = '&times;';

    el.append(icon, text, close);
    toastStack().appendChild(el);

    let timer = null;
    const dismiss = () => {
        clearTimeout(timer);
        if (!el.isConnected) return;
        el.classList.add('leaving');
        // Falls back to a timeout because animationend never fires when
        // prefers-reduced-motion has removed the animation.
        const drop = () => el.remove();
        el.addEventListener('animationend', drop, { once: true });
        setTimeout(drop, 250);
    };

    close.addEventListener('click', dismiss);
    timer = setTimeout(dismiss, TOAST_DURATION_MS);
    return dismiss;
};

// Queue a toast for whatever page loads next. Call immediately before
// assigning location.
window.toastAfterRedirect = function toastAfterRedirect(message, kind = 'ok') {
    try {
        sessionStorage.setItem(TOAST_HANDOFF_KEY, JSON.stringify({ message, kind }));
    } catch {
        // Private browsing, or storage disabled. The redirect still happens;
        // only the confirmation is lost, which is no worse than before.
    }
};

function drainToastHandoff() {
    let raw = null;
    try {
        raw = sessionStorage.getItem(TOAST_HANDOFF_KEY);
        // Removed before it is shown, so a queued toast cannot reappear on
        // every subsequent navigation in this tab.
        if (raw) sessionStorage.removeItem(TOAST_HANDOFF_KEY);
    } catch {
        return;
    }
    if (!raw) return;
    try {
        const { message, kind } = JSON.parse(raw);
        if (message) window.toast(message, kind);
    } catch {
        // Malformed entry; nothing useful to show.
    }
}

// --- Dialogs -----------------------------------------------------------
// Focus handling for the eight modals across this site, in one place because
// each of them had been getting some part of it wrong.
//
// Two problems this fixes. Focus never moved into a dialog when it opened,
// so the caret stayed on the button behind it and Tab walked the page
// underneath rather than the form on top -- and every attempt to fix that
// locally failed silently, because .modal is `visibility: hidden` under a
// transition and nothing inside it can take focus in the tick the class
// lands. And focus was not put back on close, so a keyboard visitor was
// returned to the top of the document each time.
//
// Callers keep their own .active toggling; these only handle focus, and are
// called immediately after the class goes on or comes off.
const FOCUSABLE_SELECTOR = [
    'a[href]', 'button:not([disabled])', 'input:not([disabled])',
    'select:not([disabled])', 'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

const openDialogs = new Map();

function focusableIn(container) {
    // getClientRects rather than offsetParent: the latter is null for
    // position: fixed elements, which is most of what a dialog contains.
    // Elements hidden with [hidden] or display:none have no rects and drop
    // out here.
    //
    // visibility is checked separately because those elements *do* keep
    // their rects, and focus() on one silently does nothing -- which would
    // leave the wrap below pointing at an element that can never take focus.
    // It also covers the fade-in: everything inside reads as hidden until
    // the transition starts, which is exactly when there is nothing to focus
    // yet and focusInto should keep waiting.
    return [...container.querySelectorAll(FOCUSABLE_SELECTOR)].filter(
        (el) => el.getClientRects().length > 0
            && window.getComputedStyle(el).visibility !== 'hidden',
    );
}

// Tries to put focus inside, and keeps trying until the fade-in has
// progressed far enough for that to be possible. Gives up rather than
// looping forever: a dialog with nothing focusable in it is not an error.
function focusInto(modal, preferred) {
    let settled = false;
    const timers = [];

    const finish = () => {
        settled = true;
        timers.forEach(clearTimeout);
        modal.removeEventListener('transitionend', attempt);
    };

    function attempt() {
        if (settled) return;
        const target = (preferred && preferred.getClientRects().length > 0)
            ? preferred
            : focusableIn(modal)[0];
        if (!target) return;
        target.focus();
        if (modal.contains(document.activeElement)) finish();
    }

    attempt();                                  // already visible?
    if (settled) return;
    modal.addEventListener('transitionend', attempt);
    requestAnimationFrame(() => requestAnimationFrame(attempt));
    // Backstop for the cases the two above miss: a browser that coalesces
    // the frames, or a tab that is not painting at all.
    [60, 180, 400].forEach((ms) => timers.push(setTimeout(attempt, ms)));
    timers.push(setTimeout(finish, 600));
}

// Call right after the dialog is shown. `preferred` is the control focus
// should land on when it is not simply the first one in the markup.
window.dialogOpened = function dialogOpened(modal, preferred) {
    if (!modal || openDialogs.has(modal)) return;

    const onKeydown = (e) => {
        if (e.key !== 'Tab') return;
        // Only the dialog on top traps. A confirmation opened from inside
        // another dialog registers second, and while it is up the one
        // underneath has to leave Tab alone: otherwise both traps run on
        // every Tab and the lower one pulls focus back out of the dialog the
        // user is actually answering. openDialogs is insertion-ordered, so
        // the last key is whatever opened most recently.
        const stack = [...openDialogs.keys()];
        if (stack[stack.length - 1] !== modal) return;
        const list = focusableIn(modal);
        if (list.length === 0) {
            // Nothing to move to, but Tab must still not escape into the
            // page behind the dialog.
            e.preventDefault();
            return;
        }
        const first = list[0];
        const last = list[list.length - 1];
        const active = document.activeElement;
        const outside = !modal.contains(active);
        if (e.shiftKey && (active === first || outside)) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && (active === last || outside)) {
            e.preventDefault();
            first.focus();
        }
    };

    // Capture phase, so the trap runs before any page-level Tab handling.
    document.addEventListener('keydown', onKeydown, true);
    openDialogs.set(modal, { opener: document.activeElement, onKeydown });
    focusInto(modal, preferred);
};

// Call right after the dialog is hidden.
window.dialogClosed = function dialogClosed(modal) {
    const state = modal && openDialogs.get(modal);
    if (!state) return;
    document.removeEventListener('keydown', state.onKeydown, true);
    openDialogs.delete(modal);
    // document.contains: the opener is routinely gone by the time a dialog
    // closes -- confirming a proposal or removing a meeting re-renders the
    // list its button was in.
    if (state.opener && document.contains(state.opener)) state.opener.focus();
};

// --- Character counters ------------------------------------------------
// Every textarea with a maxlength gets one, wired here rather than per page
// so a new field cannot be added without it.
//
// The counter appears only once the field is most of the way full. A form
// with six textareas would otherwise carry six "0 / 2000" labels from the
// moment it loads -- noise on every field, to warn about a limit almost
// nobody reaches. Silence until it is close, then a count, then a warning.
//
// maxlength stops the typing on its own; what it does not do is explain why
// the keyboard went dead, which is the actual failure this addresses.
const COUNTER_SHOW_AT = 0.8;    // of the limit
const COUNTER_WARN_AT = 0.95;

function wireCharacterCounters(root = document) {
    root.querySelectorAll('textarea[maxlength]').forEach((field) => {
        const limit = Number(field.getAttribute('maxlength'));
        if (!limit || field.dataset.counterWired) return;
        field.dataset.counterWired = '1';

        const counter = document.createElement('span');
        counter.className = 'char-counter';
        // Not a live region: it updates on every keystroke, and announcing
        // each one would talk over the typing. The limit is in the markup
        // where a screen reader already reports it.
        counter.setAttribute('aria-hidden', 'true');
        counter.hidden = true;
        field.insertAdjacentElement('afterend', counter);

        const paint = () => {
            const used = field.value.length;
            const ratio = used / limit;
            counter.hidden = ratio < COUNTER_SHOW_AT;
            if (counter.hidden) return;
            const left = limit - used;
            counter.textContent = left === 0
                ? 'Limit reached'
                : `${left} character${left === 1 ? '' : 's'} left`;
            counter.classList.toggle('warn', ratio >= COUNTER_WARN_AT);
        };

        field.addEventListener('input', paint);
        // Fields arrive pre-filled when a profile is being edited.
        paint();
    });
}

window.wireCharacterCounters = wireCharacterCounters;


document.addEventListener('DOMContentLoaded', () => {
    wireCharacterCounters();

    // --- Mobile navigation ---------------------------------------------
    const menuIcon = document.getElementById('menu-icon');
    const navbar = document.querySelector('.navbar');

    if (menuIcon && navbar) {
        const closeMenu = () => {
            navbar.classList.remove('active');
            menuIcon.classList.add('bx-menu');
            menuIcon.classList.remove('bx-x');
            menuIcon.setAttribute('aria-expanded', 'false');
        };

        menuIcon.addEventListener('click', () => {
            const isOpen = navbar.classList.toggle('active');
            menuIcon.classList.toggle('bx-menu', !isOpen);
            menuIcon.classList.toggle('bx-x', isOpen);
            menuIcon.setAttribute('aria-expanded', String(isOpen));
        });

        navbar.querySelectorAll('a').forEach((link) => {
            link.addEventListener('click', closeMenu);
        });

        document.addEventListener('click', (e) => {
            if (!navbar.contains(e.target) && !menuIcon.contains(e.target)) {
                closeMenu();
            }
        });
    }

    // --- Session-aware navigation ---------------------------------------
    // The nav is static markup, so it used to show "Login" to signed-in users.
    // One cheap call settles it for every page.
    updateNavForSession();

    // Anything a previous page queued on its way out.
    drainToastHandoff();
});

// Two words at most, so "Bridgewater Community Arts Trust" reads as BC rather
// than a wall of capitals. Filtering empties first keeps a stray double space
// from producing `undefined[0]`.
function initialsFor(name) {
    const words = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) return '?';
    return words.slice(0, 2).map((w) => w[0]).join('').toUpperCase();
}

// Whether this browser has recently had a signed-in session.
//
// NOT authentication, and never to be used as such: the session cookie is
// HttpOnly precisely so scripts cannot read it, and this flag is trivially
// forgeable from the console. It decides one thing -- whether to draw an
// avatar placeholder while /api/me is in flight -- and nothing downstream
// trusts it. The server is still the only thing that decides who anyone is.
//
// It exists because the placeholder would otherwise be a guess. A signed-out
// visitor shown a shimmering avatar has been told they are logged in, and on
// a cold start that lie can sit there for a second or more before the CTA
// replaces it. With the flag, first-time and signed-out visitors get the
// blank slot they got before, and only people who actually were signed in
// see the avatar placeholder.
const SESSION_HINT_KEY = 'partnerPortalSignedIn';

function rememberSessionHint(signedIn) {
    try {
        if (signedIn) localStorage.setItem(SESSION_HINT_KEY, '1');
        else localStorage.removeItem(SESSION_HINT_KEY);
    } catch {
        // Storage disabled or full. The placeholder is a nicety; losing it
        // costs nothing.
    }
}

function hasSessionHint() {
    try {
        return localStorage.getItem(SESSION_HINT_KEY) === '1';
    } catch {
        return false;
    }
}

// For pages that end a session themselves rather than through the nav's own
// sign-out -- deleting an account, for one.
window.forgetSession = function forgetSession() {
    rememberSessionHint(false);
};

// Where "Connect" and "Find partners" go, and whether "Dashboard" is offered
// at all.
//
// Both used to be one hardcoded answer -- ppsearch.html -- on every page,
// which for a signed-out visitor was a link to a login form wearing the name
// of the thing they wanted. The home page's own "Browse partners" button was
// the worst of them: the directory is what this product has to show, and the
// only route to it required the account it exists to justify.
//
// Decided here rather than in fifteen templates because this function is
// already the one place that knows the answer, and it runs on every page.
// The markup ships the signed-out destination, so a crawler and a visitor
// with no JavaScript both get the page that works without an account; being
// signed in is what upgrades it.
function routeSessionLinks(signedIn) {
    document.querySelectorAll(
        'a[href="ppsearch.html"], a[href="directory.html"]'
    ).forEach((link) => {
        link.href = signedIn ? 'ppsearch.html' : 'directory.html';
    });

    // Offered only when it leads somewhere. Signed out it redirects to the
    // login page, which is a nav item that punishes the click.
    document.querySelectorAll('.navbar a[href="ppdashboard.html"]')
        .forEach((link) => { link.hidden = !signedIn; });
}

async function updateNavForSession() {
    const slot = document.getElementById('navAccount');
    if (!slot) return;

    // Set before the await so the placeholder is up for the whole wait, not
    // just after it. A stale hint (session expired since the last visit)
    // shows the placeholder and then resolves to the signed-out CTA, which
    // is the same correction the nav made anyway -- just with something in
    // the slot rather than nothing.
    if (hasSessionHint()) slot.dataset.hint = 'in';

    let me = null;
    let pendingProposals = 0;
    let unreadThreads = 0;
    try {
        const data = await window.api('/api/me', { allowUnauthenticated: true });
        me = data && data.organization;
        pendingProposals = (data && data.pending_proposals) || 0;
        // Threads, not messages. The badge is a count of things waiting on
        // you and the notification panel behind it lists one entry per
        // conversation, so counting messages here made the number on the
        // bell disagree with the list it opens.
        unreadThreads = (data && data.unread_threads) || 0;
    } catch {
        // Signed out, or the server is down. The signed-out call to action is
        // the honest thing to show in both cases.
    }

    rememberSessionHint(Boolean(me));
    delete slot.dataset.hint;

    if (!me) {
        slot.dataset.state = 'out';
        routeSessionLinks(false);
        updateProposalBadge(0);
        return;
    }

    const set = (id, text) => {
        const el = document.getElementById(id);
        // textContent, not innerHTML: the name is whatever the org typed.
        if (el) el.textContent = text;
    };
    set('accountInitials', initialsFor(me.name));
    set('accountLabel', me.name || 'Your account');
    set('accountName', me.name || 'Your account');
    set('accountEmail', me.email || '');

    slot.dataset.state = 'in';
    routeSessionLinks(true);
    wireAccountMenu();
    // Built here rather than in fifteen page templates; see notifications.js.
    // Only for a signed-in visitor, which is the state this branch is.
    if (window.mountNotificationBell) window.mountNotificationBell();
    // Both land on the same badge: from the nav's point of view they are the
    // same question -- is there something on the dashboard waiting for me --
    // and two competing numbers on one link would only make it ambiguous
    // which one the reader is meant to act on.
    updateProposalBadge(pendingProposals + unreadThreads);
}

// Re-reads the counts without redrawing the account menu. For pages that
// change what the badge is counting -- reading a thread, answering a
// proposal -- so the nav stops claiming something is waiting the moment it
// stops being true, rather than at the next navigation.
window.refreshNavCounts = async function refreshNavCounts() {
    try {
        // fresh: this is called precisely because the counts have changed.
        const data = await window.api(
            '/api/me', { allowUnauthenticated: true, fresh: true });
        updateProposalBadge(
            ((data && data.pending_proposals) || 0)
            + ((data && data.unread_threads) || 0));
    } catch {
        // Signed out or offline. The badge keeps whatever it last knew,
        // which is no worse than the page it is sitting on.
    }
};

// Catch the badge up when the tab comes back.
//
// The counts were read once, on load, and never again unless something on
// the page went and changed them. So the common way to use this site -- leave
// the dashboard open in a tab, come back to it after lunch -- showed
// whatever was true when the tab was opened. A proposal that arrived in the
// meantime was invisible until a reload, which is a long way from what a
// notification bell appears to promise.
//
// Tied to the tab becoming visible rather than to a timer. A background tab
// polling every thirty seconds spends requests on nobody looking, and the
// moment somebody *is* looking is exactly the moment the number needs to be
// right. Focus as well as visibilitychange: switching between two windows
// that are both on screen never fires the latter.
//
// Throttled, because those two overlap -- returning to the tab commonly
// fires both -- and because flicking between windows should not turn into a
// request per flick.
const NAV_REFRESH_IDLE_MS = 30000;
let navRefreshedAt = Date.now();

function refreshNavCountsIfStale() {
    if (document.visibilityState === 'hidden') return;
    if (Date.now() - navRefreshedAt < NAV_REFRESH_IDLE_MS) return;
    navRefreshedAt = Date.now();
    // Signed-out pages have no badge to update and refreshNavCounts swallows
    // the 401 that says so, so this is safe to wire up unconditionally.
    if (window.refreshNavCounts) window.refreshNavCounts();
}

document.addEventListener('visibilitychange', refreshNavCountsIfStale);
window.addEventListener('focus', refreshNavCountsIfStale);

// How many proposals are waiting on this organization, shown on the bell.
//
// It used to light a second badge on the Dashboard nav link as well. That was
// the same number in two places, and the weaker of the two: a bare count on a
// link, with nothing to open and no way to say what it was made of. The bell
// can list the actual items, so the count lives there alone now.
function updateProposalBadge(count) {
    if (window.setNotificationDot) window.setNotificationDot(count);
}

function wireAccountMenu() {
    const toggle = document.getElementById('accountToggle');
    const dropdown = document.getElementById('accountDropdown');
    const signOut = document.getElementById('accountSignOut');
    if (!toggle || !dropdown) return;

    const setOpen = (open) => {
        dropdown.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
    };

    toggle.addEventListener('click', (e) => {
        // Without this the document listener below sees the same click and
        // closes the menu in the same tick it was opened.
        e.stopPropagation();
        setOpen(dropdown.hidden);
    });

    document.addEventListener('click', (e) => {
        if (dropdown.hidden) return;
        if (!dropdown.contains(e.target) && !toggle.contains(e.target)) setOpen(false);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || dropdown.hidden) return;
        setOpen(false);
        // Focus goes back to what opened the menu, rather than being left on
        // an element that is now hidden.
        toggle.focus();
    });

    if (signOut) {
        signOut.addEventListener('click', async () => {
            await window.api('/logout', { method: 'POST', allowUnauthenticated: true });
            // Cleared here as well as on the next /api/me, so the page landed
            // on after signing out does not briefly draw an avatar for an
            // account that just signed out of it.
            rememberSessionHint(false);
            location.href = 'index.html';
        });
    }
}
