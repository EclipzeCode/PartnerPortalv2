// "Add a past partnership", from the dashboard.
//
// Records a partnership that already happened, or is still running, and
// sends it to the partner to confirm. A partner who is not on PartnerPortal
// yet gets an invitation instead, with the partnership waiting for them --
// see record_partnership in app.py. Its own file for the same reason
// invites.js is one: a dialog that writes rows, sitting on a page that
// reports.

document.addEventListener('DOMContentLoaded', () => {
    const openBtn = document.getElementById('recordBtn');
    const modal = document.getElementById('recordModal');
    if (!openBtn || !modal) return;

    const esc = window.escapeHtml;
    const $ = (id) => document.getElementById(id);
    const form = $('recordForm');
    const errorBox = $('recordError');
    const search = $('recordSearch');
    const results = $('recordResults');
    const picked = $('recordPicked');
    const absent = $('recordAbsent');
    const inviteFields = $('recordInviteFields');
    const amounts = $('recordAmounts');
    const submitBtn = $('recordSubmit');
    const result = $('recordResult');

    let partner = null;              // {id, name} once one is chosen
    let vocab = null;                // /api/categories
    const gives = { proposer: new Set(), recipient: new Set() };

    function showError(message) {
        errorBox.textContent = message || '';
        errorBox.hidden = !message;
    }

    function labelFor(slug) {
        for (const group of vocab.groups) {
            const hit = group.categories.find((c) => c.slug === slug);
            if (hit) return hit.label;
        }
        return slug;
    }

    function buildPicker(side, host) {
        host.innerHTML = vocab.groups.map((group) => `
            <div class="category-group">
                <h4>${esc(group.name)}</h4>
                <div class="category-options">${group.categories.map((c) => `
                    <label class="category-chip">
                        <input type="checkbox" value="${esc(c.slug)}">
                        <span>${esc(c.label)}</span>
                    </label>`).join('')}
                </div>
            </div>`).join('');
        host.onchange = (e) => {
            const box = e.target.closest('input[type="checkbox"]');
            if (!box) return;
            box.closest('.category-chip').classList.toggle('checked', box.checked);
            if (box.checked) gives[side].add(box.value);
            else gives[side].delete(box.value);
            renderAmounts();
        };
    }

    // Optional amounts for whatever is checked. Kept in the inputs rather
    // than a second copy of state, and read back on submit.
    function renderAmounts() {
        const held = readAmounts();
        const units = vocab.units.filter((u) => u.slug !== 'other');
        const rows = [];
        [['proposer', 'You gave'], ['recipient', 'They gave']].forEach(([side, heading]) => {
            if (!gives[side].size) return;
            rows.push(`<h4>${esc(heading)}</h4>`);
            gives[side].forEach((slug) => {
                const prior = held[side][slug] || {};
                const unit = prior.unit || vocab.default_units[slug] || 'items';
                rows.push(`
                    <div class="amount-row">
                        <span class="amount-label">${esc(labelFor(slug))}</span>
                        <input type="number" class="amount-value" min="0.01" step="any"
                               data-side="${side}" data-slug="${esc(slug)}"
                               value="${prior.amount ?? ''}" placeholder="—"
                               aria-label="Amount of ${esc(labelFor(slug))}">
                        <select class="amount-unit" data-side="${side}" data-slug="${esc(slug)}"
                                aria-label="Unit">${units.map((u) => `
                            <option value="${esc(u.slug)}"${u.slug === unit ? ' selected' : ''}>${
                                esc(u.label)}</option>`).join('')}
                        </select>
                    </div>`);
            });
        });
        amounts.hidden = rows.length === 0;
        amounts.innerHTML = rows.join('');
    }

    function readAmounts() {
        const out = { proposer: {}, recipient: {} };
        amounts.querySelectorAll('.amount-value').forEach((input) => {
            if (input.value === '') return;
            const { side, slug } = input.dataset;
            const unit = amounts.querySelector(
                `.amount-unit[data-side="${side}"][data-slug="${slug}"]`);
            out[side][slug] = { amount: Number(input.value), unit: unit && unit.value };
        });
        return out;
    }

    function choose(org) {
        partner = org;
        results.innerHTML = '';
        search.value = '';
        picked.hidden = !org;
        picked.innerHTML = org
            ? `<strong>${esc(org.name)}</strong> <button type="button" class="btn-ghost"
                   id="recordChange">Change</button>`
            : '';
    }

    let searchTimer = null;
    search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        const q = search.value.trim();
        if (q.length < 2) { results.innerHTML = ''; return; }
        searchTimer = setTimeout(async () => {
            try {
                const data = await window.api(
                    `/api/organizations?q=${encodeURIComponent(q)}&per_page=8`);
                results.innerHTML = (data.organizations || []).map((o) => `
                    <li><button type="button" class="btn-ghost" data-pick="${esc(o.id)}"
                                data-name="${esc(o.name)}">${esc(o.name)}${
                        o.location ? ` <span class="optional">${esc(o.location)}</span>` : ''
                    }</button></li>`).join('')
                    || '<li class="optional">No match. Tick the box below to invite them.</li>';
            } catch {
                results.innerHTML = '';
            }
        }, 250);
    });
    results.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-pick]');
        if (btn) choose({ id: Number(btn.dataset.pick), name: btn.dataset.name });
    });
    picked.addEventListener('click', (e) => {
        if (e.target.closest('#recordChange')) { choose(null); search.focus(); }
    });
    absent.addEventListener('change', () => {
        inviteFields.hidden = !absent.checked;
        $('recordSearchGroup').hidden = absent.checked;
        if (absent.checked) $('recordName').focus();
    });

    openBtn.addEventListener('click', async () => {
        showError('');
        result.hidden = true;
        form.hidden = false;
        form.reset();
        choose(null);
        inviteFields.hidden = true;
        $('recordSearchGroup').hidden = false;
        gives.proposer.clear();
        gives.recipient.clear();
        try {
            vocab = vocab || await window.api('/api/categories');
        } catch {
            window.toast('Could not load the categories. Try again.', 'error');
            return;
        }
        buildPicker('proposer', $('recordProposerGives'));
        buildPicker('recipient', $('recordRecipientGives'));
        renderAmounts();
        window.showDialog(modal, search);
    });

    const close = () => window.hideDialog(modal);
    modal.querySelector('.close-modal').addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        showError('');
        if (!absent.checked && !partner) {
            showError('Search for the organization, or tick the box if they are not here yet.');
            return;
        }
        const quantities = readAmounts();
        const delivered = $('recordDelivered').value;
        const body = {
            proposer_gives: [...gives.proposer],
            recipient_gives: [...gives.recipient],
            proposer_quantities: quantities.proposer,
            recipient_quantities: quantities.recipient,
            starts_on: $('recordStartsOn').value || null,
            ends_on: $('recordEndsOn').value || null,
            message: $('recordMessage').value.trim(),
        };
        if (delivered) body.delivered = delivered === 'yes';
        if (absent.checked) {
            body.partner_name = $('recordName').value.trim();
            body.partner_email = $('recordEmail').value.trim();
        } else {
            body.partner_id = partner.id;
        }

        submitBtn.disabled = true;
        try {
            const data = await window.api('/api/partnerships/recorded',
                { method: 'POST', body });
            if (data.invite) {
                // Not on the site: the link is how they confirm it, so it
                // stays on screen to be copied, as an invitation's does.
                form.hidden = true;
                result.hidden = false;
                $('recordSentNote').textContent = data.emailed_to
                    ? `Sent to ${data.emailed_to}. The same link is below.`
                    : 'They confirm it by claiming their profile.';
                $('recordLink').value = new URL(data.invite.claim_url, location.href).href;
                $('recordLink').select();
            } else {
                close();
                window.toast(`Sent to ${partner.name} to confirm.`);
                location.hash = 'outgoing';
                location.reload();
            }
        } catch (error) {
            showError(error.message || 'Could not record that partnership.');
        } finally {
            submitBtn.disabled = false;
        }
    });
});
