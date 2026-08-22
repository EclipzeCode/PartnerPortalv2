// Invitations, from the dashboard.
//
// Its own file rather than more of ppdashboard.js, which is already the
// longest script here and is about what the dashboard reports. This is one
// dialog that writes rows, and it shares nothing with the rest of that page
// beyond sitting on it.
//
// The deliverable is a link, not an email. Two reasons: outbound mail is not
// a reliable channel here yet (see REQUIRE_EMAIL_VERIFICATION in app.py), and
// a link works in whatever the two organizations already use to talk to each
// other -- which for small nonprofits is as often a WhatsApp thread as an
// inbox.

document.addEventListener('DOMContentLoaded', () => {
    const openBtn = document.getElementById('inviteBtn');
    const modal = document.getElementById('inviteModal');
    if (!openBtn || !modal) return;

    const esc = window.escapeHtml;
    const form = document.getElementById('inviteForm');
    const nameInput = document.getElementById('inviteName');
    const nameError = document.getElementById('inviteName-error');
    const submitBtn = document.getElementById('inviteSubmitBtn');
    const result = document.getElementById('inviteResult');
    const linkInput = document.getElementById('inviteLink');
    const copyBtn = document.getElementById('inviteCopyBtn');
    const outstanding = document.getElementById('inviteOutstanding');
    const list = document.getElementById('inviteList');

    // The API returns a site-relative path, because the server does not
    // reliably know its own public URL (APP_BASE_URL is for email, and is
    // unset in development). The page does.
    const absolute = (path) => new URL(path, location.href).href;

    function setError(message) {
        nameError.textContent = message || '';
        nameInput.classList.toggle('input-error', Boolean(message));
        nameInput.setAttribute('aria-invalid', message ? 'true' : 'false');
    }

    function renderOutstanding(invites) {
        outstanding.hidden = invites.length === 0;
        list.innerHTML = invites.map((inv) => `
            <li>
                <div class="invite-row-main">
                    <span class="invite-row-name">${esc(inv.name)}</span>
                    <button type="button" class="invite-row-copy"
                            data-copy="${esc(absolute(inv.claim_url))}">
                        <i class='bx bx-copy'></i> Copy link
                    </button>
                </div>
                <button type="button" class="invite-row-revoke"
                        data-revoke="${esc(inv.id)}"
                        aria-label="Withdraw the invitation to ${esc(inv.name)}">
                    <i class='bx bx-trash'></i>
                </button>
            </li>`).join('');
    }

    async function loadOutstanding() {
        try {
            const data = await window.api('/api/invites');
            renderOutstanding(data.invites || []);
        } catch {
            // The dialog still works for creating one; the list is context,
            // not the function.
            outstanding.hidden = true;
        }
    }

    async function copy(text, button) {
        const idle = button.innerHTML;
        try {
            await navigator.clipboard.writeText(text);
            button.innerHTML = "<i class='bx bx-check'></i> Copied";
        } catch {
            // Clipboard refused (insecure context, or permission denied).
            // Selecting the text is the fallback that always works.
            if (linkInput) {
                linkInput.focus();
                linkInput.select();
            }
            button.innerHTML = "<i class='bx bx-error-circle'></i> Press Ctrl+C";
        }
        setTimeout(() => { button.innerHTML = idle; }, 2000);
    }

    openBtn.addEventListener('click', () => {
        setError('');
        result.hidden = true;
        form.reset();
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(modal, nameInput);
        loadOutstanding();
    });

    function close() {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
    }

    modal.querySelector('.close-modal').addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('active')) close();
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        setError('');

        const name = nameInput.value.trim();
        if (name.length < 2) {
            setError('Enter the name of the organization you are inviting.');
            nameInput.focus();
            return;
        }

        const idle = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = "<i class='bx bx-loader-alt'></i> Creating...";

        try {
            const data = await window.api('/api/invites', {
                method: 'POST', body: { name },
            });
            linkInput.value = absolute(data.invite.claim_url);
            result.hidden = false;
            form.reset();
            // Straight to the thing they came for.
            linkInput.focus();
            linkInput.select();
            loadOutstanding();
        } catch (error) {
            if (error.data && error.data.field === 'name') {
                setError(error.message);
            } else {
                window.toast(error.message || 'Could not create the invitation.',
                    'error');
            }
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = idle;
        }
    });

    copyBtn.addEventListener('click', () => copy(linkInput.value, copyBtn));

    list.addEventListener('click', async (e) => {
        const copyTarget = e.target.closest('[data-copy]');
        if (copyTarget) {
            copy(copyTarget.dataset.copy, copyTarget);
            return;
        }

        const revoke = e.target.closest('[data-revoke]');
        if (!revoke) return;
        revoke.disabled = true;
        try {
            await window.api(`/api/invites/${encodeURIComponent(revoke.dataset.revoke)}`,
                { method: 'DELETE' });
            window.toast('Invitation withdrawn. That link no longer works.');
            loadOutstanding();
        } catch (error) {
            revoke.disabled = false;
            window.toast(error.message || 'Could not withdraw that invitation.',
                'error');
        }
    });
});
