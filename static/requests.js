// The requests board.
//
// Public, like the directory: /api/requests answers without a session and a
// request carries no contact details. Signed in, the same list comes back
// with the viewer's own requests marked and the ones they could answer from
// their profile first.
//
// Answering does not happen here. It opens the proposal form on the matches
// page with the request attached (ppsearch.html?org=&propose=1&request=), so
// the terms, counters and messages are the ones every partnership uses.

document.addEventListener('DOMContentLoaded', async () => {
    const esc = window.escapeHtml;

    const grid = document.getElementById('reqGrid');
    const countLine = document.getElementById('reqCount');
    const pager = document.getElementById('reqPager');
    const pageIndicator = document.getElementById('reqPageIndicator');
    const prevBtn = document.getElementById('reqPrev');
    const nextBtn = document.getElementById('reqNext');
    const focusBox = document.getElementById('reqFocus');
    const controls = document.getElementById('reqControls');
    const categorySelect = document.getElementById('reqCategory');
    const remoteBox = document.getElementById('reqRemote');
    const postBtn = document.getElementById('reqPostBtn');

    const modal = document.getElementById('reqModal');
    const form = document.getElementById('reqForm');
    const formMessage = document.getElementById('reqFormMessage');
    const postCategory = document.getElementById('reqPostCategory');
    const unitSelect = document.getElementById('reqUnit');
    const unitDetailGroup = document.getElementById('reqUnitDetailGroup');
    const profileHint = document.getElementById('reqProfileHint');

    controls.addEventListener('submit', (e) => e.preventDefault());

    const state = { page: 1, pages: 1, signedIn: false };
    let me = null;
    let labels = {};
    let units = [];
    let defaultUnits = {};
    let generation = 0;

    // --- Vocabulary ---------------------------------------------------------

    try {
        const cats = await window.api('/api/categories');
        const groups = cats.groups.map((g) => `
            <optgroup label="${esc(g.name)}">
                ${g.categories.map((c) => {
                    labels[c.slug] = c.label;
                    return `<option value="${esc(c.slug)}">${esc(c.label)}</option>`;
                }).join('')}
            </optgroup>`).join('');
        categorySelect.insertAdjacentHTML('beforeend', groups);
        postCategory.innerHTML = '<option value="">Choose a category</option>' + groups;
        units = cats.units || [];
        defaultUnits = cats.default_units || {};
    } catch (error) {
        window.toast(error.message || 'Could not load categories.', 'error');
    }

    // --- The URL ------------------------------------------------------------

    function readUrl() {
        const params = new URLSearchParams(location.search);
        const kind = params.get('kind') || '';
        const box = controls.querySelector(`input[name="kind"][value="${CSS.escape(kind)}"]`);
        if (box) box.checked = true;
        categorySelect.value = params.get('category') || '';
        remoteBox.checked = params.get('remote') === '1';
        const page = parseInt(params.get('page'), 10);
        state.page = page > 1 ? page : 1;
        const id = parseInt(params.get('id'), 10);
        return id > 0 ? id : null;
    }

    function filters() {
        return {
            kind: controls.querySelector('input[name="kind"]:checked').value,
            category: categorySelect.value,
            remote: remoteBox.checked ? '1' : '',
        };
    }

    function writeUrl(focusId) {
        const params = new URLSearchParams();
        Object.entries(filters()).forEach(([k, v]) => { if (v) params.set(k, v); });
        if (state.page > 1) params.set('page', String(state.page));
        if (focusId) params.set('id', String(focusId));
        const query = params.toString();
        history.replaceState(null, '', location.pathname + (query ? `?${query}` : ''));
    }

    // --- Cards --------------------------------------------------------------

    function dateLine(req) {
        const when = new Date(`${req.expires_on}T00:00:00`).toLocaleDateString(
            'en-US', { month: 'short', day: 'numeric' });
        return req.needed_by ? `Needed by ${when}` : `Open until ${when}`;
    }

    function respondHref(req) {
        const target = `ppsearch.html?org=${encodeURIComponent(req.organization.id)}`
            + `&propose=1&request=${encodeURIComponent(req.id)}`;
        return state.signedIn ? target
            : `pplogin.html?next=${encodeURIComponent(target)}`;
    }

    function actions(req) {
        if (req.status !== 'open') {
            return `<span class="req-closed">${esc(
                req.status === 'filled' ? 'Filled' : req.status === 'expired'
                    ? 'Expired' : 'Closed')}</span>`;
        }
        if (req.mine) {
            return `
                <button type="button" class="btn-secondary" data-close="${req.id}" data-as="filled">
                    <i class='bx bx-check' aria-hidden="true"></i> Mark filled
                </button>
                <button type="button" class="btn-ghost" data-close="${req.id}" data-as="closed">Close</button>`;
        }
        const label = req.kind === 'need' ? 'I can help' : 'Request this';
        return `<a class="btn-primary" href="${esc(respondHref(req))}">${
            state.signedIn ? label : 'Sign in to respond'}
            <i class='bx bx-right-arrow-alt' aria-hidden="true"></i></a>`;
    }

    function card(req, { focused = false } = {}) {
        const org = req.organization || {};
        const meta = [org.organization_type, org.location].filter(Boolean)
            .map(esc).join(' &middot; ');
        const amount = req.quantity_label ? ` &middot; ${esc(req.quantity_label)}` : '';
        const responses = req.response_count
            ? `<span><i class='bx bx-message-dots' aria-hidden="true"></i> ${
                req.response_count} ${req.response_count === 1 ? 'response' : 'responses'}</span>`
            : '';
        const who = (req.responses || []).length ? `
            <ul class="req-responses">
                ${req.responses.map((r) => `
                    <li>
                        <a href="ppdashboard.html#incoming">${esc(r.organization || 'An organization')}</a>
                        <span class="req-response-status">${esc(r.status)}</span>
                    </li>`).join('')}
            </ul>` : '';
        return `
            <article class="dir-card req-card${focused ? ' focused' : ''}${req.fits ? ' fits' : ''}"
                     data-id="${req.id}">
                <div class="req-top">
                    <span class="req-kind-tag ${req.kind}">${req.kind === 'need' ? 'Needs' : 'Offering'}</span>
                    <span class="req-category">${esc(req.category_label)}${amount}</span>
                </div>
                <h2 class="dir-name req-title">${esc(req.title)}</h2>
                <p class="dir-meta">
                    <a href="organization.html?id=${encodeURIComponent(org.id)}">${esc(org.name || '')}</a>${
                        meta ? ` &middot; ${meta}` : ''}
                </p>
                ${req.details ? `<p class="dir-bio${focused ? ' full' : ''}">${esc(req.details)}</p>` : ''}
                <p class="req-facts">
                    ${req.fits ? `<span class="req-fit"><i class='bx bx-check-circle' aria-hidden="true"></i> Fits your profile</span>` : ''}
                    ${req.mine ? '<span class="req-fit mine">Your request</span>' : ''}
                    <span><i class='bx bx-calendar' aria-hidden="true"></i> ${esc(dateLine(req))}</span>
                    ${req.remote_ok ? `<span><i class='bx bx-globe' aria-hidden="true"></i> Remote OK</span>` : ''}
                    ${responses}
                </p>
                ${who}
                <div class="req-card-actions">${actions(req)}</div>
            </article>`;
    }

    function skeletons() {
        grid.innerHTML = Array.from({ length: 6 }, () => `
            <div class="dir-card" aria-hidden="true">
                <div class="skeleton skeleton-line short"></div>
                <div class="skeleton skeleton-line"></div>
                <div class="skeleton skeleton-line"></div>
            </div>`).join('');
    }

    function emptyState() {
        const f = filters();
        const filtered = f.kind || f.category || f.remote;
        grid.innerHTML = `
            <div class="dir-empty">
                <i class='bx bx-notepad' aria-hidden="true"></i>
                <p>${filtered ? 'No open requests match those filters.'
                    : 'No open requests yet. Be the first to post one.'}</p>
            </div>`;
    }

    // --- Loading ------------------------------------------------------------

    async function load() {
        const mine = ++generation;
        grid.setAttribute('aria-busy', 'true');
        skeletons();
        const params = new URLSearchParams();
        Object.entries(filters()).forEach(([k, v]) => { if (v) params.set(k, v); });
        params.set('page', String(state.page));
        try {
            const data = await window.api(`/api/requests?${params}`);
            if (mine !== generation) return;
            state.signedIn = data.signed_in;
            state.pages = data.pages;
            if (data.page > data.pages && data.pages >= 1 && state.page !== data.pages) {
                state.page = data.pages;
                load();
                return;
            }
            countLine.textContent = data.total === 1
                ? '1 open request' : `${data.total} open requests`;
            if (!data.requests.length) emptyState();
            else grid.innerHTML = data.requests.map((r) => card(r)).join('');
            pager.hidden = data.pages <= 1;
            pageIndicator.textContent = `Page ${data.page} of ${data.pages}`;
            prevBtn.disabled = data.page <= 1;
            nextBtn.disabled = data.page >= data.pages;
        } catch (error) {
            if (mine !== generation) return;
            grid.innerHTML = `<div class="dir-empty"><p>${esc(
                error.message || 'Could not load requests.')}</p></div>`;
        } finally {
            if (mine === generation) grid.setAttribute('aria-busy', 'false');
        }
    }

    async function showFocus(id) {
        try {
            const data = await window.api(`/api/requests/${encodeURIComponent(id)}`,
                { allowUnauthenticated: true });
            focusBox.innerHTML = card(data.request, { focused: true });
            focusBox.hidden = false;
            focusBox.scrollIntoView({ block: 'start' });
        } catch (error) {
            focusBox.innerHTML = `<p class="dir-empty">${esc(
                error.message || 'That request is not on the board.')}</p>`;
            focusBox.hidden = false;
        }
    }

    function refilter() {
        state.page = 1;
        focusBox.hidden = true;
        writeUrl();
        load();
    }

    controls.addEventListener('change', refilter);
    prevBtn.addEventListener('click', () => { state.page -= 1; writeUrl(); load(); });
    nextBtn.addEventListener('click', () => { state.page += 1; writeUrl(); load(); });

    // Mark filled / close, from a card or the focused request.
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-close]');
        if (!btn) return;
        const filled = btn.dataset.as === 'filled';
        const ok = await window.confirmDialog({
            title: filled ? 'Mark this request filled?' : 'Close this request?',
            body: 'It comes off the board. Proposals already sent are not affected.',
            confirmLabel: filled ? 'Mark filled' : 'Close request',
        });
        if (!ok) return;
        try {
            await window.api(`/api/requests/${btn.dataset.close}/close`, {
                method: 'POST', body: { status: btn.dataset.as },
            });
            window.toast(filled ? 'Marked filled.' : 'Request closed.');
            if (!focusBox.hidden) showFocus(btn.dataset.close);
            load();
        } catch (error) {
            window.toast(error.message || 'Could not update that request.', 'error');
        }
    });

    // --- Posting ------------------------------------------------------------

    function setMessage(text) {
        formMessage.textContent = text;
        formMessage.classList.toggle('hidden', !text);
    }

    function postKind() {
        return form.querySelector('input[name="postKind"]:checked').value;
    }

    function paintUnits() {
        const chosen = defaultUnits[postCategory.value] || unitSelect.value;
        unitSelect.innerHTML = units.map((u) => `<option value="${esc(u.slug)}"${
            u.slug === chosen ? ' selected' : ''}>${esc(u.slug === 'other' ? 'other...' : u.label)}</option>`).join('');
        unitDetailGroup.hidden = unitSelect.value !== 'other';
    }

    // Says up front that posting will add the category to the profile, which
    // the server does when it is not listed there yet.
    function paintHint() {
        const slug = postCategory.value;
        const kind = postKind();
        const listed = me ? (kind === 'need' ? me.needs : me.offers) || [] : [];
        profileHint.hidden = !slug || !me || listed.includes(slug);
        profileHint.textContent = `Posting adds ${labels[slug] || 'this'} to your profile's `
            + `${kind === 'need' ? 'needs' : 'offers'}.`;
    }

    postCategory.addEventListener('change', () => { paintUnits(); paintHint(); });
    unitSelect.addEventListener('change', () => {
        unitDetailGroup.hidden = unitSelect.value !== 'other';
    });
    form.querySelectorAll('input[name="postKind"]').forEach((r) =>
        r.addEventListener('change', paintHint));

    function openPost() {
        form.reset();
        setMessage('');
        paintUnits();
        paintHint();
        const max = new Date();
        max.setDate(max.getDate() + 180);
        const iso = (d) => d.toISOString().slice(0, 10);
        const dateInput = document.getElementById('reqNeededBy');
        dateInput.min = iso(new Date());
        dateInput.max = iso(max);
        window.showDialog(modal, document.getElementById('reqTitle'));
    }

    // Not the plain "pplogin.html#signup": common.js rewrites that exact
    // link for signed-in visitors into "Go to your dashboard".
    postBtn.addEventListener('click', (e) => {
        if (!state.signedIn) return; // the href goes to signup
        e.preventDefault();
        openPost();
    });
    document.getElementById('reqCancel').addEventListener('click', () => window.hideDialog(modal));
    modal.querySelector('.close-modal').addEventListener('click', () => window.hideDialog(modal));
    modal.addEventListener('click', (e) => { if (e.target === modal) window.hideDialog(modal); });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const amount = document.getElementById('reqAmount').value.trim();
        const body = {
            kind: postKind(),
            category: postCategory.value,
            title: document.getElementById('reqTitle').value.trim(),
            details: document.getElementById('reqDetails').value.trim(),
            needed_by: document.getElementById('reqNeededBy').value,
            remote_ok: document.getElementById('reqRemoteOk').checked,
        };
        if (amount) {
            body.quantity = {
                amount, unit: unitSelect.value,
                detail: document.getElementById('reqUnitDetail').value.trim(),
            };
        }
        if (!body.category) { setMessage('Pick a category.'); return; }
        if (!body.title) { setMessage('Give the request a short title.'); return; }

        const submit = form.querySelector('button[type="submit"]');
        submit.disabled = true;
        setMessage('');
        try {
            const data = await window.api('/api/requests', { method: 'POST', body });
            if (data.added_to_profile && me) {
                me[data.added_to_profile] = [...(me[data.added_to_profile] || []), body.category];
            }
            window.hideDialog(modal);
            window.toast('Your request is on the board.');
            state.page = 1;
            writeUrl(data.request.id);
            showFocus(data.request.id);
            load();
        } catch (error) {
            setMessage(error.message || 'Could not post that request.');
        } finally {
            submit.disabled = false;
        }
    });

    // --- Start --------------------------------------------------------------

    const focusId = readUrl();
    await load();
    if (state.signedIn) {
        postBtn.href = '#';
        try {
            me = (await window.api('/api/me')).organization;
        } catch (error) {
            me = null;
        }
    }
    if (focusId) showFocus(focusId);
});
