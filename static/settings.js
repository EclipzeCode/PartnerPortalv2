// Account settings.
//
// Two independent pieces: a preference that saves the moment it is toggled,
// and a deletion flow that deliberately takes three deliberate actions to
// complete (open, confirm, then re-enter the password).

document.addEventListener('DOMContentLoaded', async () => {
    const toggles = [...document.querySelectorAll(
        '.setting-row input[type="checkbox"][data-category]')];
    // What each switch is called in the line confirming it saved.
    const LABELS = {
        proposals: 'Proposal emails are',
        messages: 'Message emails are',
        partnerships: 'Partnership update emails are',
    };
    const status = document.getElementById('settingStatus');
    const container = document.querySelector('.settings-container');

    // --- Appearance -------------------------------------------------------
    // Stored in this browser, not on the account: it describes a screen
    // rather than an organization, and the same person on a laptop and a
    // phone may reasonably want different answers. That also means it needs
    // no request, which is why it is wired before the await below and is
    // never disabled -- it works while the rest of the page is still loading,
    // and it works signed out.
    //
    // The attribute itself is set twice: here, and by the inline script in
    // every page's <head>, which runs before the first stylesheet so a dark
    // visitor never sees a white flash. This half only has to keep the two in
    // step from the moment the control is used.
    //
    // The head script also watches prefers-color-scheme and re-applies while
    // nothing is stored, so choosing System here hands the page back to it
    // without either needing to know about the other.
    const THEME_KEY = 'partnerPortalTheme';
    const themeChoice = document.getElementById('themeChoice');

    if (themeChoice) {
        // Three states stored as two values: 'dark', 'light', or the key
        // absent. Absent means "follow the device" rather than a third
        // string, so a browser that has never touched this setting and one
        // that chose System are the same state -- there is no way for the
        // stored value and the default to drift apart, and nothing to
        // migrate for anyone who set a theme before System existed.
        const stored = (() => {
            try {
                const v = localStorage.getItem(THEME_KEY);
                return v === 'dark' || v === 'light' ? v : null;
            } catch { return null; }
        })();

        const selected = themeChoice.querySelector(
            `input[value="${stored || 'system'}"]`);
        if (selected) selected.checked = true;

        themeChoice.addEventListener('change', (event) => {
            const choice = event.target.value;
            // What the head script does, done again here so the page changes
            // under the pointer rather than on the next navigation. System
            // resolves through the same query the head script reads.
            const dark = choice === 'dark' || (choice === 'system'
                && window.matchMedia
                && window.matchMedia('(prefers-color-scheme: dark)').matches);
            document.documentElement.setAttribute('data-theme',
                dark ? 'dark' : 'light');
            try {
                if (choice === 'system') localStorage.removeItem(THEME_KEY);
                else localStorage.setItem(THEME_KEY, choice);
            } catch {
                // Private browsing, or storage disabled. The theme still
                // applies for this page; it just will not be remembered.
                window.toast('That applies for now, but this browser will '
                             + 'not remember it.', 'error');
            }
        });
    }

    // --- Load ------------------------------------------------------------
    // The switches and the account facts below all come from this request, so
    // they shimmer (settings.css, [data-loading="true"]) until it settles --
    // otherwise they show "off" and "—" first, which read as real answers
    // rather than "not loaded yet".
    let me;
    let verificationRequired = false;
    try {
        const data = await window.api('/api/me');
        me = data.organization;
        verificationRequired = Boolean(data.verification_required);
    } catch (error) {
        console.error('Could not load settings:', error);
        container.removeAttribute('data-loading');
        // Left disabled: without the current values there is nothing
        // truthful to draw, and an enabled switch showing a guess is worse
        // than one that cannot be moved.
        return; // api() redirects on 401; anything else leaves the page as-is
    }

    container.removeAttribute('data-loading');
    // Resolved by the server -- an absent key in the stored object means
    // "yes", and the settings page is not the place for a second copy of
    // that rule. See Organization.wants_email.
    const prefs = me.email_preferences || {};
    toggles.forEach((box) => {
        box.checked = prefs[box.dataset.category] !== false;
        box.disabled = false;
    });

    document.getElementById('accountEmailValue').textContent = me.email || '—';
    document.getElementById('verifiedValue').innerHTML = me.email_verified
        ? '<span class="pill ok"><i class=\'bx bx-check\'></i> Verified</span>'
        : '<span class="pill warn"><i class=\'bx bx-time\'></i> Not verified</span>';
    document.getElementById('profileValue').textContent = me.onboarding_complete
        ? 'Complete'
        : 'Not finished';

    const publicLink = document.getElementById('viewPublicProfile');
    publicLink.href = `organization.html?id=${encodeURIComponent(me.id)}`;

    // --- Changing the sign-in email ----------------------------------------
    // Nothing moves here. The request holds the new address on the account
    // and sends it a link; the change lands when that link is opened. An
    // address cannot be checked by looking at it, and applying a typo
    // straight away locks somebody out of the account the change was for.
    const pendingBlock = document.getElementById('pendingEmailBlock');
    const emailForm = document.getElementById('emailForm');
    const emailStatus = document.getElementById('emailStatus');
    const emailSubmitBtn = document.getElementById('emailSubmitBtn');
    const newEmail = document.getElementById('newEmail');
    const emailPassword = document.getElementById('emailPassword');

    function paintPendingEmail(pending) {
        if (!pendingBlock) return;
        pendingBlock.hidden = !pending;
        if (pending) {
            document.getElementById('pendingEmailValue').textContent = pending;
        }
    }

    function setEmailFieldError(id, message) {
        const field = document.getElementById(id);
        const note = document.getElementById(`${id}-error`);
        if (field) field.classList.toggle('input-error', Boolean(message));
        if (field) field.setAttribute('aria-invalid', message ? 'true' : 'false');
        if (note) note.textContent = message || '';
    }

    function clearEmailErrors() {
        ['newEmail', 'emailPassword'].forEach((id) => setEmailFieldError(id, ''));
        if (emailStatus) emailStatus.hidden = true;
    }

    paintPendingEmail(me.pending_email);

    if (emailForm) {
        emailForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            clearEmailErrors();

            const address = newEmail.value.trim();
            if (!address) {
                setEmailFieldError('newEmail', 'Enter the new email address.');
                newEmail.focus();
                return;
            }
            if (!emailPassword.value) {
                setEmailFieldError('emailPassword', 'Enter your password.');
                emailPassword.focus();
                return;
            }

            emailSubmitBtn.disabled = true;
            emailSubmitBtn.textContent = 'Sending...';
            try {
                const result = await window.api('/api/account/email', {
                    method: 'POST',
                    body: { email: address, password: emailPassword.value },
                });
                paintPendingEmail(result.pending_email);
                emailForm.reset();
                document.getElementById('emailChange').open = false;
                window.toast(`Check ${result.pending_email} for the `
                    + 'confirmation link.');
            } catch (error) {
                // The endpoint names the field it rejected, so the message
                // lands on the input rather than at the top of the form.
                const field = error.data && error.data.field;
                if (field === 'email') setEmailFieldError('newEmail', error.message);
                else if (field === 'password') {
                    setEmailFieldError('emailPassword', error.message);
                } else {
                    emailStatus.textContent = error.message;
                    emailStatus.className = 'setting-status error';
                    emailStatus.hidden = false;
                }
            } finally {
                emailSubmitBtn.disabled = false;
                emailSubmitBtn.textContent = 'Send confirmation link';
            }
        });
    }

    const cancelEmailBtn = document.getElementById('cancelEmailBtn');
    if (cancelEmailBtn) {
        cancelEmailBtn.addEventListener('click', async () => {
            cancelEmailBtn.disabled = true;
            try {
                await window.api('/api/account/email', { method: 'DELETE' });
                paintPendingEmail(null);
                window.toast('Email change canceled.');
            } catch (error) {
                window.toast(error.message || 'Could not cancel that.', 'error');
            } finally {
                cancelEmailBtn.disabled = false;
            }
        });
    }

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

    // One handler for all three switches, keyed off the category in the
    // markup. A listener per switch would be three copies of the same
    // in-flight-and-revert dance, which is three chances for one of them to
    // get it slightly different.
    toggles.forEach((box) => {
        box.addEventListener('change', async () => {
            const category = box.dataset.category;
            const wanted = box.checked;
            // Disabled while in flight so a fast double-toggle cannot leave
            // the switch showing the result of the request that happened to
            // land second rather than the one clicked last.
            box.disabled = true;
            try {
                // Only the category that moved. The endpoint treats a
                // missing key as "not this one", so sending all three would
                // mean a stale switch elsewhere on the page could overwrite
                // a change made in another tab.
                await window.api('/api/settings', {
                    method: 'PATCH',
                    body: { email_preferences: { [category]: wanted } },
                });
                showStatus(
                    `${LABELS[category]} ${wanted ? 'on' : 'off'}.`, 'ok');
            } catch (error) {
                // Put the switch back where it was: it should never show a
                // state the server did not accept.
                box.checked = !wanted;
                showStatus(
                    error.message || 'Could not save that. Please try again.',
                    'error',
                );
            } finally {
                box.disabled = false;
            }
        });
    });

    // --- Search indexing ---------------------------------------------------
    const searchable = document.getElementById('searchableToggle');
    const searchableStatus = document.getElementById('searchableStatus');
    if (searchable) {
        searchable.checked = Boolean(me.searchable);
        searchable.disabled = false;
        searchable.addEventListener('change', async () => {
            const wanted = searchable.checked;
            searchable.disabled = true;
            try {
                await window.api('/api/settings', {
                    method: 'PATCH', body: { searchable: wanted },
                });
                searchableStatus.textContent = wanted
                    ? 'Search engines may now list your profile. It can take '
                      + 'them a while to notice.'
                    : 'Your profile asks search engines not to list it. Copies '
                      + 'they already hold fade on their own schedule.';
                searchableStatus.className = 'setting-status ok';
                searchableStatus.hidden = false;
            } catch (error) {
                searchable.checked = !wanted;
                searchableStatus.textContent =
                    error.message || 'Could not save that. Please try again.';
                searchableStatus.className = 'setting-status error';
                searchableStatus.hidden = false;
            } finally {
                searchable.disabled = false;
            }
        });
    }

    // --- Blocked organizations ---------------------------------------------
    const blockedList = document.getElementById('blockedList');

    function paintBlocked(blocks) {
        if (!blockedList) return;
        if (!blocks.length) {
            blockedList.innerHTML =
                '<li class="blocked-empty">You have not blocked anyone.</li>';
            return;
        }
        const esc = window.escapeHtml;
        blockedList.innerHTML = blocks.map((b) => `
            <li class="blocked-row">
                <div>
                    <strong>${esc(b.name || 'An organization')}</strong>
                    <p>${esc([b.organization_type, b.location]
                        .filter(Boolean).join(' · '))}</p>
                </div>
                <button type="button" class="btn-ghost" data-unblock="${b.organization_id}">
                    Unblock
                </button>
            </li>`).join('');
    }

    if (blockedList) {
        window.api('/api/blocks').then((data) => {
            paintBlocked(data.blocks || []);
        }).catch((error) => {
            blockedList.innerHTML = `<li class="blocked-empty">${
                window.escapeHtml(error.message || 'Could not load these.')}</li>`;
        });

        blockedList.addEventListener('click', async (e) => {
            const btn = e.target.closest('button[data-unblock]');
            if (!btn) return;
            btn.disabled = true;
            try {
                await window.api(`/api/blocks/${encodeURIComponent(btn.dataset.unblock)}`,
                                 { method: 'DELETE' });
                const data = await window.api('/api/blocks');
                paintBlocked(data.blocks || []);
                window.toast('Unblocked. They can propose to you again.');
            } catch (error) {
                btn.disabled = false;
                window.toast(error.message || 'Could not unblock them.', 'error');
            }
        });
    }

    // --- Other sessions ----------------------------------------------------
    const endSessionsBtn = document.getElementById('endSessionsBtn');
    const sessionsStatus = document.getElementById('sessionsStatus');
    if (endSessionsBtn) {
        endSessionsBtn.addEventListener('click', async () => {
            endSessionsBtn.disabled = true;
            try {
                const result = await window.api('/api/account/sessions/others',
                                                { method: 'DELETE' });
                sessionsStatus.textContent = result.message
                    || 'Signed out everywhere else.';
                sessionsStatus.className = 'setting-status ok';
            } catch (error) {
                sessionsStatus.textContent =
                    error.message || 'Could not do that. Please try again.';
                sessionsStatus.className = 'setting-status error';
            } finally {
                sessionsStatus.hidden = false;
                endSessionsBtn.disabled = false;
            }
        });
    }

    // --- Modals ------------------------------------------------------------
    const confirmModal = document.getElementById('confirmDeleteModal');
    const passwordModal = document.getElementById('passwordDeleteModal');
    const deleteForm = document.getElementById('deleteForm');
    const passwordInput = document.getElementById('deletePassword');
    const submitBtn = document.getElementById('deleteSubmitBtn');

    document.getElementById('deleteEmailLabel').textContent = me.email || '';

    // Focus is common.js's dialogOpened/dialogClosed. The focusTarget.focus()
    // that used to be here never actually moved focus: .modal is
    // `visibility: hidden` under a transition, so nothing inside it can take
    // focus in the tick the class lands. The helper retries until it can, and
    // traps Tab inside the dialog meanwhile.
    function openModal(modal, focusTarget) {
        window.showDialog(modal, focusTarget);
    }

    function closeModal(modal) {
        window.hideDialog(modal);
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
        // closeModal, not a bare classList.remove: hiding the first step
        // directly left its focus trap installed, so both dialogs were
        // trapping Tab at once, and the second step then recorded a button
        // inside a hidden dialog as the control to return to -- which cannot
        // take focus, stranding it. Closing properly hands focus back to
        // "Delete my account" first, which is what the second step should
        // return to when it is dismissed.
        closeModal(confirmModal);
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
            // ?deleted=1 was landing on a home page that did nothing with
            // it, so the account vanished without a word. The toast is
            // queued for that page instead; the parameter stays because it
            // is what makes the redirect legible in history and logs.
            window.toastAfterRedirect('Your account has been deleted.');
            // Otherwise the home page draws an avatar placeholder for an
            // account that no longer exists, until /api/me 401s and clears
            // the hint itself.
            window.forgetSession();
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

    // The checks, the score and the meter painter are password-field.js's,
    // shared with the sign-up, claim and reset forms. The painter is kept so
    // it can be run again after reset() empties the field, which fires no
    // 'input' event.
    const paintPasswordMeter = window.wirePasswordMeter(newPasswordInput);

    newPasswordInput.addEventListener('input',
        () => setPwFieldError(newPasswordInput, newPasswordError, ''));

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
        if (!window.passwordAcceptable(newPassword)) {
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
            const result = await window.api('/api/account/password', {
                method: 'POST',
                body: { current_password: currentPassword, new_password: newPassword },
            });
            passwordForm.reset();
            paintPasswordMeter();   // reset() fires no 'input' event
            // The server signs every other device out when the password
            // changes (see _end_other_sessions), which is the thing somebody
            // changing a password after a scare most wants to know happened.
            passwordStatus.textContent = result && result.other_sessions_ended
                ? 'Password updated. Every other device was signed out; this one stays in.'
                : 'Password updated.';
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
