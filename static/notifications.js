// The notification bell in the nav.
//
// The nav has carried a count for a while, and a count only says that
// something is waiting -- not what, or from whom. The only way to find out
// was to open the dashboard and work it out by comparing it against memory.
// And the events that are not waiting on anybody (a proposal accepted, a
// partnership the other side ended) were never surfaced at all: they went out
// by email and nowhere else, which is a silent product for as long as
// outbound mail is not a working channel.
//
// The markup is built here rather than added to fifteen page templates. It
// only exists for a signed-in visitor, common.js already resolves that on
// every page, and a nav element that is defined in one file cannot drift
// between pages.
//
// Nothing is fetched until the bell is opened. The dot beside it reuses the
// counts /api/me already returns, so an idle page costs no extra request.

(() => {
    const RELATIVE = [
        [60, 'just now', null],
        [3600, null, 60],
        [86400, null, 3600],
        [2592000, null, 86400],
    ];

    function ago(iso) {
        const then = new Date(iso);
        if (Number.isNaN(then.getTime())) return '';
        const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000);
        if (seconds < 60) return 'Just now';
        if (seconds < 3600) {
            const m = Math.round(seconds / 60);
            return `${m} min ago`;
        }
        if (seconds < 86400) {
            const h = Math.round(seconds / 3600);
            return `${h} hour${h === 1 ? '' : 's'} ago`;
        }
        const d = Math.round(seconds / 86400);
        if (d === 1) return 'Yesterday';
        if (d < 30) return `${d} days ago`;
        return then.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    }

    // One sentence per kind. Written here rather than server-side for the
    // same reason the dashboard's activity feed writes its own: the wording
    // belongs with the rest of the wording.
    function describe(item) {
        const who = item.counterpart || 'An organization';
        switch (item.kind) {
            case 'proposal_received':
                return { icon: 'bx-envelope', text: `${who} proposed a partnership` };
            case 'proposal_countered':
                return {
                    icon: 'bx-transfer-alt',
                    text: `${who} suggested different terms — accept, decline or counter`,
                };
            case 'proposal_accepted':
                return { icon: 'bx-check-circle', text: `${who} accepted your proposal` };
            case 'proposal_declined':
                return { icon: 'bx-x-circle', text: `${who} declined your proposal` };
            case 'proposal_withdrawn':
                return { icon: 'bx-undo', text: `${who} withdrew their proposal` };
            case 'partnership_completed':
                return { icon: 'bx-check-double', text: `Your partnership with ${who} is complete` };
            case 'completion_marked':
                return {
                    icon: 'bx-time-five',
                    text: `${who} marked your partnership complete — confirm to close it`,
                };
            case 'partnership_ended':
                return { icon: 'bx-stop-circle', text: `${who} ended your partnership` };
            case 'meeting_proposed':
                return {
                    icon: 'bx-calendar-event',
                    text: `${who} proposed a meeting — accept, suggest a time, or decline`,
                };
            case 'message':
                return {
                    icon: 'bx-message-dots',
                    text: item.count > 1
                        ? `${item.count} new messages from ${who}`
                        : `${who} sent you a message`,
                };
            default:
                return { icon: 'bx-bell', text: `Something happened with ${who}` };
        }
    }

    // Placeholder rows, sized like real notification rows. The panel used to
    // say "Loading..." here, which is the one loading state on this site that
    // was a sentence rather than a shape -- directory.js, proposals.js and
    // ppdashboard.js all draw skeletons, and the odd one out reads as a
    // different kind of waiting than it is.
    //
    // Three, matching the number of rows the panel shows without scrolling.
    // aria-hidden because they are decoration: what a screen reader gets is
    // the status region below, once there is something true to say.
    const SKELETON_ROWS = Array.from({ length: 3 }, () => `
        <li class="notify-skeleton" aria-hidden="true">
            <span class="skeleton skeleton-line notify-skeleton-text"></span>
            <span class="skeleton skeleton-line notify-skeleton-when"></span>
        </li>`).join('');

    function build(slot) {
        const wrap = document.createElement('div');
        wrap.className = 'nav-notify';
        wrap.innerHTML = `
            <button type="button" class="notify-button" id="notifyToggle"
                    aria-haspopup="true" aria-expanded="false"
                    aria-controls="notifyDropdown" aria-label="Notifications">
                <i class='bx bx-bell' aria-hidden="true"></i>
                <span class="notify-dot" id="notifyDot" hidden></span>
            </button>
            <div class="notify-dropdown" id="notifyDropdown" hidden
                 role="region" aria-label="Notifications">
                <div class="notify-head">
                    <span>Notifications</span>
                    <!-- The work still waiting, as words. The dot on the
                         bell is only what is new since the panel was last
                         opened; this is what has not been answered. -->
                    <span class="notify-waiting" id="notifyWaiting" hidden></span>
                </div>
                <ul class="notify-list" id="notifyList">${SKELETON_ROWS}</ul>
                <!-- The list arrives after the panel opens, so opening it
                     and hearing "Loading..." was the end of the story: the
                     items replacing that line announce nothing. Said on a
                     region of its own rather than on the list, which would
                     read every notification out again on each open -- and
                     the panel refetches on every open, deliberately.

                     Inside the dropdown, so it is only in the accessibility
                     tree while the panel is showing. setOpen unhides the
                     panel before it fetches, so the region is present by the
                     time this is written to. -->
                <p id="notifyStatus" class="sr-only" role="status"
                   aria-live="polite" aria-atomic="true"></p>
            </div>`;
        // Before the account menu, so the bar reads: what happened, then who
        // you are.
        slot.parentNode.insertBefore(wrap, slot);
        return wrap;
    }

    function render(list, items, actionable) {
        const waiting = document.getElementById('notifyWaiting');
        const status = document.getElementById('notifyStatus');
        if (status) {
            status.textContent = items.length === 0
                ? 'No new notifications.'
                : `${items.length} notification${
                    items.length === 1 ? '' : 's'}${
                    actionable ? `, ${actionable} waiting on you` : ''}.`;
        }
        if (waiting) {
            waiting.hidden = !actionable;
            waiting.textContent = actionable
                ? `${actionable} waiting on you` : '';
        }
        if (!items.length) {
            list.innerHTML =
                '<li class="notify-empty">Nothing new. Proposals and replies '
                + 'show up here.</li>';
            return;
        }
        const esc = window.escapeHtml;
        // escapeHtml keeps the value inside the attribute; it does not decide
        // whether the attribute is safe to follow. Escaping a
        // "javascript:..." href produces a perfectly well-formed href that
        // still runs script on click, because none of the five characters it
        // rewrites appear in one -- so the quoting is not what is protecting
        // this, and it never was.
        //
        // Today every href here is built by the server as
        // "ppdashboard.html#<tab>" (see app.py), which is why this has been
        // fine. That is a fact about one f-string, not a property of the
        // endpoint, and the fix belongs at the sink either way: this is the
        // one place in the codebase where a URL reaches an href without a
        // scheme check, organization.js having grown exactly this guard for
        // exactly this reason.
        //
        // Relative paths only, since that is all a notification target ever
        // is. Anything carrying a scheme -- or a protocol-relative "//host"
        // that would leave the site without one -- is dropped rather than
        // rewritten, and the entry renders as plain text.
        const safeHref = (url) => {
            const value = String(url || '');
            return (value && !/^[a-z][a-z0-9+.-]*:/i.test(value)
                    && !value.startsWith('//')) ? value : null;
        };
        list.innerHTML = items.map((item) => {
            const { icon, text } = describe(item);
            const href = safeHref(item.href);
            const classes = [
                item.actionable ? 'is-actionable' : '',
                item.seen ? 'is-seen' : '',
            ].filter(Boolean).join(' ');
            // An entry whose target was refused still says what happened;
            // it just is not a link. Dropping the row instead would hide the
            // notification, which is the one thing it exists to do.
            const body = `
                        <i class='bx ${esc(icon)}' aria-hidden="true"></i>
                        <span class="notify-text">${esc(text)}</span>
                        <span class="notify-when">${esc(ago(item.at))}</span>`;
            // News can be cleared one entry at a time; work cannot -- an
            // entry waiting on this organization stays until it is
            // answered, so it gets no dismiss control.
            const dismiss = !item.actionable && item.key
                ? `<button type="button" class="notify-dismiss"
                           data-dismiss="${esc(item.key)}"
                           aria-label="Dismiss: ${esc(text)}">&times;</button>`
                : '';
            return `
                <li class="${classes}" data-key="${esc(item.key || '')}">
                    ${href
                        ? `<a href="${esc(href)}">${body}</a>`
                        : `<span class="notify-plain">${body}</span>`}
                    ${dismiss}
                </li>`;
        }).join('');
    }

    // Exported so common.js can set the dot from the counts it already has,
    // without this file making a request of its own on every page load.
    window.setNotificationDot = function setNotificationDot(count) {
        const dot = document.getElementById('notifyDot');
        if (!dot) return;
        dot.hidden = !(count > 0);
        dot.textContent = count > 9 ? '9+' : String(count || '');
    };

    window.mountNotificationBell = function mountNotificationBell() {
        const slot = document.getElementById('navAccount');
        if (!slot || document.getElementById('notifyToggle')) return;

        build(slot);
        const toggle = document.getElementById('notifyToggle');
        const dropdown = document.getElementById('notifyDropdown');
        const list = document.getElementById('notifyList');
        // Whether anything has ever been drawn here. Not a "do not fetch
        // again" latch, which is what this used to be: the panel was
        // populated on the first open and never afterward, so acting on
        // everything in it and opening it again showed the same list, and a
        // proposal that arrived while the page sat open never appeared at
        // all. It now refetches on every open; this only decides whether
        // there is anything worth leaving on screen while that happens.
        let everRendered = false;
        let fetching = false;

        const setOpen = async (open) => {
            dropdown.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            if (!open) return;
            // Two opens in quick succession should not race each other into
            // the list; the one already running will paint.
            if (fetching) return;
            // Only on a first open. On every open after it the previous list
            // stays put until the new one is ready, so the panel does not
            // blink through a loading state to arrive at what it was
            // already showing.
            if (!everRendered) {
                list.innerHTML = SKELETON_ROWS;
            }
            fetching = true;
            try {
                // Opening the panel is reading it. The list is fetched and
                // marked seen in one call, so the dot -- which counts what
                // is new since the panel was last opened -- clears the
                // moment the reader has been shown what it was counting.
                // Entries that are still waiting on an answer keep their
                // flag and styling in the list; seen is not done.
                const data = await window.api('/api/notifications/read',
                                              { method: 'POST' });
                render(list, data.notifications || [], data.actionable || 0);
                everRendered = true;
                if (window.setNotificationDot) window.setNotificationDot(0);
            } catch {
                // Only when there is nothing better to show. Replacing a
                // list the reader is looking at with an error, because a
                // background refresh of it failed, loses more than it says.
                if (!everRendered) {
                    list.innerHTML =
                        '<li class="notify-empty">Could not load these just '
                        + 'now.</li>';
                }
            } finally {
                fetching = false;
            }
        };

        toggle.addEventListener('click', (e) => {
            // Without this the document listener below sees the same click
            // and closes the panel in the tick it was opened.
            e.stopPropagation();
            setOpen(dropdown.hidden);
        });

        document.addEventListener('click', (e) => {
            if (dropdown.hidden) return;
            if (!dropdown.contains(e.target) && !toggle.contains(e.target)) {
                setOpen(false);
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || dropdown.hidden) return;
            setOpen(false);
            toggle.focus();
        });

        // Every item links to ppdashboard.html#<tab or thread>. From the
        // dashboard itself that is a same-document navigation, which the
        // dashboard handles through `hashchange` -- except that the browser
        // fires none when the hash is already what the link names, so a
        // thread opened from here, closed, and clicked again did nothing.
        // Dispatching the event by hand makes the second click work like the
        // first; every other case is left to the browser.
        list.addEventListener('click', async (e) => {
            const dismiss = e.target.closest('button[data-dismiss]');
            if (dismiss) {
                e.stopPropagation();
                const row = dismiss.closest('li');
                dismiss.disabled = true;
                try {
                    await window.api('/api/notifications/dismiss',
                                     { method: 'POST', body: { key: dismiss.dataset.dismiss } });
                } catch (error) {
                    dismiss.disabled = false;
                    window.toast(error.message || 'Could not dismiss that.', 'error');
                    return;
                }
                row.remove();
                if (!list.querySelector('li')) {
                    list.innerHTML = '<li class="notify-empty">Nothing new. '
                        + 'Proposals and replies show up here.</li>';
                }
                return;
            }
            const link = e.target.closest('a[href]');
            if (!link) return;
            setOpen(false);
            const target = new URL(link.href, location.href);
            if (target.pathname === location.pathname
                    && target.hash && target.hash === location.hash) {
                e.preventDefault();
                window.dispatchEvent(new HashChangeEvent('hashchange'));
            }
        });
    };
})();
