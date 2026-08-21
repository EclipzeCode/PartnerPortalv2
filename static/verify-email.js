// Email verification landing page.
//
// Standalone, like partnership.js: reached from an emailed link with no
// guarantee the reader is signed in on this device, so this does not load
// common.js (whose api() helper redirects to the login page on 401 -- there
// is no 401 here, the token itself is the credential, but the redirect
// behavior is the wrong default for a page that must work logged out).

(async function () {
    const card = document.getElementById('verifyCard');

    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function show(icon, tone, title, body) {
        card.innerHTML = `
            <div class="verify-icon ${esc(tone)}"><i class='bx ${esc(icon)}'></i></div>
            <h1>${esc(title)}</h1>
            <p class="verify-body">${body}</p>
            <a class="btn-primary" href="ppdashboard.html">Go to dashboard</a>
        `;
    }

    const token = new URLSearchParams(location.search).get('token');
    if (!token) {
        show('bx-error-circle', 'error', 'Missing link',
            'This link is missing its token. Ask PartnerPortal to resend the ' +
            'verification email, or check that the full link was copied.');
        return;
    }

    let result;
    let ok = true;
    try {
        const res = await fetch(`/api/verify-email?token=${encodeURIComponent(token)}`);
        result = await res.json().catch(() => ({}));
        ok = res.ok;
    } catch {
        show('bx-wifi-off', 'error', 'Could not connect',
            'Something went wrong reaching PartnerPortal. Check your connection ' +
            'and try opening the link again.');
        return;
    }

    if (!ok) {
        show('bx-error-circle', 'error', 'Verification failed', esc(result.error ||
            'This link could not be verified.'));
        return;
    }

    const name = result.organization && result.organization.name;
    show('bx-check-circle', 'success', 'Email verified',
        name
            ? `Thanks -- ${esc(name)}'s email address is confirmed.`
            : 'Thanks -- your email address is confirmed.');
})();
