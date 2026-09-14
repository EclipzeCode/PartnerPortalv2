// Login / registration.
//
// Auth is a signed session cookie set by the server. Nothing about the user is
// kept in localStorage any more -- the previous version stored a name string
// that any page could invent, which was not authentication in any real sense.

const container = document.getElementById('container');
const registerBtn = document.querySelector('.toggle-right .hidden');
const loginBtn = document.querySelector('.toggle-left .hidden');

const showRegister = () => container.classList.add('active');
const showLogin = () => container.classList.remove('active');

if (registerBtn) registerBtn.addEventListener('click', showRegister);
if (loginBtn) loginBtn.addEventListener('click', showLogin);

const toSignUp = document.getElementById('toSignUp');
const toSignIn = document.getElementById('toSignIn');
if (toSignUp) toSignUp.addEventListener('click', showRegister);
if (toSignIn) toSignIn.addEventListener('click', showLogin);

// Which panel to open first. The page defaults to Sign In, which is right
// for a returning visitor typing the URL and wrong for the two ways a new
// one arrives: every "Get started" / "Create account" link points at
// #signup, and anyone bounced here from onboarding.html has just tried to
// build a profile without an account -- landing them on "Welcome back" with
// a Sign Up button to find was the most expensive wrong form on the site.
(function openRequestedPanel() {
    const next = new URLSearchParams(location.search).get('next') || '';
    if (location.hash === '#signup' || next.startsWith('onboarding.html')) {
        showRegister();
    }
})();

// Somebody already signed in has nothing to do here. common.js has already
// asked /api/me for the nav (the request is shared, so this costs nothing
// extra); if it names an organization, go where a fresh sign-in would have.
// replace() rather than href, so Back does not return to a page that only
// bounces forward again.
window.api('/api/me', { allowUnauthenticated: true }).then((data) => {
    const org = data && data.organization;
    if (org) location.replace(destinationFor(org));
}).catch(() => {
    // Signed out, or the server is unreachable. Either way the form stays.
});

// Where to land after signing in. An org that has not finished onboarding is
// sent there first, because matches are meaningless without a profile.
function destinationFor(organization) {
    const params = new URLSearchParams(location.search);
    const next = params.get('next');
    if (!organization.onboarding_complete) return 'onboarding.html';
    // A page of this site, optionally with its own query and hash -- the
    // shape common.js builds when it bounces a signed-out request here. The
    // hash is what the email links carry (ppdashboard.html#incoming,
    // #messages-12), and it used to be dropped on the way through. Anchored
    // to a bare page name so this can never become an open redirect: no
    // scheme, no slashes, no protocol-relative prefix.
    if (next && /^[a-z0-9_-]+\.html(\?[^#\s]*)?(#[a-z0-9_-]*)?$/i.test(next)) {
        return next;
    }
    return 'ppdashboard.html';
}

// --- Field-level errors ------------------------------------------------
// Both forms carry `novalidate`; the browser's own bubble is unstyled,
// vanishes on the next click, and only ever reports the first problem. These
// replace it with a message under the offending field, in the same
// error-slot-plus-input-error-class shape the rest of the app uses (see
// onboarding.js and ppdashboard.js), just wired to this page's own markup
// since these inputs are not inside a `.form-group`.
function setFieldError(input, errorEl, message) {
    if (errorEl) errorEl.textContent = message || '';
    if (input) {
        input.classList.toggle('input-error', Boolean(message));
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
    }
}

function clearFieldErrors(...pairs) {
    pairs.forEach(([input, errorEl]) => setFieldError(input, errorEl, ''));
}

function setBanner(banner, message, tone) {
    if (!banner) return;
    banner.textContent = message || '';
    banner.className = 'form-banner' + (tone ? ` ${tone}` : '');
    banner.hidden = !message;
}

// --- Submit button state -------------------------------------------------
// Signing in used to only set disabled = true, which grays the button very
// slightly and says nothing. On a slow connection -- or a cold Render
// instance, which is the realistic case here -- that reads as a click that
// did not register, and the natural response is to click again. Both forms
// go through these so the two cannot drift apart.
function setButtonLoading(btn, loadingText) {
    // Stashed rather than hardcoded in the reset, so the idle label lives in
    // one place: the markup.
    btn.dataset.idleText = btn.textContent;
    btn.textContent = loadingText;
    btn.classList.add('is-loading');
    btn.disabled = true;
}

function clearButtonLoading(btn) {
    if (btn.dataset.idleText) btn.textContent = btn.dataset.idleText;
    btn.classList.remove('is-loading');
    btn.disabled = false;
}

// A too-permissive check would let obvious typos ("name@gmail") through to
// the server only to bounce back a second later; this is the same shape the
// server checks, so a field never passes here and fails there for a
// different reason.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// --- Password rules ------------------------------------------------------
// The five checks, the strength score and the meter painter are
// password-field.js's, shared with settings, claim and reset. The server
// additionally rejects a handful of common passwords and passwords
// containing the email or org name -- not mirrored here, since duplicating
// a blocklist client-side just to fail the same request twice adds no value;
// that feedback surfaces through the field error instead.
const pwInput = document.getElementById('register-password');

if (pwInput) {
    window.wirePasswordMeter(pwInput);
    // Clears whatever server-side password error is showing as soon as the
    // field changes, so it does not linger once the person starts fixing it.
    pwInput.addEventListener('input', () => {
        const err = document.getElementById('register-password-error');
        if (pwInput.classList.contains('input-error')) setFieldError(pwInput, err, '');
    });
}

// --- Register ---------------------------------------------------------------
const registerForm = document.querySelector('.sign-up form');
const registerBanner = document.getElementById('registerBanner');
const nameInput = document.getElementById('register-name');
const nameError = document.getElementById('register-name-error');
const registerEmailInput = document.getElementById('register-email');
const registerEmailError = document.getElementById('register-email-error');
const registerPasswordError = document.getElementById('register-password-error');
const honeypot = document.getElementById('register-website');

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    setBanner(registerBanner, '');
    clearFieldErrors(
        [nameInput, nameError],
        [registerEmailInput, registerEmailError],
        [pwInput, registerPasswordError],
    );

    const name = nameInput.value.trim();
    const email = registerEmailInput.value.trim();
    const password = pwInput.value;

    let firstInvalid = null;
    const fail = (input, errorEl, message) => {
        setFieldError(input, errorEl, message);
        if (!firstInvalid) firstInvalid = input;
    };

    if (!name) {
        fail(nameInput, nameError, 'Enter your organization name.');
    }

    if (!email) {
        fail(registerEmailInput, registerEmailError, 'Enter your email.');
    } else if (!EMAIL_RE.test(email)) {
        fail(registerEmailInput, registerEmailError,
            'That does not look like a valid email address.');
    }

    if (!window.passwordAcceptable(password)) {
        fail(pwInput, registerPasswordError,
            'Password does not meet the requirements below.');
    }

    if (firstInvalid) {
        firstInvalid.focus();
        return;
    }

    const submitBtn = document.getElementById('register-btn');
    setButtonLoading(submitBtn, 'Creating account...');

    try {
        const result = await window.api('/register', {
            method: 'POST',
            body: { name, email, password, website: honeypot.value },
            allowUnauthenticated: true
        });
        // Registering signs you in. A brief success message before leaving
        // is the only sign a verification email was sent -- the redirect
        // itself is instant otherwise, and this is the one moment there is
        // somewhere on-page to say so.
        rememberEmail(email);
        setBanner(registerBanner,
            "Account created. We've sent a verification link to your email.",
            'success');
        submitBtn.textContent = 'Redirecting...';
        setTimeout(() => {
            window.location.href = destinationFor(result.organization);
        }, 1400);
    } catch (error) {
        routeRegisterError(error);
        clearButtonLoading(submitBtn);
    }
});

function routeRegisterError(error) {
    const message = error.message || 'Something went wrong. Please try again.';
    if (error.status === 429) {
        setBanner(registerBanner, message, 'error');
        return;
    }
    // The server names the field when it can, and that is authoritative:
    // a moderation refusal or "Organization name is too long" says `name`,
    // and used to land under Email because the word-matching below saw
    // "name" and had no branch for it.
    const byField = {
        name: [nameInput, nameError],
        email: [registerEmailInput, registerEmailError],
        password: [pwInput, registerPasswordError],
    }[error.data && error.data.field];
    if (byField) {
        setFieldError(byField[0], byField[1], message);
        byField[0].focus();
        return;
    }
    // Older or field-less answers, routed by what they talk about.
    const lower = message.toLowerCase();
    if (lower.includes('password')) {
        setFieldError(pwInput, registerPasswordError, message);
    } else if (lower.includes('email')) {
        setFieldError(registerEmailInput, registerEmailError, message);
    } else if (lower.includes('name')) {
        setFieldError(nameInput, nameError, message);
    } else {
        setBanner(registerBanner, message, 'error');
    }
}

// --- Login ------------------------------------------------------------------
const loginForm = document.querySelector('.sign-in form');
const loginBanner = document.getElementById('loginBanner');
const loginEmailInput = document.getElementById('login-email');

// The address used last time, offered again. Only the address: it is the
// half of a sign-in that is not a secret, and it is what somebody coming
// back on the same browser retypes every time. The browser's own autofill
// covers this for many people and not for everyone -- a shared office
// machine with autofill off, a browser that never offered to save. Kept in
// this browser only, cleared by signing out, and never sent anywhere.
const LAST_EMAIL_KEY = 'partnerPortalLastEmail';

function rememberEmail(email) {
    try {
        if (email) localStorage.setItem(LAST_EMAIL_KEY, email);
        else localStorage.removeItem(LAST_EMAIL_KEY);
    } catch {
        // Storage disabled; the form still works.
    }
}

(function prefillLastEmail() {
    if (!loginEmailInput || loginEmailInput.value) return;
    try {
        const last = localStorage.getItem(LAST_EMAIL_KEY);
        if (!last) return;
        loginEmailInput.value = last;
        // The password is what they still have to type.
        const password = document.getElementById('login-password');
        if (password && !location.hash) password.focus();
    } catch {
        // Nothing remembered.
    }
})();
const loginEmailError = document.getElementById('login-email-error');
const loginPasswordInput = document.getElementById('login-password');
const loginPasswordError = document.getElementById('login-password-error');

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    setBanner(loginBanner, '');
    clearFieldErrors(
        [loginEmailInput, loginEmailError],
        [loginPasswordInput, loginPasswordError],
    );

    const email = loginEmailInput.value.trim();
    const password = loginPasswordInput.value;

    let firstInvalid = null;
    const fail = (input, errorEl, message) => {
        setFieldError(input, errorEl, message);
        if (!firstInvalid) firstInvalid = input;
    };

    if (!email) {
        fail(loginEmailInput, loginEmailError, 'Enter your email.');
    } else if (!EMAIL_RE.test(email)) {
        fail(loginEmailInput, loginEmailError,
            'That does not look like a valid email address.');
    }
    if (!password) {
        fail(loginPasswordInput, loginPasswordError, 'Enter your password.');
    }

    if (firstInvalid) {
        firstInvalid.focus();
        return;
    }

    const submitBtn = document.getElementById('login-btn');
    setButtonLoading(submitBtn, 'Signing in...');

    try {
        const result = await window.api('/login', {
            method: 'POST',
            body: { email, password },
            allowUnauthenticated: true
        });
        rememberEmail(email);
        // Left in the loading state on purpose: the navigation below is the
        // next thing to happen, and putting "Sign In" back first would flash
        // an idle-looking button on a page that is already leaving.
        submitBtn.textContent = 'Redirecting...';
        window.location.href = destinationFor(result.organization);
    } catch (error) {
        // "Invalid email or password" deliberately does not say which one --
        // singling out a field would leak whether the address is registered.
        // A banner says the same thing without pointing at either field.
        setBanner(loginBanner, error.message || 'Something went wrong.', 'error');
        clearButtonLoading(submitBtn);
    }
});
