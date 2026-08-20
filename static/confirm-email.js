// Landing page for the "confirm your new email" link.
//
// Standalone, like verify-email.js and for the same reason: this is opened in
// whatever browser reads the *new* inbox, which is routinely not the one
// holding the session. common.js's api() redirects to the login page on 401,
// which is the wrong default for a page whose whole job is to work without
// one -- the token is the credential here.

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

    function show(icon, tone, title, body, cta) {
        card.innerHTML = `
            <div class="verify-icon ${esc(tone)}"><i class='bx ${esc(icon)}'></i></div>
            <h1>${esc(title)}</h1>
            <p class="verify-body">${body}</p>
            ${cta || '<a class="btn-primary" href="pplogin.html">Sign in</a>'}
        `;
    }

    const token = new URLSearchParams(location.search).get('token');
    if (!token) {
        show('bx-error-circle', 'error', 'Missing link',
            'This link is missing its token. Open the most recent message '
            + 'sent to your new address, or request the change again from '
            + 'your settings.');
        return;
    }

    let result;
    let ok = true;
    try {
        const res = await fetch('/api/account/email/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ token }),
        });
        ok = res.ok;
        result = await res.json();
    } catch {
        show('bx-error-circle', 'error', 'Something went wrong',
            'We could not reach PartnerPortal. Check your connection and open '
            + 'the link again.');
        return;
    }

    if (!ok) {
        show('bx-error-circle', 'error', 'This link did not work',
            esc((result && result.error)
                || 'It may have expired or already been used.'));
        return;
    }

    // Said plainly, because this changes which address the account signs in
    // with -- and the next sign-in will fail confusingly for anyone who
    // missed that.
    show('bx-check-circle', 'ok', 'Email updated',
        `You now sign in with <strong>${esc(result.email)}</strong>. `
        + `${esc(result.previous_email)} no longer works for signing in.`);
})();
