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
    // The archive tab is the only one the server pages, because it is the
    // only one that grows without bound -- pending and agreed are bounded by
    // what is actually going on. These two track how much of it we are
    // holding so the tab can offer the rest rather than quietly stopping.
    let archiveLimit = 0;
    let archiveHasMore = false;
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
    // Skeletons stand in for a list that has not arrived yet. Once one has,
    // every refresh -- after an action, after each poll of an open thread
    // finds a new message -- keeps the cards in place until the new data is
    // here and swaps them in one paint. Before this, each of those blanked
    // the whole list to skeletons for a round trip, which behind an open
    // conversation meant the page flashing every time somebody replied.
    let loadedOnce = false;

    async function load({ archive } = {}) {
        list.setAttribute('aria-busy', 'true');
        if (!loadedOnce) renderSkeletonRows();
        try {
            const query = archive ? `?archive_limit=${archive}` : '';
            const data = await window.api(`/api/proposals${query}`);
            proposals = data.proposals || [];
            archiveLimit = data.archive_shown || 0;
            archiveHasMore = Boolean(data.archive_has_more);
            document.getElementById('countIncoming').textContent =
                data.counts.incoming_pending;
            document.getElementById('countOutgoing').textContent =
                data.counts.outgoing_pending;
            document.getElementById('countAgreed').textContent =
                data.counts.accepted;
        } catch (error) {
            list.removeAttribute('aria-busy');
            // A failed refresh leaves the cards that are there. Only a list
            // that never loaded has nothing better to show than the error.
            if (!loadedOnce) {
                list.innerHTML = `<p class="empty-state">${esc(error.message)}</p>`;
            } else {
                window.toast(error.message || 'Could not refresh proposals.', 'error');
            }
            return;
        }
        loadedOnce = true;
        list.removeAttribute('aria-busy');
        render();
    }

    function forTab(tab) {
        switch (tab) {
            // "Needs your response" is whose turn it is, not who sent it: a
            // proposal of yours that came back countered sits here too, and
            // one you countered moves to Sent until they answer.
            case 'incoming':
                return proposals.filter(
                    (p) => p.status === 'pending' && p.awaiting_you);
            case 'outgoing':
                return proposals.filter(
                    (p) => p.status === 'pending' && !p.awaiting_you);
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

    // "1 Mar 2026 - 30 Jun 2026", or half of it, or nothing. A start with no
    // end is open-ended, which is a real arrangement rather than a gap.
    function datesLine(p) {
        const show = (iso) => {
            // Parsed as parts, not as a string: `new Date('2026-03-01')` is
            // read as UTC midnight and renders as the previous day for
            // anyone west of Greenwich.
            const [y, m, d] = String(iso).split('-').map(Number);
            if (!y || !m || !d) return '';
            return new Date(y, m - 1, d).toLocaleDateString('en-US', {
                day: 'numeric', month: 'short', year: 'numeric',
            });
        };
        const from = p.starts_on ? show(p.starts_on) : '';
        const to = p.ends_on ? show(p.ends_on) : '';
        if (from && to) return `${from} - ${to}`;
        if (from) return `From ${from}`;
        if (to) return `Until ${to}`;
        return '';
    }

    // Where a partnership stands, in the cases the status pill cannot carry
    // on its own: waiting on one side to confirm, or finished with each
    // side's account of whether the other delivered.
    function lifecycleNote(p) {
        const parts = [];

        if (p.status === 'pending' && p.countered) {
            parts.push(p.awaiting_you
                ? '<p class="lifecycle-note"><i class=\'bx bx-transfer-alt\'></i> '
                  + esc(p.counterpart.name) + ' suggested different terms. '
                  + 'The terms above are theirs: accept them, decline, or '
                  + 'counter with your own.</p>'
                : '<p class="lifecycle-note"><i class=\'bx bx-transfer-alt\'></i> '
                  + 'You suggested different terms. Waiting on '
                  + esc(p.counterpart.name) + '.</p>');
        }

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

    // What the list now holds, for anyone not watching it. Switching tabs
    // and finishing a load both replace every card silently; this is the
    // only thing that says so. Written to a region outside the list, so a
    // screen reader hears one sentence rather than every card again.
    function announce(count) {
        const status = document.getElementById('proposalStatus');
        if (!status) return;
        const label = {
            incoming: 'awaiting your response',
            outgoing: 'sent and awaiting a reply',
            agreed: 'running',
            closed: 'closed',
        }[activeTab] || '';
        status.textContent = count === 0
            ? `No proposals ${label}.`
            : `${count} proposal${count === 1 ? '' : 's'} ${label}.`;
    }

    function render() {
        const items = forTab(activeTab);
        list.innerHTML = '';
        announce(items.length);

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
            if (p.can_edit) {
                // Before Withdraw, because correcting a term is the lighter
                // of the two and used to be reachable only through it. The
                // proposer correcting an unanswered proposal is editing;
                // anyone whose turn it is -- the recipient, or the proposer
                // answering a counter -- is countering: the same dialog,
                // but their change is their answer.
                actions.push(`<button class="btn-ghost" data-act="edit">${
                    p.awaiting_you ? 'Counter' : 'Edit terms'}</button>`);
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
                // The link used to be permanent, so anyone ever sent it kept
                // it. These are the way back from that.
                actions.push('<button class="btn-ghost" data-act="rotate">New link</button>');
                actions.push('<button class="btn-ghost" data-act="unshare">Remove link</button>');
            } else if (['accepted', 'completed', 'ended'].includes(p.status)) {
                actions.push('<button class="btn-ghost" data-act="rotate">Create link</button>');
            }
            // On every proposal, open or settled: a closed thread is still
            // the record of what the two of you said, and it is the only
            // place that record lives.
            if (p.message_count > 0 || p.messages_open) {
                const label = p.unread_count > 0
                    ? `Messages <span class="msg-unread">${p.unread_count}</span>`
                    : (p.message_count > 0
                        ? `Messages (${p.message_count})`
                        : 'Messages');
                actions.push(
                    `<button class="btn-ghost msg-open" data-act="messages">${label}</button>`);
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
                    <span class="status-pill status-${p.status}">${
                        esc(p.status === 'pending' && p.countered ? 'countered' : p.status)
                    }</span>
                </div>
                ${termsBlock(p)}
                ${p.timeline_label
                    ? `<p class="proposal-timeline"><i class='bx bx-time-five'></i> ${esc(p.timeline_label)}</p>`
                    : ''}
                ${datesLine(p)
                    ? `<p class="proposal-dates"><i class='bx bx-calendar'></i> ${esc(datesLine(p))}</p>`
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

        // Only under the archive, and only when there is genuinely more. A
        // list that stops without saying so is the thing this is here to
        // avoid: everywhere else that truncates -- the matches, the
        // directory -- says how much it is not showing, and the archive
        // silently sending the newest twenty-five would have been the one
        // place a partnership could go missing without a word.
        if (activeTab === 'closed' && archiveHasMore) {
            const more = document.createElement('button');
            more.type = 'button';
            more.className = 'btn-ghost archive-more';
            more.textContent = 'Show older';
            more.addEventListener('click', () => {
                more.disabled = true;
                more.textContent = 'Loading...';
                // Ask for the next page's worth on top of what is already
                // held. The whole list is refetched rather than appended to,
                // which keeps one code path for "what does the server say I
                // have" instead of a second one that merges.
                load({ archive: archiveLimit + 25 });
            });
            list.appendChild(more);
        }
    }

    // --- Messages -------------------------------------------------------
    // A proposal carried one message and one reply, so anything that needed
    // working out moved to email -- and what two organizations settle in
    // email is not written down anywhere this site can show them later.
    const messageModal = document.getElementById('messageModal');
    const messageThread = document.getElementById('messageThread');
    const messageForm = document.getElementById('messageForm');
    const messageBody = document.getElementById('messageBody');
    const messageSend = document.getElementById('messageSend');
    const messageError = document.getElementById('messageError');
    const messageClosed = document.getElementById('messageClosed');
    const messageTitle = document.getElementById('messageTitle');

    let openThreadId = null;

    // --- Live thread ------------------------------------------------------
    // The thread used to be fetched once, when the dialog opened, and never
    // again. A reply arriving while you were reading -- the likeliest moment
    // for one, since the message you just sent is what prompted it -- stayed
    // invisible until you closed the dialog and opened it again, with
    // nothing on screen suggesting the view was stale.
    //
    // Polling rather than anything cleverer: this is a two-person thread on
    // a proposal, open for a minute at a time, and the endpoint it calls is
    // a single indexed query. A socket would be a lot of machinery for that.
    const THREAD_POLL_MS = 12000;
    let threadTimer = null;
    let threadMessages = [];
    // Cheap "has anything actually changed" key, so a poll that finds
    // nothing new does not redraw the thread under someone's cursor.
    let threadSignature = '';
    // Whether the thread has messages older than the first one held. The
    // server sends the newest page on open; this is what draws the "earlier
    // messages" control at the top and what that control asks for.
    let threadHasMore = false;

    function signatureFor(messages, open) {
        const last = messages[messages.length - 1];
        return `${messages.length}:${last ? last.id : 0}:${open}`;
    }

    // Within a line or so of the bottom. Anyone further up is reading back
    // through the thread, and yanking them to the newest message because it
    // happened to arrive is the rudest thing this could do.
    function threadAtBottom() {
        const el = messageThread;
        return el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    }

    function stopThreadPolling() {
        clearInterval(threadTimer);
        threadTimer = null;
    }

    function startThreadPolling() {
        stopThreadPolling();
        // Nothing to poll for on a settled proposal: the thread is readable
        // and closed to new messages, so it cannot change.
        if (openThreadId === null || messageForm.hidden) return;
        threadTimer = setInterval(pollThread, THREAD_POLL_MS);
    }

    async function pollThread() {
        if (openThreadId === null || document.hidden) return;
        const id = openThreadId;
        // Ask only for what we do not already have. The thread is polled
        // every twelve seconds and almost every one of those finds nothing,
        // so sending the last id we hold turns the common case into an empty
        // reply instead of a fresh copy of the entire conversation.
        const held = threadMessages[threadMessages.length - 1];
        const since = held ? `?since=${held.id}` : '';
        let data;
        try {
            data = await window.api(`/api/proposals/${id}/messages${since}`);
        } catch (error) {
            // A blip should not empty the thread or start shouting. If the
            // proposal has genuinely gone, stop asking.
            if (error.status === 404 || error.status === 403) stopThreadPolling();
            return;
        }
        // The dialog may have been closed, or a different one opened, while
        // that request was in the air.
        if (openThreadId !== id) return;

        // A delta is appended; a full reply replaces. Which one this is is
        // decided by what we asked for, not by what came back -- an empty
        // `messages` means "nothing new" on a delta and "no messages at all"
        // on a full fetch, and the two must not be confused.
        //
        // Appended by id, never blindly concatenated. Two polls can be in
        // flight at once -- the interval fires one and coming back to the
        // tab fires another -- and both would carry the same `since`,
        // because each read it before either reply landed. Concatenating
        // would then show the same message twice. Replacing the whole list
        // used to make this impossible for free; appending has to earn it.
        const fresh = data.messages || [];
        const known = new Set(threadMessages.map((m) => m.id));
        const added = fresh.filter((m) => !known.has(m.id));
        const messages = since ? threadMessages.concat(added) : fresh;

        // Every message about a meeting carries that meeting as it stands
        // when the message is fetched. A delta fetch only brings the new
        // messages, so the older cards for the same meeting kept saying
        // "Waiting on them" after the reply that answered it had arrived --
        // two cards, one meeting, two states. The newest copy is the truth
        // for all of them.
        const latestMeeting = new Map();
        added.forEach((m) => {
            if (m.meeting) latestMeeting.set(m.meeting.id, m.meeting);
        });
        if (latestMeeting.size) {
            messages.forEach((m) => {
                if (m.meeting && latestMeeting.has(m.meeting.id)) {
                    m.meeting = latestMeeting.get(m.meeting.id);
                }
            });
        }

        const signature = signatureFor(messages, data.open);
        // Nothing new and the thread has not opened or closed. This is the
        // overwhelmingly common outcome, and it now costs no redraw, no
        // refresh of the nav counts and -- the expensive one -- no refetch
        // of the whole proposals list below.
        if (signature === threadSignature) return;
        threadSignature = signature;
        threadMessages = messages;

        renderThread(messages, { keepScroll: !threadAtBottom() });

        // Reading the thread is what marked those messages read, so the
        // badge in the nav and the count on the card are both stale now.
        if (window.refreshNavCounts) window.refreshNavCounts();

        // Refreshed before the open/closed notice is painted, not after: if
        // the proposal settled while this thread was on screen, that notice
        // names the status, and `proposals` is still holding the previous
        // one until this resolves -- so painting first said "this proposal
        // was pending, so the conversation is closed".
        await load();
        paintThreadOpenState(data.open);
    }

    // A proposal can settle while its thread is open -- the other side
    // declines, or either side ends the partnership -- and the form has to
    // go when it does, rather than failing on submit.
    function paintThreadOpenState(open) {
        messageForm.hidden = !open || !meetingForm.hidden;
        messageClosed.hidden = open;
        if (!open) {
            const proposal = proposals.find((p) => p.id === openThreadId);
            const status = proposal ? proposal.status : 'closed';
            // A live proposal whose thread is closed is one a block has
            // closed -- from either side, and the words do not say which.
            messageClosed.textContent = ['pending', 'accepted'].includes(status)
                ? 'This conversation is closed. Everything said here stays '
                  + 'with it.'
                : `This proposal was ${status}, so the conversation is closed. `
                  + 'Everything said here stays with it.';
            stopThreadPolling();
        }
    }

    // Polling a hidden tab is work nobody is looking at. Coming back should
    // show the current thread immediately rather than up to a poll later.
    document.addEventListener('visibilitychange', () => {
        if (openThreadId === null) return;
        if (document.hidden) {
            stopThreadPolling();
        } else {
            pollThread();
            startThreadPolling();
        }
    });

    // --- Shared meetings -------------------------------------------------
    // A meeting is arranged inside the thread. The server writes a card
    // into the conversation for each step; this draws the meeting as it
    // stands now under the newest of them, with the answers the reader
    // still has.
    function meetingWhen(ev) {
        const [y, mo, d] = ev.date.split('-').map(Number);
        const day = new Date(y, mo - 1, d).toLocaleDateString('en-US', {
            weekday: 'short', month: 'short', day: 'numeric',
        });
        if (ev.all_day) return `${day}, all day`;
        const [hh, mm] = ev.time.split(':').map(Number);
        const clock = new Date(y, mo - 1, d, hh, mm).toLocaleTimeString('en-US', {
            hour: 'numeric', minute: '2-digit',
        });
        let zone = '';
        if (ev.timezone) {
            try {
                const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
                if (ev.timezone !== local) {
                    const part = new Intl.DateTimeFormat('en-US', {
                        timeZone: ev.timezone, timeZoneName: 'short',
                    }).formatToParts(new Date(y, mo - 1, d, hh, mm))
                        .find((x) => x.type === 'timeZoneName');
                    if (part) zone = ` ${part.value}`;
                }
            } catch { /* a zone this browser lacks */ }
        }
        const hours = Number(ev.duration);
        const length = hours ? ` · ${hours} hr${hours === 1 ? '' : 's'}` : '';
        return `${day}, ${clock}${zone}${length}`;
    }

    function meetingCard(ev, current) {
        const sh = ev.shared || {};
        const state = {
            proposed: sh.awaiting_you ? 'Waiting on you' : 'Waiting on them',
            accepted: 'On both calendars',
            declined: 'Declined',
            cancelled: sh.cancelled_by_you ? 'You cancelled it' : 'Cancelled',
        }[sh.status] || sh.status;
        const actions = [];
        if (current && sh.can_respond) {
            actions.push(`<button type="button" class="btn-primary" data-meet="accept" data-meet-id="${ev.id}">Accept</button>`);
            actions.push(`<button type="button" class="btn-ghost" data-meet="move" data-meet-id="${ev.id}">Suggest another time</button>`);
            actions.push(`<button type="button" class="btn-ghost" data-meet="decline" data-meet-id="${ev.id}">Decline</button>`);
        } else if (current && sh.can_change) {
            if (sh.status === 'accepted') {
                actions.push(`<a class="btn-ghost" download href="/api/events/${encodeURIComponent(ev.id)}.ics"><i class='bx bx-calendar-plus'></i> Add to calendar</a>`);
            }
            actions.push(`<button type="button" class="btn-ghost" data-meet="move" data-meet-id="${ev.id}">${
                sh.status === 'accepted' ? 'Move it' : 'Change the time'}</button>`);
            actions.push(`<button type="button" class="btn-ghost" data-meet="cancel" data-meet-id="${ev.id}">Cancel meeting</button>`);
        }
        return `
            <div class="meeting-card status-${esc(sh.status || '')}">
                <div class="meeting-card-head">
                    <i class='bx bx-calendar-event' aria-hidden="true"></i>
                    <strong>${esc(ev.title)}</strong>
                    <span class="meeting-state">${esc(state)}</span>
                </div>
                <p class="meeting-when">${esc(meetingWhen(ev))}</p>
                ${ev.location ? `<p class="meeting-where">${esc(ev.location)}</p>` : ''}
                ${ev.description ? `<p class="meeting-notes">${esc(ev.description)}</p>` : ''}
                ${actions.length ? `<div class="meeting-actions">${actions.join('')}</div>` : ''}
            </div>`;
    }

    const meetingForm = document.getElementById('meetingForm');
    const meetingFormTitle = document.getElementById('meetingFormTitle');
    const meetingFormError = document.getElementById('meetingFormError');
    const meetingSubmit = document.getElementById('meetingSubmitBtn');
    const meetingProposeBtn = document.getElementById('meetingProposeBtn');
    const meetingFields = {
        title: document.getElementById('meetingTitle'),
        date: document.getElementById('meetingDate'),
        time: document.getElementById('meetingTime'),
        duration: document.getElementById('meetingDuration'),
        allDay: document.getElementById('meetingAllDay'),
        location: document.getElementById('meetingLocation'),
        notes: document.getElementById('meetingNotes'),
    };
    let meetingEditing = null;   // meeting id when suggesting a time, else null

    function localZone() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
        } catch { return null; }
    }

    function showMeetingError(text) {
        meetingFormError.textContent = text || '';
        meetingFormError.hidden = !text;
    }

    function syncMeetingAllDay() {
        const on = meetingFields.allDay.checked;
        meetingFields.time.disabled = on;
        meetingFields.duration.disabled = on;
    }
    meetingFields.allDay.addEventListener('change', syncMeetingAllDay);

    function openMeetingForm(existing) {
        meetingEditing = existing ? existing.id : null;
        showMeetingError('');
        meetingForm.reset();
        if (existing) {
            meetingFields.title.value = existing.title || '';
            meetingFields.date.value = existing.date || '';
            meetingFields.time.value = existing.all_day ? '' : (existing.time || '');
            meetingFields.duration.value = existing.duration ?? '';
            meetingFields.allDay.checked = Boolean(existing.all_day);
            meetingFields.location.value = existing.location || '';
            meetingFields.notes.value = existing.description || '';
        }
        // Only the schedule moves when suggesting a time; the rest stays
        // as the meeting has it, editable but not the point.
        meetingFormTitle.textContent = existing
            ? 'Suggest a different time' : 'Propose a meeting';
        meetingSubmit.textContent = existing ? 'Suggest this time' : 'Propose';
        const zone = localZone();
        document.getElementById('meetingZoneNote').textContent = zone
            ? `Times are in ${zone}. ${
                openThreadId !== null
                    ? 'Your partner sees them in theirs.' : ''}`
            : '';
        syncMeetingAllDay();
        meetingForm.hidden = false;
        messageForm.hidden = true;
        meetingFields.title.focus();
    }

    function closeMeetingForm() {
        meetingForm.hidden = true;
        messageForm.hidden = !(proposals.find((p) => p.id === openThreadId) || {}).messages_open;
        meetingEditing = null;
    }

    if (meetingProposeBtn) {
        meetingProposeBtn.addEventListener('click', () => openMeetingForm(null));
    }
    document.getElementById('meetingCancelBtn')
        .addEventListener('click', closeMeetingForm);

    function meetingBody() {
        const allDay = meetingFields.allDay.checked;
        return {
            title: meetingFields.title.value.trim(),
            date: meetingFields.date.value,
            all_day: allDay,
            time: allDay ? '00:00' : meetingFields.time.value,
            duration: allDay || !meetingFields.duration.value
                ? null : Number(meetingFields.duration.value),
            timezone: localZone(),
            location: meetingFields.location.value.trim(),
            description: meetingFields.notes.value.trim(),
        };
    }

    // The thread is refetched in full after any meeting action: several
    // cards can change at once (the new one, and the one before it losing
    // its buttons), and `since` polling would only bring the new one.
    async function refreshThread() {
        if (openThreadId === null) return;
        const data = await window.api(`/api/proposals/${openThreadId}/messages`);
        threadMessages = data.messages || [];
        threadHasMore = Boolean(data.has_more);
        threadSignature = signatureFor(threadMessages, data.open);
        renderThread(threadMessages);
        paintThreadOpenState(data.open);
        await load();
        if (window.refreshNavCounts) window.refreshNavCounts();
    }

    meetingForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (openThreadId === null) return;
        const body = meetingBody();
        if (!body.title) { showMeetingError('Give the meeting a title.'); meetingFields.title.focus(); return; }
        if (!body.date) { showMeetingError('Pick a date.'); meetingFields.date.focus(); return; }
        if (!body.all_day && !body.time) { showMeetingError('Pick a start time.'); meetingFields.time.focus(); return; }
        showMeetingError('');
        meetingSubmit.disabled = true;
        try {
            const path = meetingEditing === null
                ? `/api/proposals/${openThreadId}/meetings`
                : `/api/proposals/${openThreadId}/meetings/${meetingEditing}`;
            const result = await window.api(path, {
                method: meetingEditing === null ? 'POST' : 'PATCH', body,
            });
            closeMeetingForm();
            await refreshThread();
            window.toast(result.message || 'Sent.');
            document.dispatchEvent(new CustomEvent('partnerships:changed'));
        } catch (error) {
            showMeetingError(error.message || 'Could not send that.');
        } finally {
            meetingSubmit.disabled = false;
        }
    });

    // Older history, a page at a time, keeping the reader's place: the
    // newly inserted messages land above the viewport, so the scroll
    // offset is moved down by exactly the height they added.
    messageThread.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-earlier]');
        if (!btn || openThreadId === null || !threadMessages.length) return;
        const id = openThreadId;
        const oldest = threadMessages[0].id;
        btn.disabled = true;
        btn.textContent = 'Loading...';
        let data;
        try {
            data = await window.api(
                `/api/proposals/${id}/messages?before=${oldest}`);
        } catch (error) {
            btn.disabled = false;
            btn.textContent = 'Show earlier messages';
            window.toast(error.message || 'Could not load those.', 'error');
            return;
        }
        if (openThreadId !== id) return;
        const heightBefore = messageThread.scrollHeight;
        const scrollBefore = messageThread.scrollTop;
        threadMessages = (data.messages || []).concat(threadMessages);
        threadHasMore = Boolean(data.has_more);
        threadSignature = signatureFor(threadMessages, messageClosed.hidden);
        renderThread(threadMessages, { keepScroll: true });
        messageThread.scrollTop =
            scrollBefore + (messageThread.scrollHeight - heightBefore);
    });

    messageThread.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-meet]');
        if (!btn || openThreadId === null) return;
        const id = Number(btn.dataset.meetId);
        const act = btn.dataset.meet;
        const current = [...threadMessages].reverse()
            .find((m) => m.meeting && m.meeting.id === id);
        if (act === 'move') {
            openMeetingForm(current ? current.meeting : { id });
            meetingForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            return;
        }
        btn.disabled = true;
        try {
            const result = await window.api(
                `/api/proposals/${openThreadId}/meetings/${id}/${act}`,
                { method: 'POST' });
            await refreshThread();
            window.toast(result.message);
            document.dispatchEvent(new CustomEvent('partnerships:changed'));
        } catch (error) {
            btn.disabled = false;
            window.toast(error.message || 'Could not do that.', 'error');
            if (error.status === 409) refreshThread();
        }
    });

    function messageDate(iso) {
        const at = new Date(iso);
        if (Number.isNaN(at.getTime())) return '';
        const sameDay = at.toDateString() === new Date().toDateString();
        return sameDay
            ? at.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
            : at.toLocaleString('en-US', {
                month: 'short', day: 'numeric',
                hour: 'numeric', minute: '2-digit',
            });
    }

    function renderThread(messages, { keepScroll = false } = {}) {
        const previousScroll = messageThread.scrollTop;
        if (messages.length === 0) {
            messageThread.innerHTML =
                '<p class="empty-state">No messages yet. Anything you agree '
                + 'here stays with the proposal.</p>';
            return;
        }
        // The actions for a meeting go on its newest card only: every
        // earlier card about the same meeting is history.
        const newestFor = new Map();
        messages.forEach((m) => {
            if (m.kind === 'meeting' && m.meeting) newestFor.set(m.meeting.id, m.id);
        });
        const earlier = threadHasMore
            ? '<button type="button" class="btn-ghost thread-earlier" '
              + 'data-earlier>Show earlier messages</button>'
            : '';
        messageThread.innerHTML = earlier + messages.map((m) => `
            <div class="message${m.mine ? ' mine' : ''}${
                m.kind === 'meeting' ? ' is-meeting' : ''}">
                <p class="message-meta">
                    <strong>${esc(m.mine ? 'You' : m.sender_name)}</strong>${
                        m.sender_deleted && !m.mine
                            ? '<span class="party-closed">account closed</span>'
                            : ''
                    }
                    <span class="message-time">${esc(messageDate(m.created_at))}</span>
                </p>
                <p class="message-body">${esc(m.body)}</p>
                ${m.kind === 'meeting' && m.meeting
                    ? meetingCard(m.meeting, newestFor.get(m.meeting.id) === m.id)
                    : ''}
            </div>`).join('');
        // Newest is at the bottom, which is where a thread is read from --
        // unless the reader had scrolled up, in which case a message
        // arriving must not drag them away from what they were reading.
        messageThread.scrollTop = keepScroll
            ? previousScroll
            : messageThread.scrollHeight;
    }

    async function openThread(proposal) {
        openThreadId = proposal.id;
        messageTitle.textContent = `Messages with ${proposal.counterpart.name}`;
        messageThread.setAttribute('aria-busy', 'true');
        messageThread.innerHTML = '<p class="empty-state">Loading...</p>';
        messageError.hidden = true;
        messageBody.value = '';

        window.showDialog(messageModal, messageBody);

        let data;
        try {
            data = await window.api(`/api/proposals/${proposal.id}/messages`);
        } catch (error) {
            messageThread.removeAttribute('aria-busy');
            messageThread.innerHTML =
                `<p class="empty-state">${esc(error.message)}</p>`;
            return;
        }
        messageThread.removeAttribute('aria-busy');
        threadMessages = data.messages || [];
        threadHasMore = Boolean(data.has_more);
        threadSignature = signatureFor(threadMessages, data.open);
        renderThread(threadMessages);

        // Settled proposals keep the thread readable and stop accepting
        // posts, so the form is replaced rather than left to fail on submit.
        paintThreadOpenState(data.open);

        // Kept current from here on, so a reply that arrives while this is
        // open shows up rather than waiting for the dialog to be reopened.
        startThreadPolling();

        // Opening the thread marked it read, so the badge on the card and in
        // the nav are both stale until the list is refetched.
        await load();
        if (window.refreshNavCounts) window.refreshNavCounts();
    }

    // --- Report or block ---------------------------------------------------
    const reportToggle = document.getElementById('reportToggle');
    const reportForm = document.getElementById('reportForm');
    const reportReason = document.getElementById('reportReason');
    const reportBlock = document.getElementById('reportBlock');
    const reportError = document.getElementById('reportError');
    const reportSubmit = document.getElementById('reportSubmit');
    const blockOnlyBtn = document.getElementById('blockOnlyBtn');

    function setReportOpen(open) {
        if (!reportForm) return;
        reportForm.hidden = !open;
        reportToggle.setAttribute('aria-expanded', String(open));
        if (open) {
            const proposal = proposals.find((p) => p.id === openThreadId);
            const name = proposal && proposal.counterpart
                ? proposal.counterpart.name : 'this organization';
            document.getElementById('reportBlockName').textContent = name;
            reportError.hidden = true;
            reportReason.focus();
        } else {
            reportReason.value = '';
            reportBlock.checked = false;
        }
    }

    function showReportError(text) {
        reportError.textContent = text || '';
        reportError.hidden = !text;
    }

    // After a block the thread is closed and the proposal settled, and the
    // list and the nav both have to say so.
    async function afterSafetyAction(message) {
        setReportOpen(false);
        window.toast(message);
        await refreshThread();
        document.dispatchEvent(new CustomEvent('partnerships:changed'));
    }

    if (reportToggle) {
        reportToggle.addEventListener('click', () => setReportOpen(reportForm.hidden));
        document.getElementById('reportCancel')
            .addEventListener('click', () => setReportOpen(false));

        reportForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (openThreadId === null) return;
            const reason = reportReason.value.trim();
            if (!reason) {
                showReportError('Say what the problem is.');
                reportReason.focus();
                return;
            }
            reportSubmit.disabled = true;
            try {
                const result = await window.api(
                    `/api/proposals/${openThreadId}/report`,
                    { method: 'POST', body: { reason, block: reportBlock.checked } });
                await afterSafetyAction(result.message);
            } catch (error) {
                showReportError(error.message || 'Could not send that.');
            } finally {
                reportSubmit.disabled = false;
            }
        });

        blockOnlyBtn.addEventListener('click', async () => {
            const proposal = proposals.find((p) => p.id === openThreadId);
            const other = proposal && proposal.counterpart;
            if (!other || other.id === null || other.id === undefined) {
                showReportError('That organization has closed its account.');
                return;
            }
            if (!window.confirm(`Block ${other.name}? They will not be able to `
                    + 'propose to you or message you again, and any proposal '
                    + 'between you is closed. You can undo this in Settings.')) {
                return;
            }
            blockOnlyBtn.disabled = true;
            try {
                const result = await window.api('/api/blocks',
                    { method: 'POST', body: { organization_id: other.id } });
                await afterSafetyAction(result.message);
            } catch (error) {
                showReportError(error.message || 'Could not block them.');
            } finally {
                blockOnlyBtn.disabled = false;
            }
        });
    }

    function closeThread() {
        setReportOpen(false);
        stopThreadPolling();
        meetingForm.hidden = true;
        meetingEditing = null;
        openThreadId = null;
        threadMessages = [];
        threadSignature = '';
        threadHasMore = false;
        window.hideDialog(messageModal);
    }

    messageModal.querySelector('.close-modal').addEventListener('click', closeThread);
    messageModal.addEventListener('click', (e) => {
        if (e.target === messageModal) closeThread();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && messageModal.classList.contains('active')) {
            closeThread();
        }
    });

    messageForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const body = messageBody.value.trim();
        if (!body || openThreadId === null) return;

        messageSend.disabled = true;
        messageError.hidden = true;
        try {
            const result = await window.api(
                `/api/proposals/${openThreadId}/messages`,
                { method: 'POST', body: { body } });
            messageBody.value = '';
            // Added to the thread this page already holds rather than
            // refetched: the reply is in hand, and a round trip here would
            // blank the thread mid-conversation. Going through the same
            // state the poll reads keeps the two from fighting -- the
            // signature is advanced with it, so the next poll sees nothing
            // new and leaves the thread alone instead of redrawing it.
            threadMessages = [...threadMessages, result.sent];
            threadSignature = signatureFor(threadMessages, true);
            renderThread(threadMessages);
            messageBody.dispatchEvent(new Event('input'));
            await load();
        } catch (error) {
            // 409 here means the proposal settled while this was being
            // typed -- declined, withdrawn, or ended by the other side. The
            // thread is closed to new messages now, so saying so beside a
            // form that still invites another one just gets the same
            // refusal again. paintThreadOpenState swaps the form for the
            // closed notice, which is what the poll would have done a few
            // seconds later anyway; load() runs first because that notice
            // names the status and reads it from the list.
            if (error.status === 409) {
                await load();
                paintThreadOpenState(false);
                window.toast(error.message, 'error');
            } else {
                messageError.textContent = error.message;
                messageError.hidden = false;
            }
        } finally {
            messageSend.disabled = false;
        }
    });

    // --- Editing a pending proposal --------------------------------------
    // Only the sender, and only before it is answered -- the same window as
    // withdrawing. Until now correcting a date meant withdrawing and sending
    // again, which took the message thread with it: the cost of a typo was
    // the conversation that had been going on about it.
    //
    // The terms themselves -- who gives what -- are editable too. They were
    // not, at first, on the argument that the picker on the matches page is
    // where the rule about what each side may commit to lives and a second
    // copy is a second place to get it wrong. In practice the rule is the
    // server's (update_proposal refuses anything not on the giver's profile)
    // and both dialogs draw their chips from the same two offer lists, so
    // the cost of the restriction -- withdraw, lose the thread, propose
    // again to swap one category -- bought nothing.
    const editModal = document.getElementById('editModal');
    const editForm = document.getElementById('editForm');
    const editTimeline = document.getElementById('editTimeline');
    const editStartsOn = document.getElementById('editStartsOn');
    const editEndsOn = document.getElementById('editEndsOn');
    const editMessage = document.getElementById('editMessage');
    const editError = document.getElementById('editError');
    const editSubmit = document.getElementById('editSubmit');
    let editing = null;

    async function fillTimelines(select, chosen) {
        if (select.dataset.filled) {
            select.value = chosen || '';
            return;
        }
        try {
            const data = await window.api('/api/categories');
            select.innerHTML = '<option value="">No timeline</option>'
                + (data.timelines || []).map((t) =>
                    `<option value="${esc(t.slug)}">${esc(t.label)}</option>`).join('');
            select.dataset.filled = '1';
        } catch {
            // The field is optional; leaving it as-is is better than
            // refusing to open the dialog over it.
        }
        select.value = chosen || '';
    }

    // Amounts, for the same window in which anything else can be corrected.
    // Built from the structured terms the proposal already carries, so this
    // dialog does not need its own copy of the unit vocabulary beyond the
    // labels to name them.
    let editUnits = [];
    let editDefaults = {};
    let editGroups = [];
    let editMe = null;
    const editQuantities = { proposer: {}, recipient: {} };
    // What each side gives, as edited. Seeded from the proposal in openEdit.
    const editGives = { proposer: new Set(), recipient: new Set() };

    async function loadUnits() {
        if (editUnits.length) return;
        try {
            const [data, meData] = await Promise.all([
                window.api('/api/categories'),
                window.api('/api/me'),
            ]);
            editUnits = data.units || [];
            editDefaults = data.default_units || {};
            editGroups = data.groups || [];
            editMe = meData.organization;
        } catch {
            // The amounts and pickers simply do not render; everything else
            // in the dialog still works.
        }
    }

    function editLabel(slug) {
        for (const group of editGroups) {
            const hit = (group.categories || []).find((c) => c.slug === slug);
            if (hit) return hit.label;
        }
        return slug;
    }

    // The two give/receive pickers. Each column offers exactly what that
    // side's profile lists -- the same rule the server enforces -- and
    // starts checked at what the proposal currently says.
    // The two columns are "you provide" and "they provide", whichever party
    // is editing. Internally they stay keyed proposer/recipient -- the
    // markup's ids and counters are -- so the mapping onto the proposal's
    // actual sides happens once, on submit. `you_give` and `you_receive`
    // are already from the viewer's point of view.
    function buildEditPickers(proposal) {
        const columns = [
            ['proposer', document.getElementById('editProposerGives'),
             new Set((editMe && editMe.offers) || []), proposal.you_give || []],
            ['recipient', document.getElementById('editRecipientGives'),
             new Set((proposal.counterpart && proposal.counterpart.offers) || []),
             proposal.you_receive || []],
        ];
        columns.forEach(([side, container, allowed, chosen]) => {
            if (!container) return;
            container.innerHTML = '';
            editGives[side] = new Set(chosen.filter((slug) => allowed.has(slug)));
            if (allowed.size === 0) {
                container.innerHTML = '<p class="picker-empty">Nothing listed yet.</p>';
                paintEditCounts();
                return;
            }
            editGroups.forEach((group) => {
                const options = (group.categories || []).filter((c) => allowed.has(c.slug));
                if (options.length === 0) return;
                const wrap = document.createElement('div');
                wrap.className = 'category-group';
                wrap.innerHTML = `<h4>${esc(group.name)}</h4>`;
                const row = document.createElement('div');
                row.className = 'category-options';
                options.forEach((c) => {
                    const id = `edit-${side}-${c.slug}`;
                    const on = editGives[side].has(c.slug);
                    const label = document.createElement('label');
                    label.className = `category-chip${on ? ' checked' : ''}`;
                    label.setAttribute('for', id);
                    label.innerHTML = `
                        <input type="checkbox" id="${id}" value="${esc(c.slug)}"${on ? ' checked' : ''}>
                        <span>${esc(c.label)}</span>`;
                    row.appendChild(label);
                });
                wrap.appendChild(row);
                container.appendChild(wrap);
            });
            container.onchange = (e) => {
                const box = e.target.closest('input[type="checkbox"]');
                if (!box) return;
                if (box.checked) editGives[side].add(box.value);
                else editGives[side].delete(box.value);
                box.closest('.category-chip').classList.toggle('checked', box.checked);
                paintEditCounts();
                renderEditAmounts();
            };
        });
        paintEditCounts();
    }

    function paintEditCounts() {
        Object.entries(editGives).forEach(([side, set]) => {
            const counter = editForm.querySelector(`.picker-count[data-for="${side}"]`);
            if (counter) {
                counter.textContent = set.size === 0 ? 'None selected' : `${set.size} selected`;
            }
        });
    }

    // Seeds the amounts from the proposal's structured terms, once per open;
    // rows are then drawn from whatever is currently checked, so a category
    // added in the picker gets an amount row and one removed loses it.
    function seedEditQuantities(proposal) {
        editQuantities.proposer = {};
        editQuantities.recipient = {};
        [['proposer', proposal.you_give_terms], ['recipient', proposal.you_receive_terms]]
            .forEach(([side, terms]) => {
                (terms || []).forEach((term) => {
                    editQuantities[side][term.slug] = {
                        amount: term.amount, unit: term.unit, detail: term.detail,
                    };
                });
            });
    }

    function renderEditAmounts() {
        const host = document.getElementById('editAmounts');
        if (!host || !editUnits.length) return;

        const rows = [];
        [['proposer', 'You provide'], ['recipient', 'They provide']]
        .forEach(([side, heading]) => {
            const slugs = [...editGives[side]];
            if (!slugs.length) return;
            rows.push(`<h4>${esc(heading)}</h4>`);
            slugs.forEach((slug) => {
                const held = editQuantities[side][slug] || {};
                const term = { slug, label: editLabel(slug), amount: held.amount,
                               unit: held.unit, detail: held.detail };
                const unit = term.unit || editDefaults[term.slug] || 'items';
                const options = editUnits.map((u) => `
                    <option value="${esc(u.slug)}"${u.slug === unit ? ' selected' : ''}>${
                        esc(u.slug === 'other' ? 'other...' : u.label)}</option>`).join('');
                rows.push(`
                    <div class="amount-row">
                        <span class="amount-label">${esc(term.label)}</span>
                        <input type="number" class="amount-value" min="0.01" step="any"
                               data-side="${esc(side)}" data-slug="${esc(term.slug)}"
                               value="${term.amount ?? ''}" placeholder="—"
                               aria-label="Amount of ${esc(term.label)}">
                        <select class="amount-unit" data-side="${esc(side)}"
                                data-slug="${esc(term.slug)}"
                                aria-label="Unit">${options}</select>
                        <input type="text" class="amount-detail"
                               data-side="${esc(side)}" data-slug="${esc(term.slug)}"
                               value="${esc(term.detail || '')}" placeholder="unit"
                               maxlength="100" aria-label="Unit name"
                               ${unit === 'other' ? '' : 'hidden'}>
                    </div>`);
            });
        });

        host.hidden = rows.length === 0;
        host.innerHTML = rows.join('');
    }

    const editAmountsHost = document.getElementById('editAmounts');
    if (editAmountsHost) {
        editAmountsHost.addEventListener('input', (e) => {
            const el = e.target.closest('[data-side][data-slug]');
            if (!el) return;
            const { side, slug } = el.dataset;
            const held = editQuantities[side][slug] || {};
            if (el.classList.contains('amount-value')) {
                held.amount = el.value === '' ? null : Number(el.value);
            } else if (el.classList.contains('amount-unit')) {
                held.unit = el.value;
                const detail = editAmountsHost.querySelector(
                    `.amount-detail[data-side="${side}"][data-slug="${slug}"]`);
                if (detail) detail.hidden = el.value !== 'other';
            } else if (el.classList.contains('amount-detail')) {
                held.detail = el.value.trim() || null;
            }
            editQuantities[side][slug] = held;
        });
    }

    // The first amount that is filled in and not above zero, as
    // {slug, input}, or null. Blank is fine.
    function firstBadEditAmount() {
        for (const [side, entries] of Object.entries(editQuantities)) {
            for (const [slug, q] of Object.entries(entries)) {
                if (!editGives[side].has(slug)) continue;
                if (q.amount === null || q.amount === undefined || q.amount === '') continue;
                if (Number(q.amount) > 0) continue;
                const input = editAmountsHost && editAmountsHost.querySelector(
                    `.amount-value[data-side="${side}"][data-slug="${slug}"]`);
                return { slug, input: input || editSubmit };
            }
        }
        return null;
    }

    function editQuantitiesFor(side) {
        const out = {};
        Object.entries(editQuantities[side]).forEach(([slug, q]) => {
            if (!editGives[side].has(slug)) return;
            if (q.amount === null || q.amount === undefined || q.amount === '') return;
            out[slug] = {
                amount: q.amount,
                unit: q.unit || editDefaults[slug] || 'items',
                detail: q.detail || null,
            };
        });
        return out;
    }

    async function openEdit(proposal) {
        editing = proposal;
        editError.hidden = true;
        editError.textContent = '';
        // Countering is the same form with a different framing: the change
        // is the answer, and it goes to the other side to accept.
        const countering = Boolean(proposal.awaiting_you);
        const title = document.getElementById('editModalTitle');
        const intro = editModal.querySelector('.modal-intro');
        if (title) title.textContent = countering ? 'Suggest different terms' : 'Edit proposal';
        if (intro) {
            intro.textContent = countering
                ? `Change anything below and send it back. ${proposal.counterpart.name} `
                  + 'can then accept these terms, decline, or suggest their own. '
                  + 'Each side can only be committed to things it lists on its profile.'
                : 'They have not answered yet, so all of this can still change. '
                  + 'Each side can only be committed to things it lists on its profile.';
        }
        editSubmit.textContent = countering ? 'Send counter-offer' : 'Save changes';
        editStartsOn.value = proposal.starts_on || '';
        editEndsOn.value = proposal.ends_on || '';
        editMessage.value = proposal.message || '';
        await fillTimelines(editTimeline, proposal.timeline);
        await loadUnits();
        seedEditQuantities(proposal);
        buildEditPickers(proposal);
        renderEditAmounts();

        window.showDialog(editModal, editStartsOn);
        editOpenedAs = editSnapshot();
    }

    // What the form held when it opened, so closing can tell a form that
    // was looked at from one that was worked on.
    let editOpenedAs = '';

    function editSnapshot() {
        return JSON.stringify({
            gives: [...editGives.proposer].sort(),
            gets: [...editGives.recipient].sort(),
            quantities: editQuantities,
            timeline: editTimeline.value,
            starts: editStartsOn.value,
            ends: editEndsOn.value,
            message: editMessage.value,
        });
    }

    function closeEdit({ force = false } = {}) {
        if (!editing) return;
        // A backdrop click or a stray Escape used to drop a half-written
        // counter-offer without a word; now it asks.
        if (!force && editSnapshot() !== editOpenedAs
                && !window.confirm(
                    'Discard these changes? What you have filled in will '
                    + 'be lost.')) {
            return;
        }
        editing = null;
        window.hideDialog(editModal);
    }

    if (editModal) {
        editModal.querySelector('.close-modal')
            .addEventListener('click', closeEdit);
        document.getElementById('editCancel')
            .addEventListener('click', closeEdit);
        editModal.addEventListener('click', (e) => {
            if (e.target === editModal) closeEdit();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && editModal.classList.contains('active')) {
                closeEdit();
            }
        });

        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!editing) return;
            editError.hidden = true;

            // The server says the same thing, but from here it is one line.
            if (editGives.proposer.size === 0 || editGives.recipient.size === 0) {
                editError.textContent = 'A partnership needs something from '
                    + 'both sides. Pick at least one thing you will provide '
                    + 'and one thing you are asking for.';
                editError.hidden = false;
                return;
            }

            // Same rule the server applies to an amount: above zero. This
            // form is novalidate, so the input's min does nothing on its own.
            const badAmount = firstBadEditAmount();
            if (badAmount) {
                editError.textContent = `${editLabel(badAmount.slug)}: enter an `
                    + 'amount above 0, or leave it blank.';
                editError.hidden = false;
                badAmount.input.focus();
                return;
            }

            const idle = editSubmit.textContent;
            editSubmit.disabled = true;
            editSubmit.textContent = 'Saving...';
            // The dialog's "you"/"they" columns map onto the proposal's real
            // sides according to which party is editing.
            const iAmProposer = editing.direction === 'outgoing';
            const mine = iAmProposer ? 'proposer' : 'recipient';
            const theirs = iAmProposer ? 'recipient' : 'proposer';
            const countering = Boolean(editing.awaiting_you);
            try {
                await window.api(`/api/proposals/${editing.id}`, {
                    method: 'PATCH',
                    body: {
                        [`${mine}_gives`]: [...editGives.proposer],
                        [`${theirs}_gives`]: [...editGives.recipient],
                        timeline: editTimeline.value,
                        starts_on: editStartsOn.value,
                        ends_on: editEndsOn.value,
                        [`${mine}_quantities`]: editQuantitiesFor('proposer'),
                        [`${theirs}_quantities`]: editQuantitiesFor('recipient'),
                        message: editMessage.value.trim(),
                    },
                });
                const name = editing.counterpart.name;
                closeEdit({ force: true });
                if (countering) activateTab('outgoing');
                await load();
                window.toast(countering
                    ? `Counter-offer sent. ${name} has been asked to answer it.`
                    : `Proposal updated. ${name} has been told.`);
                document.dispatchEvent(new CustomEvent('partnerships:changed'));
            } catch (error) {
                // Answered while it was being corrected. There is nothing
                // left to edit and no field to focus, so this leaves the
                // dialog rather than reporting a validation problem the
                // form cannot fix -- the same reasoning as the respond
                // dialog below.
                if (error.status === 409) {
                    closeEdit({ force: true });
                    await load();
                    window.toast(error.message, 'error');
                    return;
                }
                editError.textContent = error.message;
                editError.hidden = false;
                const field = error.data && error.data.field;
                if (field === 'starts_on') editStartsOn.focus();
                else if (field === 'ends_on') editEndsOn.focus();
            } finally {
                editSubmit.disabled = false;
                editSubmit.textContent = idle;
            }
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

        if (act === 'messages') {
            await openThread(proposal);
            return;
        }

        if (act === 'edit') {
            openEdit(proposal);
            return;
        }

        if (act === 'copy') {
            const url = `${location.origin}/partnership.html?token=${
                encodeURIComponent(proposal.share_token)}`;
            try {
                await navigator.clipboard.writeText(url);
                btn.textContent = 'Copied';
                setTimeout(() => { btn.textContent = 'Copy link'; }, 1500);
            } catch {
                // No clipboard access (an insecure origin, or permission
                // refused). The agreement page is one click away and its
                // address bar holds the same link, which beats a bare
                // prompt() dialog nobody else on this site uses.
                window.toast('Could not copy automatically. Open "View '
                    + 'agreement" and copy the address from your browser.',
                'error');
            }
            return;
        }

        // Accept is the step that creates a binding-looking agreement and mints
        // a public link, so it is confirmed rather than fired on one click.
        // The name rides along for the confirmation toast: by the time the
        // response lands, load() has re-rendered the list and this
        // proposal's card may have moved to another tab entirely.
        // Rotating and revoking a link both change what a URL somebody else
        // may be holding does, so both confirm here rather than firing on
        // one click -- through this same dialog, not window.confirm(),
        // which was the one native dialog left on a site that styles every
        // other one.
        const hadLink = Boolean(proposal.share_token);
        pending = { id, action: act, name: proposal.counterpart.name, hadLink };
        respondTitle.textContent = {
            accept: `Accept partnership with ${proposal.counterpart.name}?`,
            decline: proposal.countered && proposal.direction === 'outgoing'
                ? `Decline ${proposal.counterpart.name}'s counter-offer?`
                : `Decline proposal from ${proposal.counterpart.name}?`,
            withdraw: `Withdraw your proposal to ${proposal.counterpart.name}?`,
            complete: `Mark your partnership with ${proposal.counterpart.name} complete?`,
            end: `End your partnership with ${proposal.counterpart.name}?`,
            rotate: hadLink
                ? `Create a new link for your partnership with ${proposal.counterpart.name}?`
                : `Create a public link for your partnership with ${proposal.counterpart.name}?`,
            unshare: `Remove the public link for your partnership with ${proposal.counterpart.name}?`,
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
        } else if (act === 'rotate') {
            respondTerms.innerHTML = hadLink
                ? `<p class="respond-note">The current link will stop working `
                  + `for everyone who has it, including `
                  + `${esc(proposal.counterpart.name)}. They are told a new `
                  + `one was made.</p>`
                : `<p class="respond-note">Anyone with the link will be able `
                  + `to read the agreement summary: both organization names `
                  + `and the terms, but no contact details.</p>`;
        } else if (act === 'unshare') {
            respondTerms.innerHTML =
                `<p class="respond-note">It will stop working for everyone `
                + `who has it. The agreement itself stays, and either of you `
                + `can create a new link later.</p>`;
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
            ['withdraw', 'complete', 'rotate', 'unshare'].includes(act) ? 'none' : '';
        const messageLabel = respondMessage.parentElement.querySelector('label');
        if (messageLabel) {
            messageLabel.textContent = act === 'end'
                ? 'Why are you ending it? (optional)'
                : 'Add a note (optional)';
        }
        respondConfirm.textContent = {
            accept: 'Accept partnership', decline: 'Decline', withdraw: 'Withdraw',
            complete: 'Mark complete', end: 'End partnership',
            rotate: hadLink ? 'Create new link' : 'Create link',
            unshare: 'Remove link',
        }[act];
        respondConfirm.className =
            ['accept', 'complete', 'rotate'].includes(act) ? 'btn-primary' : 'btn-danger';
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

        if (action === 'rotate' || action === 'unshare') {
            const isNew = action === 'rotate';
            try {
                await window.api(`/api/proposals/${pending.id}/share`,
                    { method: isNew ? 'POST' : 'DELETE' });
                closeModal();
                await load();
                window.toast(!isNew
                    ? 'Public link removed.'
                    : (pending.hadLink
                        ? 'New link created. The previous one no longer works.'
                        : 'Public link created.'));
            } catch (error) {
                closeModal();
                // A 409 means the proposal is no longer one with a public
                // link -- withdrawn or declined since this list was drawn --
                // so the card offering the control is itself out of date.
                if (error.status === 409) await load();
                window.toast(error.message || 'Could not change that link.',
                    'error');
            } finally {
                respondConfirm.disabled = false;
                pending = null;
            }
            return;
        }

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
            // A 409 here is not the user getting something wrong. It is the
            // proposal having moved while this dialog was open: the other
            // side accepted or declined a moment ago, or the partner ended
            // it, or this is a second click on a button that already worked.
            // The server is right to refuse -- see the status guards on the
            // lifecycle routes -- but showing the refusal inside a dialog
            // that still offers to Accept, above a list still showing the
            // old state, presents somebody else's action as this person's
            // mistake.
            //
            // So the dialog closes, the list is refetched, and the message
            // is said as a toast. The server's wording already names the
            // state it found ("This proposal was already accepted"), which
            // is the one thing this could not work out for itself.
            if (error.status === 409) {
                closeModal();
                await load();
                window.toast(error.message, 'error');
                document.dispatchEvent(new CustomEvent('partnerships:changed'));
            } else {
                // Everything else -- a validation refusal, a network blip --
                // is about what was typed here, so it stays here, above the
                // terms rather than in place of them: replacing the block
                // also threw away the delivery radios, so a retry after a
                // blip on "Mark complete" would have sent no verdict.
                let note = respondTerms.querySelector(':scope > .form-message');
                if (!note) {
                    note = document.createElement('p');
                    note.className = 'form-message';
                    respondTerms.prepend(note);
                }
                note.textContent = error.message;
                // `pending` is deliberately kept: the dialog is still open
                // and the button still says Accept, so it has to work.
                respondConfirm.disabled = false;
                return;
            }
        }
        respondConfirm.disabled = false;
        pending = null;
    });

    // --- Modal ----------------------------------------------------------
    // Focus is common.js's dialogOpened/dialogClosed: trapped inside while
    // open, returned to the Accept/Decline/Withdraw button on close.
    function openModal() {
        // The note, not the confirm button: this dialog is a decision, and
        // landing on the control that commits it invites a stray Enter.
        window.showDialog(modal, respondMessage);
    }

    function closeModal() {
        window.hideDialog(modal);
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
    function paintTabs() {
        tabs.forEach((t) => {
            const on = t.dataset.tab === activeTab;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', String(on));
            // Roving tabindex: Tab lands on the selected tab, the arrows
            // move within the set.
            t.tabIndex = on ? 0 : -1;
        });
        const selected = tabs.find((t) => t.dataset.tab === activeTab);
        if (selected && selected.id) list.setAttribute('aria-labelledby', selected.id);
    }

    function activateTab(tab) {
        activeTab = tab;
        paintTabs();
        render();
    }

    tabs.forEach((t, i) => {
        t.addEventListener('click', () => activateTab(t.dataset.tab));
        t.addEventListener('keydown', (e) => {
            const step = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: tabs.length - 1 - i }[e.key];
            if (step === undefined) return;
            e.preventDefault();
            const next = tabs[(i + step + tabs.length) % tabs.length];
            next.focus();
            activateTab(next.dataset.tab);
        });
    });

    // Deep link into a tab, e.g. ppdashboard.html#agreed, or straight into
    // one conversation: #messages-<proposal id>, which is what the "you have
    // a new message" email and the notification bell link to. Without this
    // the link landed on whichever tab happened to be first and left the
    // reader to find the thread they had just been emailed about.
    const TAB_NAMES = ['incoming', 'outgoing', 'agreed', 'closed'];

    async function openThreadFromHash(wanted) {
        let proposal = proposals.find((p) => p.id === wanted);
        if (!proposal) {
            // The list holds everything live and only the newest slice of
            // the archive, so a link into an older settled thread -- a
            // message notification on a partnership that ended last year
            // -- found nothing and said the conversation was gone. Ask for
            // the one proposal instead; it answers 404 only if it really is.
            try {
                const data = await window.api(`/api/proposals/${wanted}`);
                proposal = data.proposal;
            } catch {
                proposal = null;
            }
        }
        if (!proposal) {
            // Party to it no longer, or it was deleted with the other
            // organization's account. Saying so beats a dialog that never
            // opens for reasons the page does not explain.
            window.toast('That conversation is no longer available.', 'error');
            return;
        }
        // The thread may sit under any of the four tabs, and the one it is
        // under is the one that should be showing behind it when the dialog
        // is closed. Pending ones split by whose turn it is, not by who
        // sent them: a counter-offer waiting on the proposer sits under
        // Incoming for the proposer, whatever direction it started in.
        const tabFor = {
            pending: proposal.awaiting_you ? 'incoming' : 'outgoing',
            accepted: 'agreed',
        }[proposal.status] || 'closed';
        activateTab(tabFor);
        if (openThreadId === proposal.id) return;   // already looking at it
        if (openThreadId !== null) closeThread();
        openThread(proposal);
    }

    const hash = location.hash.replace('#', '');
    if (TAB_NAMES.includes(hash)) {
        activeTab = hash;
        paintTabs();
    }
    const threadMatch = /^messages-(\d+)$/.exec(hash);

    await load();

    if (threadMatch) openThreadFromHash(Number(threadMatch[1]));

    // The same links, followed while already on this page. The bell in the
    // nav points at ppdashboard.html#incoming and #messages-<id>; from the
    // dashboard itself those are same-document navigations, which fire no
    // load and, until this, changed nothing but the address bar. A thread
    // link is preceded by a reload, because the notification that led here
    // usually exists precisely because something changed since `proposals`
    // was fetched.
    window.addEventListener('hashchange', async () => {
        const next = location.hash.replace('#', '');
        if (TAB_NAMES.includes(next)) {
            if (openThreadId !== null) closeThread();
            activateTab(next);
            return;
        }
        const thread = /^messages-(\d+)$/.exec(next);
        if (!thread) return;
        await load();
        openThreadFromHash(Number(thread[1]));
    });
});
