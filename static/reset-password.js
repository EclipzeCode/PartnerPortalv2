// Password reset landing page.
//
// Standalone, like verify-email.js: reached from an emailed link with no
// guarantee the reader is signed in on this device, so this does not load
// common.js -- there is no nav state to show, and window.api's redirect-on-401
// behaviour is the wrong default for a page that must work fully logged out.

document.addEventListener('DOMContentLoaded', () => {
    const card = document.getElementById('resetCard');
    const token = new URLSearchParams(location.search).get('token');

    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function showStatus(icon, tone, title, body) {
        card.innerHTML = `
            <div class="reset-icon ${esc(tone)}"><i class='bx ${esc(icon)}'></i></div>
            <h1>${esc(title)}</h1>
            <p class="reset-body">${body}</p>
            <a class="btn-primary" href="forgot-password.html">Request a new link</a>
        `;
    }

    if (!token) {
        showStatus('bx-error-circle', 'error', 'Missing link',
            'This link is missing its token. Check that the full link was ' +
            'copied, or request a new one.');
        return;
    }

    renderForm();

    // --- Password rules -----------------------------------------------------
    // Same five checks app.py's password_problem() enforces, in the same
    // order pplogin.js's signup checklist uses, restated here rather than
    // shared across files per that file's own note on why: duplicating a
    // dozen lines is simpler than a shared module two pages reach for.
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

    const STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong'];
    // The colours for these four levels live in notice.css, keyed off
    // data-score. They were four hardcoded hex values assigned inline from
    // here, which meant they could not follow the theme -- the third copy of
    // this meter to be fixed the same way, after settings and sign-up.

    function passwordStrength(password, checks) {
        const satisfied = Object.values(checks).filter(Boolean).length;
        let score;
        if (satisfied <= 2) score = 1;
        else if (satisfied === 3) score = 2;
        else if (satisfied === 4) score = 3;
        else score = password.length >= 14 ? 4 : 3;
        return score;
    }

    function renderForm() {
        card.innerHTML = `
            <h1>Choose a new password</h1>
            <p class="reset-sub">Pick something you have not used here before.</p>

            <p class="form-banner" id="formBanner" hidden></p>

            <form class="reset-form" id="resetForm" novalidate>
                <div class="field">
                    <label for="password">New password</label>
                    <input type="password" id="password" autocomplete="new-password">
                    <p class="field-error" id="password-error"></p>

                    <div class="pw-meter" id="pwMeter" hidden>
                        <div class="pw-meter-bar">
                            <span class="pw-meter-fill" id="pwMeterFill"></span>
                        </div>
                        <span class="pw-meter-label" id="pwMeterLabel"></span>
                    </div>

                    <ul class="pw-checklist" id="pwChecklist" hidden>
                        <li data-rule="length"><i class='bx bx-circle'></i> At least 10 characters</li>
                        <li data-rule="lower"><i class='bx bx-circle'></i> One lowercase letter</li>
                        <li data-rule="upper"><i class='bx bx-circle'></i> One uppercase letter</li>
                        <li data-rule="digit"><i class='bx bx-circle'></i> One number</li>
                        <li data-rule="special"><i class='bx bx-circle'></i> One special character</li>
                    </ul>
                </div>

                <div class="field">
                    <label for="confirmPassword">Confirm new password</label>
                    <input type="password" id="confirmPassword" autocomplete="new-password">
                    <p class="field-error" id="confirmPassword-error"></p>
                </div>

                <button type="submit" class="btn-primary" id="submitBtn">Reset password</button>
            </form>

            <a href="pplogin.html" class="reset-back-link">&larr; Back to sign in</a>
        `;
        wireForm();
    }

    function wireForm() {
        const form = document.getElementById('resetForm');
        const pwInput = document.getElementById('password');
        const pwError = document.getElementById('password-error');
        const confirmInput = document.getElementById('confirmPassword');
        const confirmError = document.getElementById('confirmPassword-error');
        const banner = document.getElementById('formBanner');
        const submitBtn = document.getElementById('submitBtn');

        const pwMeter = document.getElementById('pwMeter');
        const pwMeterFill = document.getElementById('pwMeterFill');
        const pwMeterLabel = document.getElementById('pwMeterLabel');
        const pwChecklist = document.getElementById('pwChecklist');

        function setBanner(message, tone) {
            banner.textContent = message || '';
            banner.className = 'form-banner' + (tone ? ` ${tone}` : '');
            banner.hidden = !message;
        }

        function setFieldError(input, errorEl, message) {
            errorEl.textContent = message || '';
            input.classList.toggle('input-error', Boolean(message));
        }

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

        pwInput.addEventListener('input', () => {
            updatePasswordUI();
            setFieldError(pwInput, pwError, '');
        });
        confirmInput.addEventListener('input', () => setFieldError(confirmInput, confirmError, ''));

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            setBanner('');
            setFieldError(pwInput, pwError, '');
            setFieldError(confirmInput, confirmError, '');

            const password = pwInput.value;
            const confirm = confirmInput.value;

            let firstInvalid = null;
            const checks = passwordChecks(password);
            if (!passwordIsAcceptable(checks)) {
                setFieldError(pwInput, pwError, 'Password does not meet the requirements below.');
                firstInvalid = pwInput;
            } else if (password !== confirm) {
                setFieldError(confirmInput, confirmError, 'Passwords do not match.');
                firstInvalid = confirmInput;
            }

            if (firstInvalid) {
                firstInvalid.focus();
                return;
            }

            submitBtn.disabled = true;
            submitBtn.textContent = 'Resetting...';

            try {
                const res = await fetch('/api/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ token, password }),
                });
                const data = await res.json().catch(() => ({}));

                if (!res.ok) {
                    if (res.status === 404 || res.status === 410) {
                        // The token itself is the problem, not anything the
                        // form collected -- the field errors above do not
                        // apply, so this replaces the whole card rather than
                        // pointing at an input.
                        showStatus('bx-error-circle', 'error',
                            res.status === 410 ? 'Link expired' : 'Link invalid',
                            esc(data.error || 'This link could not be used.'));
                        return;
                    }
                    if (data.field === 'password') {
                        setFieldError(pwInput, pwError, data.error);
                        pwInput.focus();
                    } else {
                        setBanner(data.error || 'Something went wrong. Please try again.', 'error');
                    }
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Reset password';
                    return;
                }

                // The response signs the browser in, same as a fresh
                // registration does -- the dashboard is the useful next
                // stop, not a second trip through the login form.
                setBanner("Password reset. Signing you in...", 'success');
                submitBtn.textContent = 'Redirecting...';
                setTimeout(() => { window.location.href = 'ppdashboard.html'; }, 1200);
            } catch {
                setBanner('Could not reach PartnerPortal. Check your connection and try again.', 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Reset password';
            }
        });
    }
});
