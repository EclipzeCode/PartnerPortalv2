// Shared behaviour loaded on every page.
// Must be included BEFORE the page-specific script.

// Flask serves these files itself now, so the API is same-origin and the base
// is always empty. The old localhost:5000 switch is gone, along with the CORS
// setup and the macOS AirPlay port collision that came with it.
window.API_BASE = '';

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

    const res = await fetch(`${window.API_BASE}${path}`, opts);

    let data = null;
    try {
        data = await res.json();
    } catch {
        // Non-JSON response (a proxy error page, say). Leave data null and let
        // the status drive the error message.
    }

    if (res.status === 401 && !opts.allowUnauthenticated) {
        const here = encodeURIComponent(location.pathname.replace(/^\//, ''));
        location.href = `pplogin.html?next=${here}`;
        // Never resolves; the navigation is already underway.
        return new Promise(() => {});
    }

    if (!res.ok) {
        const error = new Error((data && data.error) || `Request failed (${res.status})`);
        error.status = res.status;
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

document.addEventListener('DOMContentLoaded', () => {
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
    try {
        const data = await window.api('/api/me', { allowUnauthenticated: true });
        me = data && data.organization;
    } catch {
        // Signed out, or the server is down. The signed-out call to action is
        // the honest thing to show in both cases.
    }

    rememberSessionHint(Boolean(me));
    delete slot.dataset.hint;

    if (!me) {
        slot.dataset.state = 'out';
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
    wireAccountMenu();
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
