// Invitation claim page.
//
// Standalone, like reset-password.js and for the same reason: this is reached
// from a link handed to somebody who has no account here at all, so it cannot
// depend on common.js -- window.api's redirect-on-401 would send the one
// visitor this page exists for to a sign-in form they cannot use.
//
// The token in the URL is the credential. It resolves to an unclaimed profile
// somebody created, and this turns that profile into an account: the claimer
// supplies their own address and password, and may correct the name, which
// they know better than whoever typed it.

document.addEventListener('DOMContentLoaded', () => {
    const card = document.getElementById('claimCard');
    const token = new URLSearchParams(location.search).get('token');

    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function showMessage(title, body, cta) {
        card.innerHTML = `
            <h1>${esc(title)}</h1>
            <p class="reset-sub">${esc(body)}</p>
            ${cta || '<a class="btn-primary" href="index.html">Go to PartnerPortal</a>'}
        `;
    }

    // Same five rules app.py's password_problem() enforces, in the order the
    // checklist below shows them -- the third copy of this on the site, and
    // deliberately identical to the other two so a password accepted on one
    // page is accepted on all of them.
    const SPECIAL_CHARS_RE = /[!@#$%^&*()_+\-=[\]{}|;:,.<>?/~`"'\\]/;
    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    function passwordChecks(password) {
        return {
            length: password.length >= 10,
            lower: /[a-z]/.test(password),
            upper: /[A-Z]/.test(password),
            digit: /[0-9]/.test(password),
            special: SPECIAL_CHARS_RE.test(password),
        };
    }

    const STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong'];

    function passwordStrength(password, checks) {
        const satisfied = Object.values(checks).filter(Boolean).length;
        if (satisfied <= 2) return 1;
        if (satisfied === 3) return 2;
        if (satisfied === 4) return 3;
        return password.length >= 14 ? 4 : 3;
    }

    function renderForm(invite) {
        // Who sent it, said first. An invitation from nobody in particular is
        // just a signup form that arrived by surprise, and the name is the
        // whole reason the person opened the link.
        const from = invite.invited_by
            ? `<p class="reset-sub"><strong>${esc(invite.invited_by)}</strong>
               invited you to partner with them on PartnerPortal.</p>`
            : `<p class="reset-sub">You have been invited to join
               PartnerPortal.</p>`;

        card.innerHTML = `
            <h1>Claim your profile</h1>
            ${from}

            <p class="form-banner" id="formBanner" hidden></p>

            <form class="reset-form" id="claimForm" novalidate>
                <div class="field">
                    <label for="orgName">Organization name</label>
                    <input type="text" id="orgName" autocomplete="organization"
                           value="${esc(invite.name)}">
                    <p class="field-error" id="orgName-error"></p>
                </div>

                <div class="field">
                    <label for="email">Your email address</label>
                    <input type="email" id="email" autocomplete="email"
                           placeholder="you@organization.org">
                    <p class="field-error" id="email-error"></p>
                </div>

                <div class="field">
                    <label for="password">Choose a password</label>
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

                <button type="submit" class="btn-primary" id="submitBtn">Create my account</button>
            </form>

            <a href="pplogin.html" class="reset-back-link">Already have an account? Sign in</a>
        `;
        wireForm();
    }

    function wireForm() {
        // Built after DOMContentLoaded, so password-field.js's own pass has
        // already run; this is what gives these fields their reveal toggle.
        if (window.wirePasswordToggles) window.wirePasswordToggles();

        const form = document.getElementById('claimForm');
        const nameInput = document.getElementById('orgName');
        const nameError = document.getElementById('orgName-error');
        const emailInput = document.getElementById('email');
        const emailError = document.getElementById('email-error');
        const pwInput = document.getElementById('password');
        const pwError = document.getElementById('password-error');
        const banner = document.getElementById('formBanner');
        const submitBtn = document.getElementById('submitBtn');

        const pwMeter = document.getElementById('pwMeter');
        const pwMeterFill = document.getElementById('pwMeterFill');
        const pwMeterLabel = document.getElementById('pwMeterLabel');
        const pwChecklist = document.getElementById('pwChecklist');

        function setFieldError(input, errorEl, message) {
            if (errorEl) errorEl.textContent = message || '';
            if (input) {
                input.classList.toggle('input-error', Boolean(message));
                input.setAttribute('aria-invalid', message ? 'true' : 'false');
            }
        }

        function setBanner(message, tone) {
            banner.textContent = message || '';
            banner.className = 'form-banner' + (tone ? ` ${tone}` : '');
            banner.hidden = !message;
        }

        pwInput.addEventListener('input', () => {
            const password = pwInput.value;
            const has = password.length > 0;
            pwMeter.hidden = !has;
            pwChecklist.hidden = !has;
            if (pwInput.classList.contains('input-error')) {
                setFieldError(pwInput, pwError, '');
            }
            if (!has) return;

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
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            setBanner('');
            setFieldError(nameInput, nameError, '');
            setFieldError(emailInput, emailError, '');
            setFieldError(pwInput, pwError, '');

            const name = nameInput.value.trim();
            const email = emailInput.value.trim();
            const password = pwInput.value;

            let firstInvalid = null;
            const fail = (input, errorEl, message) => {
                setFieldError(input, errorEl, message);
                if (!firstInvalid) firstInvalid = input;
            };

            if (name.length < 2) {
                fail(nameInput, nameError, 'Enter your organization name.');
            }
            if (!email) {
                fail(emailInput, emailError, 'Enter your email address.');
            } else if (!EMAIL_RE.test(email)) {
                fail(emailInput, emailError,
                    'That does not look like a valid email address.');
            }
            if (!Object.values(passwordChecks(password)).every(Boolean)) {
                fail(pwInput, pwError,
                    'Password does not meet the requirements below.');
            }
            if (firstInvalid) {
                firstInvalid.focus();
                return;
            }

            const idle = submitBtn.textContent;
            submitBtn.disabled = true;
            submitBtn.textContent = 'Creating your account...';

            let data = null;
            let res;
            try {
                res = await fetch(
                    `/api/invites/${encodeURIComponent(token)}/claim`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, email, password }),
                    });
                data = await res.json();
            } catch {
                setBanner('Could not reach the server. Please try again.',
                    'error');
                submitBtn.disabled = false;
                submitBtn.textContent = idle;
                return;
            }

            if (!res.ok) {
                const message = (data && data.error) || 'Something went wrong.';
                const field = data && data.field;
                if (field === 'email') setFieldError(emailInput, emailError, message);
                else if (field === 'password') setFieldError(pwInput, pwError, message);
                else if (field === 'name') setFieldError(nameInput, nameError, message);
                else setBanner(message, 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = idle;
                return;
            }

            // Claiming signs you in, so the next step is the profile itself --
            // which is the whole point of the invitation, and the only thing
            // that puts this organization in front of the one that invited it.
            submitBtn.textContent = 'Redirecting...';
            window.location.href = 'onboarding.html';
        });
    }

    async function start() {
        if (!token) {
            showMessage(
                'This link is missing its token',
                'Ask whoever invited you to send the link again.');
            return;
        }

        let res;
        let data = null;
        try {
            res = await fetch(`/api/invites/${encodeURIComponent(token)}`);
            data = await res.json();
        } catch {
            showMessage(
                'Could not reach PartnerPortal',
                'Check your connection and reload this page.');
            return;
        }

        if (!res.ok) {
            showMessage(
                'This invitation is no longer valid',
                (data && data.error)
                || 'It may already have been used, or been withdrawn.',
                '<a class="btn-primary" href="pplogin.html">Create an account instead</a>');
            return;
        }

        renderForm(data.invite);
    }

    start();
});
