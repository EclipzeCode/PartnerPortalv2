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

    // Placeholder rows, sized like real proposal cards, so the panel does not
    // collapse to one line of text and then expand once the list arrives.
    // Two, not more: most orgs have a handful of proposals at most, and a
    // wall of shimmer would overstate what is coming.
    function renderSkeletonRows(count = 2) {
        list.innerHTML = Array.from({ length: count }, () => `
            <article class="proposal-card skeleton-row" aria-hidden="true">
                <div class="skeleton skeleton-line title"></div>
                <div class="skeleton skeleton-line meta"></div>
                <div class="skeleton skeleton-block"></div>
            </article>
        `).join('');
    }

    // --- Data -----------------------------------------------------------
    async function load() {
        list.setAttribute('aria-busy', 'true');
        renderSkeletonRows();
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
            list.removeAttribute('aria-busy');
            list.innerHTML = `<p class="empty-state">${esc(error.message)}</p>`;
            return;
        }
        list.removeAttribute('aria-busy');
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
                // Live agreements only. A partnership that has run its course
                // sat here indefinitely, so this tab slowly became a list of
                // everything ever agreed rather than what is actually running.
                return proposals.filter((p) => p.status === 'accepted');
            default:
                return proposals.filter((p) => ['declined', 'withdrawn',
                    'completed', 'ended'].includes(p.status));
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

    // Where a partnership stands, in the cases the status pill cannot carry
    // on its own: waiting on one side to confirm, or finished with each
    // side's account of whether the other delivered.
    function lifecycleNote(p) {
        const parts = [];

        if (p.status === 'accepted' && (p.you_marked_complete || p.they_marked_complete)) {
            parts.push(p.you_marked_complete
                ? '<p class="lifecycle-note"><i class=\'bx bx-time-five\'></i> '
                  + 'You marked this complete. It closes once '
                  + esc(p.counterpart.name) + ' confirms.</p>'
                : '<p class="lifecycle-note"><i class=\'bx bx-bell\'></i> '
                  + esc(p.counterpart.name) + ' marked this complete. '
                  + 'Confirm from your side to close it.</p>');
        }

        if (p.status === 'ended') {
            parts.push('<p class="lifecycle-note">'
                + (p.ended_by_you
                    ? 'You ended this partnership.'
                    : esc(p.counterpart.name) + ' ended this partnership.')
                + '</p>');
            if (p.end_reason) {
                parts.push('<blockquote class="proposal-message">'
                    + esc(p.end_reason) + '</blockquote>');
            }
        }

        // Only once it is over: a verdict on a partnership still running is
        // not a verdict yet, and both sides record theirs at the same moment.
        if (p.status === 'completed') {
            const said = (verdict, who) => verdict === null || verdict === undefined
                ? `${who} did not say`
                : (verdict ? `${who} delivered` : `${who} did not deliver`);
            parts.push('<p class="lifecycle-note delivery">'
                + '<i class=\'bx bx-check-double\'></i> '
                + esc(said(p.counterpart_delivered, p.counterpart.name))
                + ' &middot; '
                + esc(said(p.you_delivered, 'You'))
                + ' <span class="lifecycle-private">(between the two of you)</span>'
                + '</p>');
        }

        return parts.join('');
    }

    function render() {
        const items = forTab(activeTab);
        list.innerHTML = '';

        if (items.length === 0) {
            const messages = {
                incoming: 'No proposals waiting on you.',
                outgoing: 'You have not sent any proposals yet. ' +
                          'Open a match and propose a partnership.',
                agreed: 'No partnerships running right now.',
                closed: 'Nothing closed yet — this is where partnerships go '
                        + 'once they finish, and where declined and withdrawn '
                        + 'proposals are kept.'
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
            if (p.share_token) {
                actions.push(
                    `<a class="btn-primary" target="_blank" rel="noopener"
                        href="partnership.html?token=${encodeURIComponent(p.share_token)}">
                        View agreement</a>`);
                actions.push('<button class="btn-ghost" data-act="copy">Copy link</button>');
            }
            if (p.can_complete) {
                actions.push(
                    '<button class="btn-ghost" data-act="complete">Mark complete</button>');
            }
            if (p.can_end) {
                actions.push('<button class="btn-ghost" data-act="end">End partnership</button>');
            }

            card.innerHTML = `
                <div class="proposal-head">
                    <div>
                        <span class="proposal-direction">${
                            p.direction === 'incoming' ? 'From' : 'To'
                        }</span>
                        <h3>${esc(other.name)}${
                            other.deleted
                                ? '<span class="party-closed">account closed</span>'
                                : ''
                        }</h3>
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
                ${lifecycleNote(p)}
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
        // The name rides along for the confirmation toast: by the time the
        // response lands, load() has re-rendered the list and this
        // proposal's card may have moved to another tab entirely.
        pending = { id, action: act, name: proposal.counterpart.name };
        respondTitle.textContent = {
            accept: `Accept partnership with ${proposal.counterpart.name}?`,
            decline: `Decline proposal from ${proposal.counterpart.name}?`,
            withdraw: `Withdraw your proposal to ${proposal.counterpart.name}?`,
            complete: `Mark your partnership with ${proposal.counterpart.name} complete?`,
            end: `End your partnership with ${proposal.counterpart.name}?`
        }[act];

        // Every branch says something: withdrawing used to leave a blank gap
        // between the title and the buttons.
        if (act === 'accept') {
            respondTerms.innerHTML = termsBlock(proposal) +
                '<p class="respond-note">Accepting creates a shareable summary ' +
                'that anyone with the link can read. It contains both ' +
                'organization names and these terms, but no contact details.</p>';
        } else if (act === 'complete') {
            // The delivery question is asked here because this is the moment
            // it is answerable, and only of the other side -- nobody grades
            // their own homework.
            respondTerms.innerHTML = termsBlock(proposal) +
                `<p class="respond-note">This closes once `
                + `${esc(proposal.counterpart.name)} confirms too. The shared `
                + `summary stays available and will say the partnership is `
                + `complete.</p>`
                + `<fieldset class="delivery-ask">
                       <legend>Did ${esc(proposal.counterpart.name)} provide
                       what they committed to?</legend>
                       <label><input type="radio" name="delivered" value="yes">
                           <span>Yes</span></label>
                       <label><input type="radio" name="delivered" value="no">
                           <span>No</span></label>
                       <label><input type="radio" name="delivered" value=""
                           checked><span>Rather not say</span></label>
                       <p class="delivery-note">Your answer is shown to
                       ${esc(proposal.counterpart.name)} and to no one else. It
                       never appears on the public summary, on either profile,
                       or in any total.</p>
                   </fieldset>`;
        } else if (act === 'end') {
            respondTerms.innerHTML =
                `<p class="respond-note">This stops the partnership now, `
                + `without waiting for ${esc(proposal.counterpart.name)} to `
                + `agree. They are told that you ended it, along with your `
                + `note below if you add one. The record of what was agreed `
                + `stays available, and you can propose again later.</p>`;
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

        // Completing takes no note -- the delivery answer is the message --
        // and withdrawing reaches nobody, so neither offers the box.
        respondMessage.parentElement.style.display =
            (act === 'withdraw' || act === 'complete') ? 'none' : '';
        const messageLabel = respondMessage.parentElement.querySelector('label');
        if (messageLabel) {
            messageLabel.textContent = act === 'end'
                ? 'Why are you ending it? (optional)'
                : 'Add a note (optional)';
        }
        respondConfirm.textContent = {
            accept: 'Accept partnership', decline: 'Decline', withdraw: 'Withdraw',
            complete: 'Mark complete', end: 'End partnership'
        }[act];
        respondConfirm.className =
            (act === 'accept' || act === 'complete') ? 'btn-primary' : 'btn-danger';
        respondMessage.value = '';
        openModal();
    });

    respondForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!pending) return;
        // Captured before the awaits below: `finally` clears pending, and
        // the toast is worded from it after load() has already run.
        const { action, name } = pending;
        respondConfirm.disabled = true;
        try {
            // Each endpoint takes the field it actually reads. Sending a
            // `message` to /complete or a `reason` to /decline would be
            // silently dropped, which is how a note someone typed goes
            // missing without anything saying so.
            let body;
            if (action === 'complete') {
                const picked = respondTerms.querySelector(
                    'input[name="delivered"]:checked');
                const value = picked ? picked.value : '';
                // "Rather not say" is an empty value and stays absent, so
                // "no answer" is distinguishable from "no".
                body = value ? { delivered: value === 'yes' } : {};
            } else if (action === 'end') {
                body = { reason: respondMessage.value.trim() };
            } else {
                body = { message: respondMessage.value.trim() };
            }

            const result = await window.api(
                `/api/proposals/${pending.id}/${pending.action}`,
                { method: 'POST', body });
            closeModal();
            // Land on the tab where the result now lives.
            if (action === 'accept') activateTab('agreed');
            if (action === 'end') activateTab('closed');
            // Completing only moves it once both sides have confirmed.
            if (action === 'complete' && !result.awaiting_other_side) {
                activateTab('closed');
            }
            await load();
            // The list re-renders underneath, and on accept the card also
            // changes tab -- easy to miss that anything happened at all, so
            // this says which of the three actions actually went through.
            window.toast({
                complete: result && result.awaiting_other_side
                    ? `Marked complete. It closes once ${name} confirms.`
                    : `Partnership with ${name} is complete.`,
                end: `Your partnership with ${name} has ended.`,
                accept: `Partnership with ${name} accepted.`,
                decline: `Proposal from ${name} declined.`,
                withdraw: `Your proposal to ${name} was withdrawn.`
            }[action]);
            // The dashboard's activity feed is built from this same history.
            document.dispatchEvent(new CustomEvent('partnerships:changed'));
        } catch (error) {
            respondTerms.innerHTML =
                `<p class="form-message">${esc(error.message)}</p>`;
        } finally {
            respondConfirm.disabled = false;
            pending = null;
        }
    });

    // --- Modal ----------------------------------------------------------
    // Focus is common.js's dialogOpened/dialogClosed: trapped inside while
    // open, returned to the Accept/Decline/Withdraw button on close.
    function openModal() {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        // The note, not the confirm button: this dialog is a decision, and
        // landing on the control that commits it invites a stray Enter.
        window.dialogOpened(modal, respondMessage);
    }

    function closeModal() {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
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

    // Deep link into a tab, e.g. ppdashboard.html#agreed
    const hash = location.hash.replace('#', '');
    if (['incoming', 'outgoing', 'agreed', 'closed'].includes(hash)) {
        activeTab = hash;
        tabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === hash));
    }

    await load();
});
