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

// Where to land after signing in. An org that has not finished onboarding is
// sent there first, because matches are meaningless without a profile.
function destinationFor(organization) {
    const params = new URLSearchParams(location.search);
    const next = params.get('next');
    if (!organization.onboarding_complete) return 'onboarding.html';
    if (next && /^[a-z0-9_-]+\.html$/i.test(next)) return next;
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
// Signing in used to only set disabled = true, which greys the button very
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
// Same five checks app.py's password_problem() enforces server-side, in the
// same order the checklist below displays them. The server additionally
// rejects a handful of common passwords and passwords containing the email
// or org name -- not mirrored here, since duplicating a blocklist client-side
// just to fail the same request twice adds no value; that feedback surfaces
// through the banner instead if it is ever what trips someone up.
const SPECIAL_CHARS_RE = /[!@#$%^&*()_+\-=[\]{}|;:,.<>?/~`"'\\]/;

function passwordChecks(password) {
    return {
        length: password.length >= 10,
        lower: /[a-z]/.test(password),
        upper: /[A-Z]/.test(password),
        digit: /[0-9]/.test(password),
        special: SPECIAL_CHARS_RE.test(password),
    };
}

function passwordIsAcceptable(checks) {
    return Object.values(checks).every(Boolean);
}

// A 1-4 heuristic, not a real entropy estimate: reaching "Strong" needs every
// rule satisfied *and* real length margin above the 10-character floor, so
// the meter rewards actually going further rather than just clearing the bar.
const STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong'];
// The colours for these four levels live in pplogin.css, keyed off
// data-score. They were four hardcoded hex values assigned inline from here,
// which meant they could not follow the theme -- the same fix the settings
// page's copy of this meter already has.

function passwordStrength(password, checks) {
    const satisfied = Object.values(checks).filter(Boolean).length;
    let score;
    if (satisfied <= 2) score = 1;
    else if (satisfied === 3) score = 2;
    else if (satisfied === 4) score = 3;
    else score = password.length >= 14 ? 4 : 3;
    return score;
}

// --- Password strength UI -------------------------------------------------
const pwInput = document.getElementById('register-password');
const pwMeter = document.getElementById('pwMeter');
const pwMeterFill = document.getElementById('pwMeterFill');
const pwMeterLabel = document.getElementById('pwMeterLabel');
const pwChecklist = document.getElementById('pwChecklist');

function updatePasswordUI() {
    const password = pwInput.value;
    const hasValue = password.length > 0;

    pwMeter.hidden = !hasValue;
    pwChecklist.hidden = !hasValue;
    if (!hasValue) return;

    const checks = passwordChecks(password);

    pwChecklist.querySelectorAll('li[data-rule]').forEach((item) => {
        const met = Boolean(checks[item.dataset.rule]);
        item.classList.toggle('met', met);
        const icon = item.querySelector('i');
        if (icon) icon.className = met ? 'bx bx-check-circle' : 'bx bx-circle';
    });

    const score = passwordStrength(password, checks);
    pwMeter.dataset.score = String(score);
    pwMeterFill.style.width = `${(score / 4) * 100}%`;
    pwMeterLabel.textContent = STRENGTH_LABELS[score - 1];
}

if (pwInput) {
    pwInput.addEventListener('input', updatePasswordUI);
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

    const checks = passwordChecks(password);
    if (!passwordIsAcceptable(checks)) {
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
    const lower = message.toLowerCase();
    if (lower.includes('password')) {
        setFieldError(pwInput, registerPasswordError, message);
    } else if (lower.includes('email') || lower.includes('name')) {
        // Covers "already registered", "valid email address" and the
        // disposable-domain message, all of which are about the email field;
        // the org-name-in-password case is caught by the password branch
        // above since its message also contains "password".
        setFieldError(registerEmailInput, registerEmailError, message);
    } else {
        setBanner(registerBanner, message, 'error');
    }
}

// --- Login ------------------------------------------------------------------
const loginForm = document.querySelector('.sign-in form');
const loginBanner = document.getElementById('loginBanner');
const loginEmailInput = document.getElementById('login-email');
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
