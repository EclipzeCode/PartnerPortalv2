// Partnership proposals: review incoming, track sent, confirm agreements.

document.addEventListener('DOMContentLoaded', async () => {
    const list = document.getElementById('proposalList');
    const tabs = [...document.querySelectorAll('.proposal-tab')];
    const modal = document.getElementById('respondModal');
    const respondForm = document.getElementById('respondForm');
    const respondTitle = document.getElementById('respondTitle');
    const respondTerms = document.getElementById('respondTerms');
    const respondMessage = document.getElementById('respondMessage');
    const respondConfirm = document.getElementById('respondConfirm');
    const respondCancel = document.getElementById('respondCancel');
    const esc = window.escapeHtml;

    let proposals = [];
    let activeTab = 'incoming';
    // What the modal will do on confirm: { id, action, verb }
    let pending = null;

    // --- Data -----------------------------------------------------------
    async function load() {
        list.innerHTML = '<p class="empty-state">Loading...</p>';
        try {
            const data = await window.api('/api/proposals');
            proposals = data.proposals || [];
            document.getElementById('countIncoming').textContent =
                data.counts.incoming_pending;
            document.getElementById('countOutgoing').textContent =
                data.counts.outgoing_pending;
            document.getElementById('countAgreed').textContent =
                data.counts.accepted;
        } catch (error) {
            list.innerHTML = `<p class="empty-state">${esc(error.message)}</p>`;
            return;
        }
        render();
    }

    function forTab(tab) {
        switch (tab) {
            case 'incoming':
                return proposals.filter(
                    (p) => p.direction === 'incoming' && p.status === 'pending');
            case 'outgoing':
                return proposals.filter(
                    (p) => p.direction === 'outgoing' && p.status === 'pending');
            case 'agreed':
                return proposals.filter((p) => p.status === 'accepted');
            default:
                return proposals.filter(
                    (p) => p.status === 'declined' || p.status === 'withdrawn');
        }
    }

    // --- Rendering ------------------------------------------------------
    function termsBlock(p) {
        const give = (p.you_give_labels || []).map(
            (l) => `<li>${esc(l)}</li>`).join('') || '<li class="none">Nothing listed</li>';
        const get = (p.you_receive_labels || []).map(
            (l) => `<li>${esc(l)}</li>`).join('') || '<li class="none">Nothing listed</li>';
        return `
            <div class="terms">
                <div class="terms-side gives">
                    <h4><i class='bx bx-up-arrow-alt'></i> You give</h4>
                    <ul>${give}</ul>
                </div>
                <div class="terms-side gets">
                    <h4><i class='bx bx-down-arrow-alt'></i> You receive</h4>
                    <ul>${get}</ul>
                </div>
            </div>
        `;
    }

    function render() {
        const items = forTab(activeTab);
        list.innerHTML = '';

        if (items.length === 0) {
            const messages = {
                incoming: 'No proposals waiting on you.',
                outgoing: 'You have not sent any proposals yet. ' +
                          'Open a match and propose a partnership.',
                agreed: 'No agreed partnerships yet.',
                closed: 'Nothing declined or withdrawn.'
            };
            list.innerHTML =
                `<p class="empty-state">${esc(messages[activeTab])}` +
                (activeTab === 'outgoing'
                    ? '<br><br><a class="btn-primary" href="ppsearch.html">Find partners</a>'
                    : '') + '</p>';
            return;
        }

        items.forEach((p) => {
            const other = p.counterpart;
            const card = document.createElement('article');
            card.className = `proposal-card status-${p.status}`;

            const when = p.created_at
                ? new Date(p.created_at).toLocaleDateString(
                    'en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                : '';

            const actions = [];
            if (p.can_respond) {
                actions.push('<button class="btn-primary" data-act="accept">Accept</button>');
                actions.push('<button class="btn-ghost" data-act="decline">Decline</button>');
            }
            if (p.can_withdraw) {
                actions.push('<button class="btn-ghost" data-act="withdraw">Withdraw</button>');
            }
            if (p.status === 'accepted' && p.share_token) {
                actions.push(
                    `<a class="btn-primary" target="_blank" rel="noopener"
                        href="partnership.html?token=${encodeURIComponent(p.share_token)}">
                        View agreement</a>`);
                actions.push('<button class="btn-ghost" data-act="copy">Copy link</button>');
            }

            card.innerHTML = `
                <div class="proposal-head">
                    <div>
                        <span class="proposal-direction">${
                            p.direction === 'incoming' ? 'From' : 'To'
                        }</span>
                        <h3>${esc(other.name)}</h3>
                        <p class="proposal-meta">${esc(other.organization_type || '')}${
                            other.location ? ' · ' + esc(other.location) : ''
                        } · ${esc(when)}</p>
                    </div>
                    <span class="status-pill status-${p.status}">${esc(p.status)}</span>
                </div>
                ${termsBlock(p)}
                ${p.timeline_label
                    ? `<p class="proposal-timeline"><i class='bx bx-time-five'></i> ${esc(p.timeline_label)}</p>`
                    : ''}
                ${p.message
                    ? `<blockquote class="proposal-message">${esc(p.message)}</blockquote>`
                    : ''}
                ${p.response_message
                    ? `<blockquote class="proposal-message reply"><strong>Reply:</strong> ${esc(p.response_message)}</blockquote>`
                    : ''}
                ${actions.length
                    ? `<div class="proposal-actions" data-id="${p.id}">${actions.join('')}</div>`
                    : ''}
            `;
            list.appendChild(card);
        });
    }

    // --- Actions --------------------------------------------------------
    list.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-act]');
        if (!btn) return;
        const id = Number(btn.closest('.proposal-actions').dataset.id);
        const act = btn.dataset.act;
        const proposal = proposals.find((p) => p.id === id);
        if (!proposal) return;

        if (act === 'copy') {
            const url = `${location.origin}/partnership.html?token=${
                encodeURIComponent(proposal.share_token)}`;
            try {
                await navigator.clipboard.writeText(url);
                btn.textContent = 'Copied';
                setTimeout(() => { btn.textContent = 'Copy link'; }, 1500);
            } catch {
                // Clipboard needs a secure context; show the URL so it can
                // still be copied by hand.
                window.prompt('Copy this link:', url);
            }
            return;
        }

        // Accept is the step that creates a binding-looking agreement and mints
        // a public link, so it is confirmed rather than fired on one click.
        pending = { id, action: act };
        respondTitle.textContent = {
            accept: `Accept partnership with ${proposal.counterpart.name}?`,
            decline: `Decline proposal from ${proposal.counterpart.name}?`,
            withdraw: `Withdraw your proposal to ${proposal.counterpart.name}?`
        }[act];

        // Every branch says something: withdrawing used to leave a blank gap
        // between the title and the buttons.
        if (act === 'accept') {
            respondTerms.innerHTML = termsBlock(proposal) +
                '<p class="respond-note">Accepting creates a shareable summary ' +
                'that anyone with the link can read. It contains both ' +
                'organization names and these terms, but no contact details.</p>';
        } else if (act === 'withdraw') {
            respondTerms.innerHTML =
                `<p class="respond-note">This takes the proposal back before ` +
                `${esc(proposal.counterpart.name)} has responded. They will no ` +
                `longer see it, and nothing is sent to them. You can propose ` +
                `again later.</p>`;
        } else {
            respondTerms.innerHTML =
                `<p class="respond-note">${esc(proposal.counterpart.name)} will ` +
                `see that you declined. Your note below, if you add one, goes ` +
                `with it.</p>`;
        }

        respondMessage.parentElement.style.display =
            act === 'withdraw' ? 'none' : '';
        respondConfirm.textContent = {
            accept: 'Accept partnership', decline: 'Decline', withdraw: 'Withdraw'
        }[act];
        respondConfirm.className = act === 'accept' ? 'btn-primary' : 'btn-danger';
        respondMessage.value = '';
        openModal();
    });

    respondForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!pending) return;
        respondConfirm.disabled = true;
        try {
            await window.api(`/api/proposals/${pending.id}/${pending.action}`, {
                method: 'POST',
                body: { message: respondMessage.value.trim() }
            });
            closeModal();
            // Land on the tab where the result now lives.
            if (pending.action === 'accept') activateTab('agreed');
            await load();
        } catch (error) {
            respondTerms.innerHTML =
                `<p class="form-message">${esc(error.message)}</p>`;
        } finally {
            respondConfirm.disabled = false;
            pending = null;
        }
    });

    // --- Modal ----------------------------------------------------------
    function openModal() {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }

    modal.querySelector('.close-modal').addEventListener('click', closeModal);
    respondCancel.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('active')) closeModal();
    });

    // --- Tabs -----------------------------------------------------------
    function activateTab(tab) {
        activeTab = tab;
        tabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
        render();
    }

    tabs.forEach((t) => {
        t.addEventListener('click', () => activateTab(t.dataset.tab));
    });

    // Deep link from the dashboard, e.g. proposals.html#agreed
    const hash = location.hash.replace('#', '');
    if (['incoming', 'outgoing', 'agreed', 'closed'].includes(hash)) {
        activeTab = hash;
        tabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === hash));
    }

    await load();
});
