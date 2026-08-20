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
    try {
        const data = await window.api('/api/me', { allowUnauthenticated: true });
        me = data && data.organization;
        pendingProposals = (data && data.pending_proposals) || 0;
    } catch {
        // Signed out, or the server is down. The signed-out call to action is
        // the honest thing to show in both cases.
    }

    rememberSessionHint(Boolean(me));
    delete slot.dataset.hint;

    if (!me) {
        slot.dataset.state = 'out';
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
    wireAccountMenu();
    updateProposalBadge(pendingProposals);
}

// The badge on the nav's Dashboard link. Proposals waiting on this org to
// respond were otherwise invisible outside of email -- the dashboard is the
// only place they can be acted on, and nothing on the rest of the site said
// one was there. Hidden entirely rather than shown as "0", the same "nothing
// here" treatment the rest of the nav uses.
function updateProposalBadge(count) {
    const badge = document.getElementById('navProposalBadge');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.hidden = false;
    } else {
        badge.hidden = true;
    }
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
