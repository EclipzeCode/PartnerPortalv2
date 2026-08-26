// The admin panel.
//
// Two queues and two powers, and both powers are reversible. Nothing here can
// suspend an account, edit a profile, act as somebody, or delete anything.
//
// The page ships holding a login form and nothing else. Everything drawn
// below arrives from /api/admin/overview, which answers 404 without an admin
// session -- so a stranger who finds this URL sees a sign-in box and cannot
// learn from the app whether there is anything behind it.

document.addEventListener('DOMContentLoaded', async () => {
    const esc = window.escapeHtml;

    const gate = document.getElementById('adminGate');
    const panel = document.getElementById('adminPanel');
    const loginForm = document.getElementById('adminLoginForm');
    const loginError = document.getElementById('adminLoginError');
    const loginBtn = document.getElementById('adminLoginBtn');

    const hideModal = document.getElementById('hideModal');
    const hideWho = document.getElementById('hideWho');
    const hideReason = document.getElementById('hideReason');
    const hideError = document.getElementById('hideError');

    let pendingHideId = null;

    // --- Requests ---------------------------------------------------------
    // allowUnauthenticated everywhere: these routes answer 404 rather than
    // 401, so common.js's sign-in redirect would never fire anyway -- but
    // saying so keeps this page from ever bouncing an admin to the
    // organization login, which is a different account entirely.
    const call = (path, options = {}) =>
        window.api(path, { allowUnauthenticated: true, ...options });

    function showError(el, message) {
        el.textContent = message;
        el.hidden = !message;
    }

    // --- Rendering --------------------------------------------------------

    function when(iso) {
        if (!iso) return '';
        const at = new Date(iso);
        if (Number.isNaN(at.getTime())) return '';
        return at.toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: 'numeric', minute: '2-digit',
        });
    }

    function empty(message) {
        return `<p class="admin-empty">${esc(message)}</p>`;
    }

    function messageRow(m) {
        return `
            <article class="admin-row">
              <div class="admin-row-main">
                <p class="admin-row-title">
                  ${esc(m.name)}
                  <a href="mailto:${esc(m.email)}">${esc(m.email)}</a>
                  ${m.phone ? `<span class="admin-dim">${esc(m.phone)}</span>` : ''}
                </p>
                <p class="admin-row-body">${esc(m.message)}</p>
                <p class="admin-dim">${esc(when(m.created_at))}</p>
              </div>
              <div class="admin-row-actions">
                <button type="button" class="btn-ghost"
                        data-handle="${m.id}">Mark handled</button>
              </div>
            </article>`;
    }

    function orgRow(org, kind) {
        const meta = [org.organization_type, org.location]
            .filter(Boolean).map(esc).join(' &middot; ');
        // The profile link is the point of the row: you cannot judge a name
        // without seeing what it is attached to. It opens the public profile,
        // which for a hidden organization now 404s -- so hidden rows link to
        // nothing and say so instead of offering a dead link.
        const link = org.hidden_at
            ? '<span class="admin-dim">profile not listed</span>'
            : `<a href="organization.html?id=${encodeURIComponent(org.id)}"
                  target="_blank" rel="noopener">Open profile</a>`;

        const actions = kind === 'flagged'
            ? `<button type="button" class="btn-ghost" data-clear="${org.id}">Name is fine</button>
               <button type="button" class="btn-danger" data-hide="${org.id}"
                       data-name="${esc(org.name)}">Hide</button>`
            : `<button type="button" class="btn-ghost" data-unhide="${org.id}">List again</button>`;

        return `
            <article class="admin-row">
              <div class="admin-row-main">
                <p class="admin-row-title">
                  ${esc(org.name)}
                  ${org.is_demo ? '<span class="admin-tag">example</span>' : ''}
                </p>
                ${meta ? `<p class="admin-dim">${meta}</p>` : ''}
                ${org.description
                    ? `<p class="admin-row-body">${esc(org.description)}</p>` : ''}
                ${org.hidden_reason
                    ? `<p class="admin-reason">Told: ${esc(org.hidden_reason)}</p>` : ''}
                <p class="admin-dim">
                  ${esc(org.email)} &middot;
                  ${esc(org.hidden_at ? `hidden ${when(org.hidden_at)}`
                                      : `joined ${when(org.created_at)}`)}
                  &middot; ${link}
                </p>
              </div>
              <div class="admin-row-actions">${actions}</div>
            </article>`;
    }

    function actionRow(a) {
        const detail = Object.entries(a.detail || {})
            .filter(([, v]) => v !== null && v !== '')
            .map(([k, v]) => `${esc(k)}: ${esc(String(v))}`)
            .join(' · ');
        return `
            <p class="admin-action">
              <code>${esc(a.action)}</code>
              <span class="admin-dim">${esc(a.admin_email)}</span>
              ${detail ? `<span class="admin-dim">${detail}</span>` : ''}
              <span class="admin-dim">${esc(when(a.created_at))}</span>
            </p>`;
    }

    function render(data) {
        document.getElementById('adminWho').textContent =
            `${data.admin.name} (${data.admin.email})`;

        const c = data.counts;
        document.getElementById('adminCounts').innerHTML = [
            ['Messages waiting', c.contact_messages],
            ['Names flagged', c.flagged],
            ['Hidden', c.hidden],
        ].map(([label, n]) => `
            <div class="admin-count${n ? ' has' : ''}">
              <span class="admin-count-n">${n}</span>
              <span class="admin-count-label">${esc(label)}</span>
            </div>`).join('');

        document.getElementById('adminMessages').innerHTML =
            data.contact_messages.length
                ? data.contact_messages.map(messageRow).join('')
                : empty('Nothing waiting.');

        document.getElementById('adminFlagged').innerHTML =
            data.flagged.length
                ? data.flagged.map((o) => orgRow(o, 'flagged')).join('')
                : empty('No names are flagged.');

        document.getElementById('adminHidden').innerHTML =
            data.hidden.length
                ? data.hidden.map((o) => orgRow(o, 'hidden')).join('')
                : empty('Nothing is hidden.');

        document.getElementById('adminActions').innerHTML =
            data.actions.length
                ? data.actions.map(actionRow).join('')
                : empty('Nothing has been done yet.');
    }

    // --- Loading ----------------------------------------------------------

    async function load() {
        let data;
        try {
            data = await call('/api/admin/overview');
        } catch (error) {
            // 404 is "not an admin", which is the signed-out state as far as
            // this page is concerned. Anything else is a real failure and
            // should not be disguised as one.
            if (error.status === 404) {
                gate.hidden = false;
                panel.hidden = true;
                return false;
            }
            gate.hidden = false;
            panel.hidden = true;
            showError(loginError,
                error.message || 'Could not reach the server.');
            return false;
        }
        gate.hidden = true;
        panel.hidden = false;
        render(data);
        return true;
    }

    // --- Sign in and out --------------------------------------------------

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        showError(loginError, '');
        loginBtn.disabled = true;
        try {
            await call('/api/admin/login', {
                method: 'POST',
                body: {
                    email: document.getElementById('adminEmail').value.trim(),
                    password: document.getElementById('adminPassword').value,
                },
            });
            document.getElementById('adminPassword').value = '';
            await load();
        } catch (error) {
            showError(loginError, error.message || 'Could not sign in.');
        } finally {
            loginBtn.disabled = false;
        }
    });

    document.getElementById('adminSignOut').addEventListener('click', async () => {
        await call('/api/admin/logout', { method: 'POST' });
        // Signing out of the admin surface deliberately leaves any
        // organization session alone, so this reloads the panel rather than
        // navigating anywhere.
        panel.hidden = true;
        gate.hidden = false;
    });

    // --- Actions ----------------------------------------------------------
    // One delegated listener rather than one per button: every row is
    // replaced on each reload, so per-button handlers would have to be rewired
    // every time and a missed rewire is a button that silently does nothing.

    async function act(fn) {
        try {
            await fn();
            await load();
        } catch (error) {
            window.toast(error.message || 'That did not work.', 'error');
        }
    }

    panel.addEventListener('click', (e) => {
        const handle = e.target.closest('[data-handle]');
        if (handle) {
            return act(() => call(
                `/api/admin/contact-messages/${handle.dataset.handle}/handled`,
                { method: 'POST', body: { handled: true } }));
        }

        const clear = e.target.closest('[data-clear]');
        if (clear) {
            return act(() => call(
                `/api/admin/organizations/${clear.dataset.clear}/flag`,
                { method: 'DELETE' }));
        }

        const unhide = e.target.closest('[data-unhide]');
        if (unhide) {
            return act(() => call(
                `/api/admin/organizations/${unhide.dataset.unhide}/hidden`,
                { method: 'POST', body: { hidden: false } }));
        }

        const hide = e.target.closest('[data-hide]');
        if (hide) {
            pendingHideId = hide.dataset.hide;
            // From the button rather than scraped out of the row: the title
            // also carries the "example" tag, and the dialog was naming the
            // organization "Coders Over Borders example".
            hideWho.textContent = hide.dataset.name;
            hideReason.value = '';
            showError(hideError, '');
            hideModal.hidden = false;
            hideModal.classList.add('active');
            window.dialogOpened(hideModal, hideReason);
        }
    });

    function closeHide() {
        hideModal.classList.remove('active');
        hideModal.hidden = true;
        window.dialogClosed(hideModal);
        pendingHideId = null;
    }

    document.getElementById('hideCancel').addEventListener('click', closeHide);

    document.getElementById('hideConfirm').addEventListener('click', async () => {
        const reason = hideReason.value.trim();
        if (!reason) {
            // The server refuses this too. Saying it here saves a round trip
            // for the mistake somebody is most likely to make.
            showError(hideError, 'Give a reason. It is emailed to them.');
            return;
        }
        try {
            await call(`/api/admin/organizations/${pendingHideId}/hidden`, {
                method: 'POST',
                body: { hidden: true, reason },
            });
            closeHide();
            await load();
        } catch (error) {
            showError(hideError, error.message || 'That did not work.');
        }
    });

    await load();
});
