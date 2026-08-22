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
                <div class="notify-head">Notifications</div>
                <ul class="notify-list" id="notifyList">
                    <li class="notify-empty">Loading...</li>
                </ul>
            </div>`;
        // Before the account menu, so the bar reads: what happened, then who
        // you are.
        slot.parentNode.insertBefore(wrap, slot);
        return wrap;
    }

    function render(list, items) {
        if (!items.length) {
            list.innerHTML =
                '<li class="notify-empty">Nothing new. Proposals and replies '
                + 'show up here.</li>';
            return;
        }
        const esc = window.escapeHtml;
        list.innerHTML = items.map((item) => {
            const { icon, text } = describe(item);
            return `
                <li class="${item.actionable ? 'is-actionable' : ''}">
                    <a href="${esc(item.href)}">
                        <i class='bx ${esc(icon)}' aria-hidden="true"></i>
                        <span class="notify-text">${esc(text)}</span>
                        <span class="notify-when">${esc(ago(item.at))}</span>
                    </a>
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
        let loaded = false;

        const setOpen = async (open) => {
            dropdown.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            if (!open || loaded) return;
            try {
                const data = await window.api('/api/notifications');
                render(list, data.notifications || []);
                loaded = true;
            } catch {
                list.innerHTML =
                    '<li class="notify-empty">Could not load these just now.</li>';
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
    };
})();
