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
});

async function updateNavForSession() {
    const loginLinks = [...document.querySelectorAll('.navbar a[href="pplogin.html"]')];
    if (loginLinks.length === 0) return;

    let me = null;
    try {
        const data = await window.api('/api/me', { allowUnauthenticated: true });
        me = data && data.organization;
    } catch {
        // Signed out, or the server is down. Either way, leave the nav alone.
        return;
    }
    if (!me) return;

    loginLinks.forEach((link) => {
        link.textContent = 'Sign out';
        link.href = '#';
        link.addEventListener('click', async (e) => {
            e.preventDefault();
            await window.api('/logout', { method: 'POST', allowUnauthenticated: true });
            location.href = 'index.html';
        });
    });
}
