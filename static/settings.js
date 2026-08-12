// Account settings.
//
// Two independent pieces: a preference that saves the moment it is toggled,
// and a deletion flow that deliberately takes three deliberate actions to
// complete (open, confirm, then re-enter the password).

document.addEventListener('DOMContentLoaded', async () => {
    const toggle = document.getElementById('emailNotifications');
    const status = document.getElementById('settingStatus');

    // --- Load ------------------------------------------------------------
    let me;
    let verificationRequired = false;
    try {
        const data = await window.api('/api/me');
        me = data.organization;
        verificationRequired = Boolean(data.verification_required);
    } catch (error) {
        console.error('Could not load settings:', error);
        return; // api() redirects on 401; anything else leaves the page as-is
    }

    toggle.checked = Boolean(me.email_notifications);

    document.getElementById('accountEmailValue').textContent = me.email || '—';
    document.getElementById('verifiedValue').innerHTML = me.email_verified
        ? '<span class="pill ok"><i class=\'bx bx-check\'></i> Verified</span>'
        : '<span class="pill warn"><i class=\'bx bx-time\'></i> Not verified</span>';
    document.getElementById('profileValue').textContent = me.onboarding_complete
        ? 'Complete'
        : 'Not finished';

    const publicLink = document.getElementById('viewPublicProfile');
    publicLink.href = `organization.html?id=${encodeURIComponent(me.id)}`;

    // --- Email verification ------------------------------------------------
    const verifyPrompt = document.getElementById('verifyPrompt');
    const verifyStatus = document.getElementById('verifyStatus');
    const resendBtn = document.getElementById('resendVerifyBtn');

    if (!me.email_verified) {
        document.getElementById('verifyPromptEmail').textContent = me.email || '';
        // Only claims proposals are blocked when they actually are.
        document.getElementById('verifyPromptDetail').textContent =
            verificationRequired
                ? 'Until the address is confirmed you can do everything except '
                  + 'send a partnership proposal.'
                : 'Confirming it shows partners the address behind your account '
                  + 'is real. Nothing is blocked in the meantime.';
        verifyPrompt.hidden = false;
    }

    resendBtn.addEventListener('click', async () => {
        resendBtn.disabled = true;
        verifyStatus.hidden = true;
        try {
            const result = await window.api('/api/verify-email/resend', {
                method: 'POST',
            });
            verifyStatus.textContent =
                `Sent. Check ${result.email} for the new link — it replaces any ` +
                'earlier one.';
            verifyStatus.className = 'setting-status ok';
            verifyStatus.hidden = false;
            // Left disabled on success: the mail is on its way, and the next
            // useful action is reading it, not sending another.
        } catch (error) {
            verifyStatus.textContent =
                error.message || 'Could not send that. Please try again.';
            verifyStatus.className = 'setting-status error';
            verifyStatus.hidden = false;
            resendBtn.disabled = false;
        }
    });

    // --- Notification preference -----------------------------------------
    let statusTimer = null;

    function showStatus(message, kind) {
        status.textContent = message;
        status.className = `setting-status ${kind}`;
        status.hidden = false;
        clearTimeout(statusTimer);
        // Errors stay put; a success message that lingers stops meaning
        // "just saved" and starts looking like part of the page.
        if (kind === 'ok') {
            statusTimer = setTimeout(() => { status.hidden = true; }, 3000);
        }
    }

    toggle.addEventListener('change', async () => {
        const wanted = toggle.checked;
        // Disabled while in flight so a fast double-toggle cannot leave the
        // switch showing the result of the request that happened to land
        // second rather than the one clicked last.
        toggle.disabled = true;
        try {
            await window.api('/api/settings', {
                method: 'PATCH',
                body: { email_notifications: wanted },
            });
            showStatus(
                wanted
                    ? 'Partnership emails are on.'
                    : 'Partnership emails are off.',
                'ok',
            );
        } catch (error) {
            // Put the switch back where it was: it should never show a state
            // the server did not accept.
            toggle.checked = !wanted;
            showStatus(
                error.message || 'Could not save that. Please try again.',
                'error',
            );
        } finally {
            toggle.disabled = false;
        }
    });

    // --- Modals ------------------------------------------------------------
    const confirmModal = document.getElementById('confirmDeleteModal');
    const passwordModal = document.getElementById('passwordDeleteModal');
    const deleteForm = document.getElementById('deleteForm');
    const passwordInput = document.getElementById('deletePassword');
    const submitBtn = document.getElementById('deleteSubmitBtn');

    document.getElementById('deleteEmailLabel').textContent = me.email || '';

    // What to focus when a modal closes, so focus is never left on a hidden
    // element.
    let lastFocus = null;

    function openModal(modal, focusTarget) {
        lastFocus = document.activeElement;
        modal.classList.add('active');
        if (focusTarget) focusTarget.focus();
    }

    function closeModal(modal) {
        modal.classList.remove('active');
        if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    }

    function openModals() {
        return [confirmModal, passwordModal].filter(
            (m) => m.classList.contains('active'),
        );
    }

    // Every Cancel button, X, and backdrop shares one path out.
    [confirmModal, passwordModal].forEach((modal) => {
        modal.addEventListener('click', (e) => {
            // The backdrop is the modal element itself; a click that lands on
            // the container inside it is not a click-away.
            if (e.target === modal || e.target.closest('[data-close]')) {
                closeModal(modal);
            }
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        openModals().forEach(closeModal);
    });

    // --- Delete flow -------------------------------------------------------
    document.getElementById('deleteAccountBtn').addEventListener('click', () => {
        openModal(confirmModal, document.getElementById('confirmDeleteBtn'));
    });

    document.getElementById('confirmDeleteBtn').addEventListener('click', () => {
        confirmModal.classList.remove('active');
        clearFieldError(passwordInput);
        passwordInput.value = '';
        openModal(passwordModal, passwordInput);
    });

    // Same error shape as the rest of the site: `.input-error` on the control
    // and a `.field-error` note directly under it.
    function setFieldError(el, message) {
        clearFieldError(el);
        el.classList.add('input-error');
        const note = document.createElement('p');
        note.className = 'field-error';
        note.textContent = message;
        el.closest('.form-group').appendChild(note);
    }

    function clearFieldError(el) {
        el.classList.remove('input-error');
        const group = el.closest('.form-group');
        const note = group && group.querySelector('.field-error');
        if (note) note.remove();
    }

    passwordInput.addEventListener('input', () => clearFieldError(passwordInput));

    deleteForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const password = passwordInput.value;
        if (!password) {
            setFieldError(passwordInput, 'Enter your password to confirm.');
            passwordInput.focus();
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Deleting…';
        try {
            await window.api('/api/account', {
                method: 'DELETE',
                body: { password },
            });
            // The session is already cleared server-side. replace() rather
            // than href so Back cannot return to a settings page for an
            // account that no longer exists.
            location.replace('index.html?deleted=1');
        } catch (error) {
            // The server says which field is at fault when one is; anything
            // else (rate limiting, a server error) is not about the password
            // box and is shown as a general message instead.
            const field = error.data && error.data.field;
            if (field === 'password') {
                setFieldError(passwordInput, error.message);
                passwordInput.focus();
                passwordInput.select();
            } else {
                setFieldError(
                    passwordInput,
                    error.message || 'Something went wrong. Please try again.',
                );
            }
            submitBtn.disabled = false;
            submitBtn.textContent = 'Delete my account';
        }
    });

    // --- Change password ----------------------------------------------------
    // Local field-error helpers rather than the delete flow's setFieldError
    // above: that one creates a fresh <p class="field-error"> on every call,
    // which suits deletePassword (its form-group starts with none in the
    // HTML) but would leave a second, duplicate note behind the static
    // #currentPassword-error/etc. elements this form already carries.
    const passwordForm = document.getElementById('passwordForm');
    const currentPasswordInput = document.getElementById('currentPassword');
    const currentPasswordError = document.getElementById('currentPassword-error');
    const newPasswordInput = document.getElementById('newPassword');
    const newPasswordError = document.getElementById('newPassword-error');
    const confirmNewPasswordInput = document.getElementById('confirmNewPassword');
    const confirmNewPasswordError = document.getElementById('confirmNewPassword-error');
    const passwordStatus = document.getElementById('passwordStatus');
    const passwordSubmitBtn = document.getElementById('passwordSubmitBtn');

    function setPwFieldError(input, errorEl, message) {
        errorEl.textContent = message || '';
        input.classList.toggle('input-error', Boolean(message));
    }

    function clearPwFieldErrors() {
        setPwFieldError(currentPasswordInput, currentPasswordError, '');
        setPwFieldError(newPasswordInput, newPasswordError, '');
        setPwFieldError(confirmNewPasswordInput, confirmNewPasswordError, '');
        passwordStatus.hidden = true;
    }

    currentPasswordInput.addEventListener('input',
        () => setPwFieldError(currentPasswordInput, currentPasswordError, ''));
    confirmNewPasswordInput.addEventListener('input',
        () => setPwFieldError(confirmNewPasswordInput, confirmNewPasswordError, ''));

    // Same five checks app.py's password_problem() enforces server-side, in
    // the same order pplogin.js's signup checklist uses -- restated here, as
    // reset-password.js also does, rather than shared across the three pages
    // that each need it for one form.
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
    const STRENGTH_COLORS = ['#dc2626', '#d97706', '#65a30d', '#16a34a'];

    function passwordStrength(password, checks) {
        const satisfied = Object.values(checks).filter(Boolean).length;
        let score;
        if (satisfied <= 2) score = 1;
        else if (satisfied === 3) score = 2;
        else if (satisfied === 4) score = 3;
        else score = password.length >= 14 ? 4 : 3;
        return score;
    }

    const pwMeter = document.getElementById('pwMeter');
    const pwMeterFill = document.getElementById('pwMeterFill');
    const pwMeterLabel = document.getElementById('pwMeterLabel');
    const pwChecklist = document.getElementById('pwChecklist');

    function updatePasswordUI() {
        const password = newPasswordInput.value;
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
        pwMeterFill.style.width = `${(score / 4) * 100}%`;
        pwMeterFill.style.background = STRENGTH_COLORS[score - 1];
        pwMeterLabel.textContent = STRENGTH_LABELS[score - 1];
        pwMeterLabel.style.color = STRENGTH_COLORS[score - 1];
    }

    newPasswordInput.addEventListener('input', () => {
        updatePasswordUI();
        setPwFieldError(newPasswordInput, newPasswordError, '');
    });

    passwordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearPwFieldErrors();

        const currentPassword = currentPasswordInput.value;
        const newPassword = newPasswordInput.value;
        const confirmNewPassword = confirmNewPasswordInput.value;

        let firstInvalid = null;
        if (!currentPassword) {
            setPwFieldError(currentPasswordInput, currentPasswordError,
                'Enter your current password.');
            firstInvalid = currentPasswordInput;
        }
        const checks = passwordChecks(newPassword);
        if (!passwordIsAcceptable(checks)) {
            setPwFieldError(newPasswordInput, newPasswordError,
                'Password does not meet the requirements below.');
            firstInvalid = firstInvalid || newPasswordInput;
        } else if (newPassword !== confirmNewPassword) {
            setPwFieldError(confirmNewPasswordInput, confirmNewPasswordError,
                'Passwords do not match.');
            firstInvalid = firstInvalid || confirmNewPasswordInput;
        }

        if (firstInvalid) {
            firstInvalid.focus();
            return;
        }

        passwordSubmitBtn.disabled = true;
        passwordSubmitBtn.textContent = 'Updating…';

        try {
            await window.api('/api/account/password', {
                method: 'POST',
                body: { current_password: currentPassword, new_password: newPassword },
            });
            passwordForm.reset();
            // Clears the meter/checklist too -- reset() empties the field but
            // fires no 'input' event, so updatePasswordUI would not run.
            pwMeter.hidden = true;
            pwChecklist.hidden = true;
            passwordStatus.textContent = 'Password updated.';
            passwordStatus.className = 'setting-status ok';
            passwordStatus.hidden = false;
        } catch (error) {
            const field = error.data && error.data.field;
            if (field === 'current_password') {
                setPwFieldError(currentPasswordInput, currentPasswordError, error.message);
                currentPasswordInput.focus();
            } else if (field === 'new_password') {
                setPwFieldError(newPasswordInput, newPasswordError, error.message);
                newPasswordInput.focus();
            } else {
                // Rate limiting and anything unexpected: not about one field.
                passwordStatus.textContent =
                    error.message || 'Could not update your password. Please try again.';
                passwordStatus.className = 'setting-status error';
                passwordStatus.hidden = false;
            }
        } finally {
            passwordSubmitBtn.disabled = false;
            passwordSubmitBtn.textContent = 'Update password';
        }
    });
});
