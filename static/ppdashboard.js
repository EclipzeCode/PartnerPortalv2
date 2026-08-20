// Dashboard.
//
// The stat cards and activity feed used to be hardcoded markup. They are now
// filled from /api/dashboard, which reports the signed-in org's real match
// counts, its top matches and its proposal history.
//
// Meetings are server-backed as of the events table: they arrive with
// /api/dashboard and are written through /api/events. They used to live in
// localStorage, which meant they were not saved at all -- one browser, gone
// with site data, never following the account that made them.

document.addEventListener('DOMContentLoaded', async () => {
    // Only still read to rescue anything left behind by that older version;
    // nothing is ever written here now. See migrateLocalEvents below.
    const EVENTS_KEY = 'partnerPortalEvents';
    const esc = window.escapeHtml;

    const modal = document.getElementById('eventModal');
    const addEventBtn = document.getElementById('addEventBtn');
    const eventForm = document.getElementById('eventForm');
    const eventsList = document.querySelector('.events-list');
    const closeBtn = modal ? modal.querySelector('.close-modal') : null;
    const eventFormError = document.getElementById('eventFormError');
    const eventSubmitBtn = document.getElementById('eventSubmitBtn');

    const activityFilter = document.getElementById('activityFilter');
    const activityViewAll = document.getElementById('activityViewAll');
    const ACTIVITY_COLLAPSED = 4;
    let activityExpanded = false;

    // --- Live data ------------------------------------------------------
    // Set before the await, not after: the stat cards ship with a hardcoded
    // 0 in the markup, and a 0 that is about to become 4 is worse than a
    // blank -- it is a wrong answer presented as a real one. data-loading
    // swaps those numbers for shimmer until the real ones arrive
    // (ppdashboard.css), and the activity feed gets placeholder rows.
    const container = document.querySelector('.dashboard-container');
    const activityList = document.querySelector('.activity-list');
    if (container) container.dataset.loading = 'true';
    if (activityList) {
        activityList.setAttribute('aria-busy', 'true');
        activityList.innerHTML = Array.from({ length: 3 }, () => `
            <div class="activity-item skeleton-activity" aria-hidden="true">
                <div class="skeleton skeleton-dot"></div>
                <div class="skeleton-activity-text">
                    <div class="skeleton skeleton-line"></div>
                    <div class="skeleton skeleton-line short"></div>
                </div>
            </div>
        `).join('');
    }

    const finishLoading = () => {
        if (container) delete container.dataset.loading;
        if (activityList) activityList.removeAttribute('aria-busy');
    };

    let dashboard = null;
    try {
        dashboard = await window.api('/api/dashboard');
    } catch (error) {
        console.error('Could not load dashboard:', error);
        // Leaves the shimmer in place otherwise, which would read as a page
        // that never finishes loading rather than one that failed.
        finishLoading();
        if (activityList) activityList.innerHTML = '';
        return; // api() redirects on 401; anything else leaves the page as-is
    }
    finishLoading();

    const org = dashboard.organization;
    const stats = dashboard.stats;

    // Greeting
    const heading = document.querySelector('.section-header h2');
    if (heading) {
        heading.innerHTML = `Welcome back, <span>${esc(org.name)}</span>`;
    }

    const viewProfileBtn = document.getElementById('viewProfileBtn');
    if (viewProfileBtn) {
        viewProfileBtn.href = `organization.html?id=${encodeURIComponent(org.id)}`;
    }

    // Only surfaced once the profile is finished. Before that, "verify your
    // email" is not the useful message -- an unfinished profile has nothing
    // to propose with, and the toolbar below is already saying so.
    const verifyBanner = document.getElementById('verifyBanner');
    if (verifyBanner && org.email_verified === false && !dashboard.needs_onboarding) {
        const detail = document.getElementById('verifyBannerDetail');
        if (detail) {
            // Only claims proposals are blocked when they actually are.
            detail.textContent = dashboard.verification_required
                ? 'You can browse, edit your profile and answer proposals as '
                  + 'normal — but you will not be able to send a partnership '
                  + 'proposal until your address is confirmed.'
                : 'Confirming it shows partners the address behind your '
                  + 'account is real. Nothing is blocked in the meantime.';
        }
        verifyBanner.hidden = false;
    }

    // Stat cards. The markup labels are updated too, because "Active Partners"
    // and "Partner Score" described numbers that never existed.
    setStat('statMatches', stats.total_matches, 'Matches',
            stats.mutual_matches ? `${stats.mutual_matches} two-way` : 'no two-way yet');
    setStat('statTwoWay', stats.mutual_matches, 'Two-way matches',
            'both sides benefit');
    setStat('statProfileTags', stats.needs_count + stats.offers_count, 'Profile tags',
            `${stats.needs_count} needs · ${stats.offers_count} offers`);
    setStat('savedLeadsCount', stats.saved || 0, 'Saved',
            stats.saved ? 'shortlisted' : 'none yet');
    setStat('profileViews', stats.profile_views || 0, 'Profile views',
            stats.profile_views
                ? `${stats.profile_views_recent || 0} in the last 30 days`
                : 'none yet');

    function setStat(id, value, label, changeText) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = value;
        const content = el.closest('.stat-content');
        if (!content) return;
        const h3 = content.querySelector('h3');
        if (h3 && label) h3.textContent = label;
        const change = content.querySelector('.stat-change');
        if (change && changeText) {
            change.textContent = changeText;
            change.className = 'stat-change' + (value > 0 ? ' positive' : ' neutral');
        }
    }

    // Prompt to finish onboarding rather than showing a page of zeroes.
    const toolbar = document.querySelector('.dashboard-toolbar');
    const toolbarHint = document.getElementById('toolbarHint');
    const editProfileBtn = document.getElementById('editProfileBtn');

    if (dashboard.needs_onboarding) {
        if (toolbar) toolbar.classList.add('needs-profile');
        if (toolbarHint) {
            toolbarHint.textContent =
                'Your profile is not finished yet, so there is nothing to match against.';
        }
        if (editProfileBtn) {
            editProfileBtn.innerHTML = "<i class='bx bx-user-plus'></i> Complete your profile";
        }
    } else if (toolbarHint) {
        const parts = [];
        if (org.organization_type) parts.push(org.organization_type);
        if (org.location) parts.push(org.location);
        toolbarHint.textContent = parts.join(' · ');
    }

    // --- Activity -------------------------------------------------------
    // Built from real records: proposal history (with real timestamps), the
    // org's current top matches, and locally saved meetings. Previously this
    // list was four invented rows of markup.
    function buildActivity() {
        const items = [];

        (dashboard.recent_proposals || []).forEach((p) => {
            const who = `<strong>${esc(p.counterpart.name)}</strong>`;
            const incoming = p.direction === 'incoming';

            items.push({
                kind: 'proposal',
                variant: incoming ? 'incoming' : 'sent',
                icon: incoming ? 'bx-envelope' : 'bx-send',
                text: incoming
                    ? `${who} proposed a partnership`
                    : `You proposed a partnership to ${who}`,
                at: p.created_at
            });

            // The response, whatever it was. A partnership that later
            // completed or ended was still agreed on this date, and that is
            // its own event -- keying every closer off `status` dropped the
            // agreement from the feed the moment it finished.
            if (p.status !== 'pending' && p.responded_at) {
                const agreedOrRefused = ['accepted', 'completed', 'ended']
                    .includes(p.status)
                    ? {
                        icon: 'bx-check-circle',
                        text: `Partnership with ${who} agreed`,
                        variant: 'accepted'
                    }
                    : p.status === 'declined'
                        ? {
                            icon: 'bx-x-circle',
                            variant: 'declined',
                            text: incoming
                                ? `You declined the proposal from ${who}`
                                : `${who} declined your proposal`
                        }
                        : {
                            icon: 'bx-undo',
                            variant: 'withdrawn',
                            text: incoming
                                ? `${who} withdrew their proposal`
                                : `You withdrew your proposal to ${who}`
                        };
                items.push({
                    kind: 'proposal',
                    variant: agreedOrRefused.variant,
                    icon: agreedOrRefused.icon,
                    text: agreedOrRefused.text,
                    at: p.responded_at
                });
            }

            // How it finished, on its own date rather than the date it was
            // agreed -- responded_at is when the recipient accepted, which
            // for a partnership that ran for a year is nowhere near when it
            // closed.
            if (p.status === 'completed' && p.completed_at) {
                items.push({
                    kind: 'proposal',
                    variant: 'completed',
                    icon: 'bx-check-double',
                    text: `Partnership with ${who} completed`,
                    at: p.completed_at
                });
            } else if (p.status === 'ended' && p.ended_at) {
                items.push({
                    kind: 'proposal',
                    variant: 'ended',
                    icon: 'bx-stop-circle',
                    text: p.ended_by_you
                        ? `You ended your partnership with ${who}`
                        : `${who} ended your partnership`,
                    at: p.ended_at
                });
            }
        });

        // Matches are current state rather than events, so they carry no
        // timestamp and sort below anything that actually happened.
        (dashboard.top_matches || []).slice(0, 4).forEach((m) => {
            const gives = (m.match_detail.they_give_labels || [])[0];
            items.push({
                kind: 'match',
                variant: m.match_detail.mutual ? 'mutual' : 'oneway',
                icon: m.match_detail.mutual ? 'bx-transfer' : 'bx-link',
                text: gives
                    ? `<strong>${esc(m.name)}</strong> offers ${esc(gives)}`
                    : `<strong>${esc(m.name)}</strong> could use what you offer`,
                note: `${m.match_score} match${m.match_detail.mutual ? ' · two-way' : ''}`
            });
        });

        loadEvents().forEach((ev) => {
            items.push({
                kind: 'event',
                variant: 'event',
                icon: 'bx-calendar-event',
                text: `Meeting <strong>${esc(ev.title)}</strong> with ${esc(ev.partner)}`,
                at: eventDateTime(ev)
            });
        });

        // Newest first; undated entries keep their order at the end.
        return items.sort((a, b) => {
            if (a.at && b.at) return new Date(b.at) - new Date(a.at);
            if (a.at) return -1;
            if (b.at) return 1;
            return 0;
        });
    }

    // Local datetime for an event; a bare date string would be read as UTC.
    function eventDateTime(ev) {
        if (!ev.date) return null;
        const [y, m, d] = ev.date.split('-').map(Number);
        const [hh, mm] = (ev.time || '00:00').split(':').map(Number);
        return new Date(y, m - 1, d, hh || 0, mm || 0).toISOString();
    }

    function relativeTime(iso) {
        const then = new Date(iso);
        if (Number.isNaN(then.getTime())) return '';

        const diffMs = then - Date.now();
        const future = diffMs > 0;
        const mins = Math.round(Math.abs(diffMs) / 60000);

        if (mins < 1) return 'Just now';
        if (mins < 60) return future ? `In ${mins} min` : `${mins} min ago`;

        const hours = Math.round(mins / 60);
        if (hours < 24) {
            const unit = hours === 1 ? 'hour' : 'hours';
            return future ? `In ${hours} ${unit}` : `${hours} ${unit} ago`;
        }

        const days = Math.round(hours / 24);
        if (days === 1) return future ? 'Tomorrow' : 'Yesterday';
        if (days < 30) return future ? `In ${days} days` : `${days} days ago`;

        return then.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric'
        });
    }

    function renderActivity() {
        const list = document.querySelector('.activity-list');
        if (!list) return;

        const filter = activityFilter ? activityFilter.value : 'all';
        const all = buildActivity()
            .filter((i) => filter === 'all' || i.kind === filter);

        list.innerHTML = '';

        if (all.length === 0) {
            const messages = {
                all: dashboard.needs_onboarding
                    ? 'Finish your profile to start matching.'
                    : 'Nothing has happened yet. Propose a partnership to get started.',
                proposal: 'No partnership activity yet.',
                match: 'No matches yet. More needs and offers widen the search.',
                event: 'No meetings scheduled yet.'
            };
            list.innerHTML = `<p class="empty-state">${esc(messages[filter])}</p>`;
            if (activityViewAll) activityViewAll.hidden = true;
            return;
        }

        const shown = activityExpanded ? all : all.slice(0, ACTIVITY_COLLAPSED);
        shown.forEach((item) => {
            const row = document.createElement('div');
            row.className = `activity-item kind-${item.variant}`;
            row.innerHTML = `
                <div class="activity-icon"><i class='bx ${esc(item.icon)}'></i></div>
                <div class="activity-content">
                    <p>${item.text}</p>
                    <span class="activity-time">${
                        esc(item.at ? relativeTime(item.at) : (item.note || ''))
                    }</span>
                </div>
            `;
            list.appendChild(row);
        });

        if (activityViewAll) {
            activityViewAll.hidden = all.length <= ACTIVITY_COLLAPSED;
            activityViewAll.innerHTML = activityExpanded
                ? "Show less <i class='bx bx-chevron-up'></i>"
                : `View all activity (${all.length}) <i class='bx bx-chevron-right'></i>`;
        }
    }

    if (activityFilter) {
        activityFilter.addEventListener('change', () => {
            activityExpanded = false;
            renderActivity();
        });
    }

    if (activityViewAll) {
        activityViewAll.addEventListener('click', () => {
            activityExpanded = !activityExpanded;
            renderActivity();
        });
    }

    // Accepting or declining in the Partnerships card changes the history the
    // feed is built from, so re-read it rather than leaving a stale list.
    document.addEventListener('partnerships:changed', async () => {
        try {
            dashboard = await window.api('/api/dashboard');
        } catch {
            return; // leave the current feed rather than blanking it
        }
        renderActivity();
    });

    // --- Event partner dropdown -----------------------------------------
    // Was a hardcoded list of four invented organizations.
    //
    // Orgs you have already agreed a partnership with come first: those are
    // the ones you actually arrange meetings with. Listing only top matches
    // left the dropdown empty -- and the form unsubmittable, since the field
    // is required -- for any org whose partners were all already agreed.
    const partnerSelect = document.getElementById('eventPartner');
    if (partnerSelect) {
        partnerSelect.innerHTML = '<option value="">Select a partner</option>';

        const seen = new Set();
        const addOption = (id, name) => {
            if (!name || seen.has(String(id))) return;
            seen.add(String(id));
            const opt = document.createElement('option');
            opt.value = String(id);
            opt.textContent = name;
            partnerSelect.appendChild(opt);
        };

        (dashboard.recent_proposals || [])
            // An agreement outlives the other side closing its account, so
            // an accepted partnership no longer implies there is anyone left
            // to meet. The agreement still shows on the partnerships page;
            // it just is not something to put in the diary.
            // 'accepted' only: a completed or ended partnership is a record
            // rather than someone you are still arranging meetings with.
            .filter((p) => p.status === 'accepted' && !p.counterpart.deleted)
            .forEach((p) => addOption(p.counterpart.id, p.counterpart.name));
        (dashboard.top_matches || []).forEach((m) => addOption(m.id, m.name));
    }

    // --- Events -----------------------------------------------------------
    // Seeded from the dashboard payload, then kept in step with the server by
    // addEvent/removeEvent. Held in memory so every render below can stay
    // synchronous -- the reads are frequent (the card, the feed, the dialog)
    // and none of them should have to await.
    let events = (dashboard && dashboard.events) || [];

    // A copy: callers sort the result in place, and doing that to the backing
    // array would quietly reorder everyone else's view of it.
    function loadEvents() {
        return events.slice();
    }

    async function addEvent(payload) {
        const data = await window.api('/api/events', {
            method: 'POST',
            body: payload,
        });
        events.push(data.event);
        return data.event;
    }

    async function removeEvent(id) {
        await window.api(`/api/events/${encodeURIComponent(id)}`, {
            method: 'DELETE',
        });
        events = events.filter((ev) => String(ev.id) !== String(id));
    }

    // One-time rescue of meetings saved by the localStorage version. Without
    // it, the release that fixed "meetings do not persist" would itself be
    // the release that lost the meetings people already had.
    //
    // Each entry is dropped from storage only once the server has it, so a
    // failure halfway through leaves the rest to be retried on the next load
    // rather than uploading the successful ones twice. The key is removed
    // once empty, which is what makes this run only until it has finished.
    async function migrateLocalEvents() {
        let stored;
        try {
            stored = JSON.parse(localStorage.getItem(EVENTS_KEY)) || [];
        } catch {
            stored = [];
        }
        if (!Array.isArray(stored) || stored.length === 0) {
            try { localStorage.removeItem(EVENTS_KEY); } catch { /* nothing to clear */ }
            return;
        }

        const remaining = [...stored];
        for (const ev of stored) {
            try {
                await addEvent({
                    title: ev.title,
                    date: ev.date,
                    time: ev.time,
                    duration: ev.duration,
                    partner: ev.partner,
                    description: ev.description,
                    location: ev.location,
                });
            } catch (error) {
                // A 400 means this row can never be accepted (it predates the
                // server's validation), so it is dropped rather than retried
                // forever. Anything else is likely temporary and is kept.
                if (!error.status || error.status !== 400) break;
            }
            remaining.shift();
        }

        try {
            if (remaining.length) {
                localStorage.setItem(EVENTS_KEY, JSON.stringify(remaining));
            } else {
                localStorage.removeItem(EVENTS_KEY);
            }
        } catch {
            // Storage disabled; the rows are on the server either way.
        }
    }

    function formatTime(time24) {
        if (!time24) return '';
        const [hours, minutes] = time24.split(':').map(Number);
        const period = hours >= 12 ? 'PM' : 'AM';
        const hour12 = hours % 12 || 12;
        return `${hour12}:${String(minutes).padStart(2, '0')} ${period}`;
    }

    function addHours(time24, hoursToAdd) {
        if (!time24) return '';
        const [hours, minutes] = time24.split(':').map(Number);
        const total = hours * 60 + minutes + Math.round(hoursToAdd * 60);
        const endHours = Math.floor(total / 60) % 24;
        const endMinutes = total % 60;
        const label = formatTime(`${endHours}:${String(endMinutes).padStart(2, '0')}`);
        // A meeting starting at 23:00 and running two hours ended at
        // "1:00 AM" with nothing to say which day that was -- which reads as
        // a meeting that finished twenty-two hours before it started.
        return total >= 24 * 60 ? `${label} (+1 day)` : label;
    }

    // Focus is handled by common.js's dialogOpened/dialogClosed, which trap
    // Tab inside the dialog and put focus back on the control that opened it.
    function openModal() {
        if (!modal) return;
        // Errors from a previous attempt should not greet a fresh one.
        if (eventForm) clearEventErrors();
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(modal, document.getElementById('eventTitle'));
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
    }

    if (addEventBtn) addEventBtn.addEventListener('click', openModal);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal && modal.classList.contains('active')) {
            closeModal();
        }
    });

    // Local time; a bare "YYYY-MM-DD" is treated as UTC by Date and would
    // render as the previous day in western timezones.
    function eventDate(event) {
        const [year, month, day] = event.date.split('-').map(Number);
        return new Date(year, month - 1, day);
    }

    // Whether a meeting has already finished. The card is headed "Upcoming"
    // and the stat card counts what it holds, but nothing looked at the date
    // -- so a meeting from March was still being counted and shown as
    // something coming up. Measured from the end of the meeting rather than
    // its start, so one that is running right now still counts as upcoming.
    function isPastEvent(ev) {
        const end = eventDateTime(ev);
        if (!end) return false;
        const finishes = new Date(end);
        finishes.setMinutes(
            finishes.getMinutes() + Math.round((Number(ev.duration) || 0) * 60),
        );
        return finishes.getTime() < Date.now();
    }

    function eventTimeLabel(event) {
        const endTime = addHours(event.time, event.duration);
        return endTime
            ? `${formatTime(event.time)} - ${endTime}`
            : formatTime(event.time);
    }

    function renderEvent(event) {
        const date = eventDate(event);
        const monthLabel = date.toLocaleString('en-US', { month: 'short' }).toUpperCase();
        const timeLabel = eventTimeLabel(event);

        const item = document.createElement('div');
        item.className = 'event-item' + (isPastEvent(event) ? ' is-past' : '');
        // Opens the same dialog the Upcoming stat card does.
        item.dataset.eventId = event.id;
        item.innerHTML = `
            <div class="event-date">
                <span class="event-day">${date.getDate()}</span>
                <span class="event-month">${monthLabel}</span>
            </div>
            <div class="event-details">
                <h4>${esc(event.title)}</h4>
                <p>With ${esc(event.partner)}</p>
                <span class="event-time"><i class='bx bx-time'></i> ${timeLabel}</span>
            </div>
            <button class="btn-event" title="Remove event" data-event-id="${event.id}">
                <i class='bx bx-trash'></i>
            </button>
        `;
        return item;
    }

    function renderSavedEvents() {
        if (!eventsList) return;
        eventsList.innerHTML = '';

        const events = loadEvents().sort((a, b) =>
            `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`)
        );
        // Split rather than filtered: a meeting that has happened is still
        // worth seeing, and dropping it would lose the only record anyone
        // has of it. It just is not "upcoming", so it sorts below everything
        // that is -- most recent first, since a meeting last week is more
        // interesting than one last year -- and is marked as past.
        const upcoming = events.filter((ev) => !isPastEvent(ev));
        const past = events.filter(isPastEvent).reverse();

        if (events.length === 0) {
            eventsList.innerHTML =
                '<p class="empty-state">No meetings scheduled yet.</p>';
        } else {
            [...upcoming, ...past].forEach(
                (event) => eventsList.appendChild(renderEvent(event)));
        }

        // Counts what the card is headed with. This used to be every meeting
        // ever saved, so one from March still read as something coming up.
        const counter = document.getElementById('upcomingEvents');
        if (counter) counter.textContent = upcoming.length;

        // Meetings are one of the feed's sources, so adding or removing one
        // has to reach the activity list too.
        renderActivity();
        // ...and the dialog, if it is open on the meetings it just changed.
        if (statModal && statModal.classList.contains('active')) renderStat();
    }

    if (eventsList) {
        eventsList.addEventListener('click', async (e) => {
            const btn = e.target.closest('.btn-event[data-event-id]');
            if (btn) {
                // Disabled while the request is in flight: the row stays put
                // until the server confirms, and a second click would send a
                // delete for something already gone.
                btn.disabled = true;
                try {
                    await removeEvent(btn.dataset.eventId);
                    renderSavedEvents();
                } catch (error) {
                    btn.disabled = false;
                    // The row is still on screen and still real, so this says
                    // so rather than leaving a delete that looked ignored.
                    window.toast(
                        error.message || 'Could not remove that meeting.',
                        'error',
                    );
                }
                return;
            }
            // Anywhere else on the row opens that meeting in the dialog.
            const item = e.target.closest('.event-item[data-event-id]');
            if (item) openStat('events', { kind: 'event', id: item.dataset.eventId });
        });
    }

    // --- Event form validation ------------------------------------------
    // The form carries `novalidate`, so these messages replace the browser's
    // own bubbles: those are unstyled, vanish on the next click, and only ever
    // report the first offending field.
    //
    // Same shape as onboarding.js: `.input-error` on the control, a
    // `.field-error` note appended to the enclosing .form-group. Both are
    // already styled in forms.css.
    function setFieldError(field, message) {
        if (!field) return;
        field.classList.toggle('input-error', Boolean(message));
        field.setAttribute('aria-invalid', message ? 'true' : 'false');

        const holder = field.closest('.form-group') || field.parentElement;
        let note = holder.querySelector(':scope > .field-error');
        if (!message) {
            if (note) note.remove();
            return;
        }
        if (!note) {
            note = document.createElement('span');
            note.className = 'field-error';
            holder.appendChild(note);
        }
        note.textContent = message;
    }

    function showEventFormError(message) {
        if (!eventFormError) return;
        eventFormError.textContent = message;
        eventFormError.hidden = false;
    }

    function clearEventErrors() {
        eventForm.querySelectorAll('.field-error').forEach((n) => {
            // The whole-form slot is markup, not one of the notes setFieldError
            // creates -- hidden and emptied rather than removed, or the next
            // failure would have nowhere to report to.
            if (n === eventFormError) {
                n.hidden = true;
                n.textContent = '';
                return;
            }
            n.remove();
        });
        eventForm.querySelectorAll('.input-error').forEach((f) => {
            f.classList.remove('input-error');
            f.setAttribute('aria-invalid', 'false');
        });
    }

    function validateEventForm() {
        const title = document.getElementById('eventTitle');
        const date = document.getElementById('eventDate');
        const time = document.getElementById('eventTime');
        const duration = document.getElementById('eventDuration');
        const partner = document.getElementById('eventPartner');

        const problems = [];
        const fail = (field, message) => {
            setFieldError(field, message);
            problems.push(field);
        };

        clearEventErrors();

        if (!title.value.trim()) fail(title, 'Give the meeting a title.');
        if (!date.value) fail(date, 'Pick a date.');
        if (!time.value) fail(time, 'Pick a start time.');

        const hours = parseFloat(duration.value);
        if (!duration.value || Number.isNaN(hours) || hours <= 0) {
            fail(duration, 'Enter how long it runs, in hours.');
        }

        if (!partner.value) {
            // The dropdown is empty until there is someone to meet with, so
            // say that rather than asking for a choice that cannot be made.
            fail(partner, partner.options.length <= 1
                ? 'No partners yet — agree a partnership first, then schedule with them.'
                : 'Choose who the meeting is with.');
        }

        return problems;
    }

    if (eventForm) {
        // Clear a field's error as soon as it is corrected, so the form does
        // not keep complaining about something already fixed.
        eventForm.addEventListener('input', (e) => {
            if (e.target.classList.contains('input-error')) setFieldError(e.target, '');
        });
        eventForm.addEventListener('change', (e) => {
            if (e.target.classList.contains('input-error')) setFieldError(e.target, '');
        });

        eventForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const problems = validateEventForm();
            if (problems.length) {
                problems[0].focus();
                return;
            }

            const select = document.getElementById('eventPartner');
            const payload = {
                title: document.getElementById('eventTitle').value.trim(),
                date: document.getElementById('eventDate').value,
                time: document.getElementById('eventTime').value,
                duration: parseFloat(document.getElementById('eventDuration').value) || 1,
                partner: select.options[select.selectedIndex].text,
                description: document.getElementById('eventDescription').value.trim(),
                location: document.getElementById('eventLocation').value.trim()
            };

            // The dialog stays open and the button says what is happening,
            // rather than closing on a meeting that may not have saved.
            if (eventSubmitBtn) {
                eventSubmitBtn.disabled = true;
                eventSubmitBtn.textContent = 'Saving…';
            }
            try {
                await addEvent(payload);
            } catch (error) {
                showEventFormError(
                    error.message || 'Could not save that meeting. Please try again.',
                );
                return;
            } finally {
                if (eventSubmitBtn) {
                    eventSubmitBtn.disabled = false;
                    eventSubmitBtn.textContent = 'Save Event';
                }
            }

            renderSavedEvents();
            eventForm.reset();
            clearEventErrors();
            closeModal();
        });
    }

    // --- Stat detail dialog ----------------------------------------------
    // One dialog behind all four stat cards. `statView` picks the list;
    // `statDetail`, when set, replaces it with a single item and reveals the
    // back button. Layout aims to fit a whole list without scrolling (see the
    // two-column .stat-list in ppdashboard.css); the body can still scroll,
    // because with enough matches nothing fits and clipping would be worse.
    const statModal = document.getElementById('statModal');
    const statTitle = document.getElementById('statTitle');
    const statBody = document.getElementById('statBody');
    const statBack = document.getElementById('statBack');

    let statView = null;
    let statDetail = null;
    let allMatches = null;   // cached /api/matches
    let matchesError = null;
    let savedLeads = null;   // cached /api/saved
    let savedError = null;

    const VIEW_TITLES = {
        matches: 'Matches',
        mutual: 'Two-way matches',
        events: 'Upcoming meetings',
        tags: 'Profile tags',
        saved: 'Saved',
        views: 'Profile views'
    };

    function sortedEvents() {
        return loadEvents().sort((a, b) =>
            `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`));
    }

    function matchesFor(view) {
        const list = allMatches || [];
        return view === 'mutual'
            ? list.filter((m) => m.match_detail && m.match_detail.mutual)
            : list;
    }

    function emptyState(message) {
        return `<p class="empty-state">${esc(message)}</p>`;
    }

    function matchRow(m) {
        const meta = [m.organization_type, m.location].filter(Boolean).map(esc).join(' · ');
        return `
            <button type="button" class="stat-row" data-match-id="${m.id}">
                <span class="stat-row-mark">${esc(m.match_score)}<small>match</small></span>
                <span class="stat-row-main">
                    <span class="stat-row-title">${esc(m.name)}${
                        m.match_detail && m.match_detail.mutual
                            ? '<span class="mutual-flag">2-way</span>' : ''
                    }</span>
                    <span class="stat-row-meta">${meta || '&mdash;'}</span>
                </span>
                <i class='bx bx-chevron-right stat-row-go'></i>
            </button>`;
    }

    function eventRow(ev) {
        const d = eventDate(ev);
        return `
            <button type="button" class="stat-row" data-event-id="${esc(ev.id)}">
                <span class="stat-row-mark">${d.getDate()}<small>${
                    esc(d.toLocaleString('en-US', { month: 'short' }))
                }</small></span>
                <span class="stat-row-main">
                    <span class="stat-row-title">${esc(ev.title)}</span>
                    <span class="stat-row-meta">${esc(ev.partner)} · ${esc(eventTimeLabel(ev))}</span>
                </span>
                <i class='bx bx-chevron-right stat-row-go'></i>
            </button>`;
    }

    function field(label, value) {
        if (!value) return '';
        return `<div class="stat-field"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
    }

    function eventDetail(ev) {
        const d = eventDate(ev);
        const full = d.toLocaleDateString('en-US', {
            weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'
        });
        const hours = Number(ev.duration) || 1;
        return `
            <div class="stat-detail-head">
                <span class="stat-row-mark">${d.getDate()}<small>${
                    esc(d.toLocaleString('en-US', { month: 'short' }))
                }</small></span>
                <div>
                    <div class="stat-row-title">${esc(ev.title)}</div>
                    <div class="stat-row-meta">With ${esc(ev.partner)}</div>
                </div>
            </div>
            <dl class="stat-detail-grid">
                ${field('Date', full)}
                ${field('Time', eventTimeLabel(ev))}
                ${field('Duration', `${hours} hour${hours === 1 ? '' : 's'}`)}
                ${field('Location', ev.location)}
            </dl>
            ${ev.description
                ? `<p class="stat-detail-note">${esc(ev.description)}</p>` : ''}
            <div class="stat-detail-actions">
                <button type="button" class="btn-danger" data-remove-event="${esc(ev.id)}">
                    <i class='bx bx-trash'></i> Remove meeting
                </button>
            </div>`;
    }

    function matchDetail(m) {
        const d = m.match_detail || {};
        const meta = [m.organization_type, m.location].filter(Boolean).map(esc).join(' · ');
        const list = (items) => (items && items.length)
            ? `<div class="tag-chips">${items.map((i) => `<span>${esc(i)}</span>`).join('')}</div>`
            : '<p class="stat-row-meta">Nothing listed</p>';

        return `
            <div class="stat-detail-head">
                <span class="stat-row-mark">${esc(m.match_score)}<small>match</small></span>
                <div>
                    <div class="stat-row-title">${esc(m.name)}${
                        d.mutual ? '<span class="mutual-flag">2-way</span>' : ''
                    }</div>
                    <div class="stat-row-meta">${meta || '&mdash;'}</div>
                </div>
            </div>
            ${m.description ? `<p class="stat-detail-note">${esc(m.description)}</p>` : ''}
            <div class="stat-tags">
                <div class="needs">
                    <h3><i class='bx bx-down-arrow-alt'></i> They can offer you</h3>
                    ${list(d.they_give_labels)}
                </div>
                <div class="offers">
                    <h3><i class='bx bx-up-arrow-alt'></i> You can offer them</h3>
                    ${list(d.i_give_labels)}
                </div>
            </div>
            <dl class="stat-detail-grid" style="margin-top:1rem">
                ${field('Contact', m.contact_email)}
                ${field('Phone', m.contact_phone)}
            </dl>
            <div class="stat-detail-actions">
                <a class="btn-primary" href="organization.html?id=${encodeURIComponent(m.id)}"
                   target="_blank" rel="noopener">
                    <i class='bx bx-id-card'></i> View public profile
                </a>
                <a class="btn-ghost" href="ppsearch.html">Propose a partnership</a>
            </div>`;
    }

    function tagsView() {
        const org = (dashboard && dashboard.organization) || {};
        const chips = (items) => (items && items.length)
            ? `<div class="tag-chips">${items.map((i) => `<span>${esc(i)}</span>`).join('')}</div>`
            : '<p class="stat-row-meta">Nothing selected yet.</p>';
        return `
            <div class="stat-tags">
                <div class="needs">
                    <h3><i class='bx bx-down-arrow-alt'></i> What you need
                        (${(org.needs_labels || []).length})</h3>
                    ${chips(org.needs_labels)}
                </div>
                <div class="offers">
                    <h3><i class='bx bx-up-arrow-alt'></i> What you offer
                        (${(org.offers_labels || []).length})</h3>
                    ${chips(org.offers_labels)}
                </div>
            </div>`;
    }

    // A summary, not a list. Every other view here itemises what it counts;
    // this one deliberately cannot, because the rows behind it record that
    // somebody looked, not who -- most visitors are signed out and have no
    // account here to be named from. Says so plainly rather than leaving the
    // absence to be read as a gap.
    function viewsView() {
        const s = (dashboard && dashboard.stats) || {};
        const total = s.profile_views || 0;
        const recent = s.profile_views_recent || 0;
        if (!total) {
            return emptyState('No one has opened your public profile yet. '
                + 'Sharing its link is what puts it in front of people — the '
                + 'Copy link button is on the profile itself.');
        }
        return `
            <div class="stat-detail-grid">
                ${field('All time', String(total))}
                ${field('Last 30 days', String(recent))}
            </div>
            <p class="stat-detail-note">
                Counted once per visitor per day, so a reload is not a second
                view. Your own visits are not counted. Who looked is not
                recorded — most people opening a public profile are not signed
                in, so there is no one to name.
            </p>`;
    }

    function renderStat() {
        if (!statModal) return;

        // Drilled into a single item.
        if (statDetail) {
            statBack.hidden = false;
            if (statDetail.kind === 'event') {
                const ev = loadEvents().find((e) => String(e.id) === String(statDetail.id));
                if (!ev) { statDetail = null; return renderStat(); }
                statTitle.textContent = ev.title;
                statBody.innerHTML = eventDetail(ev);
            } else {
                // Both lists, not just the matches: a saved organization is
                // kept precisely because it may no longer be a match, so
                // looking only there would fail to open the very rows this
                // view exists to hold.
                const m = (allMatches || []).find((x) => String(x.id) === String(statDetail.id))
                    || (savedLeads || []).find((x) => String(x.id) === String(statDetail.id));
                if (!m) { statDetail = null; return renderStat(); }
                statTitle.textContent = m.name;
                statBody.innerHTML = matchDetail(m);
            }
            return;
        }

        statBack.hidden = true;

        if (statView === 'events') {
            const events = sortedEvents();
            statTitle.textContent = `${VIEW_TITLES.events} (${events.length})`;
            statBody.innerHTML = events.length
                ? `<div class="stat-list">${events.map(eventRow).join('')}</div>`
                : emptyState('No meetings scheduled yet. Use Add Event to create one.');
            return;
        }

        if (statView === 'saved') {
            statTitle.textContent = VIEW_TITLES.saved;
            if (savedError) {
                statBody.innerHTML = emptyState(savedError);
                return;
            }
            if (savedLeads === null) {
                statBody.innerHTML = emptyState('Loading...');
                return;
            }
            statTitle.textContent = `${VIEW_TITLES.saved} (${savedLeads.length})`;
            statBody.innerHTML = savedLeads.length
                ? `<div class="stat-list">${savedLeads.map(matchRow).join('')}</div>`
                : emptyState('Nothing saved yet. Use the bookmark on a match in '
                    + 'Search to keep it here — saved organizations stay on this '
                    + 'list even if your profile changes and they stop matching.');
            return;
        }

        if (statView === 'views') {
            const s = (dashboard && dashboard.stats) || {};
            statTitle.textContent =
                `${VIEW_TITLES.views} (${s.profile_views || 0})`;
            statBody.innerHTML = viewsView();
            return;
        }

        if (statView === 'tags') {
            const org = (dashboard && dashboard.organization) || {};
            const total = (org.needs_labels || []).length + (org.offers_labels || []).length;
            statTitle.textContent = `${VIEW_TITLES.tags} (${total})`;
            statBody.innerHTML = tagsView();
            return;
        }

        // matches / mutual
        statTitle.textContent = VIEW_TITLES[statView] || 'Details';
        if (matchesError) {
            statBody.innerHTML = emptyState(matchesError);
            return;
        }
        if (allMatches === null) {
            statBody.innerHTML = emptyState('Loading...');
            return;
        }
        const list = matchesFor(statView);
        statTitle.textContent = `${VIEW_TITLES[statView]} (${list.length})`;
        statBody.innerHTML = list.length
            ? `<div class="stat-list">${list.map(matchRow).join('')}</div>`
            : emptyState(statView === 'mutual'
                ? 'No two-way matches yet. These are organizations that need what you offer and offer what you need.'
                : 'No matches yet. Adding more needs and offers to your profile widens the search.');
    }

    async function ensureMatches() {
        if (allMatches !== null || matchesError) return;
        try {
            const data = await window.api('/api/matches');
            allMatches = data.matches || [];
        } catch (error) {
            matchesError = error.status === 409
                ? 'Finish your profile first — matches are built from what you need and offer.'
                : (error.message || 'Could not load matches.');
        }
        renderStat();
    }

    // Same lazy shape as ensureMatches: the card shows the count from the
    // dashboard payload, and the organizations behind it are only fetched
    // once someone opens the list.
    async function ensureSaved() {
        if (savedLeads !== null || savedError) return;
        try {
            const data = await window.api('/api/saved');
            savedLeads = data.saved || [];
        } catch (error) {
            savedError = error.message || 'Could not load your saved list.';
        }
        renderStat();
    }

    function openStat(view, detail) {
        if (!statModal) return;
        const wasOpen = statModal.classList.contains('active');
        statView = view;
        statDetail = detail || null;
        statModal.classList.add('active');
        document.body.style.overflow = 'hidden';
        renderStat();
        // Only on the way in: reopening a view while the dialog is already
        // up would otherwise record a row that is about to be repainted away
        // as the control to return to.
        if (!wasOpen) {
            window.dialogOpened(statModal, document.getElementById('statClose'));
        }
        if (view === 'matches' || view === 'mutual') ensureMatches();
        if (view === 'saved') ensureSaved();
    }

    function closeStat() {
        if (!statModal) return;
        statModal.classList.remove('active');
        document.body.style.overflow = 'auto';
        statDetail = null;
        window.dialogClosed(statModal);
    }

    document.querySelectorAll('.stat-card[data-stat]').forEach((card) => {
        card.addEventListener('click', () => openStat(card.dataset.stat));
    });

    const eventsViewAll = document.getElementById('eventsViewAll');
    if (eventsViewAll) eventsViewAll.addEventListener('click', () => openStat('events'));

    if (statModal) {
        statBack.addEventListener('click', () => { statDetail = null; renderStat(); });
        document.getElementById('statClose').addEventListener('click', closeStat);
        statModal.addEventListener('click', (e) => {
            if (e.target === statModal) closeStat();
        });

        // Row clicks and the in-detail remove button.
        statBody.addEventListener('click', async (e) => {
            const remove = e.target.closest('[data-remove-event]');
            if (remove) {
                remove.disabled = true;
                try {
                    await removeEvent(remove.dataset.removeEvent);
                    statDetail = null;
                    renderSavedEvents();  // repaints the card, the feed and this dialog
                } catch (error) {
                    remove.disabled = false;
                    window.toast(
                        error.message || 'Could not remove that meeting.',
                        'error',
                    );
                }
                return;
            }
            const row = e.target.closest('.stat-row');
            if (!row) return;
            if (row.dataset.eventId) {
                statDetail = { kind: 'event', id: row.dataset.eventId };
            } else if (row.dataset.matchId) {
                statDetail = { kind: 'match', id: row.dataset.matchId };
            }
            renderStat();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || !statModal.classList.contains('active')) return;
            // Escape steps back out of a detail before closing the dialog.
            if (statDetail) { statDetail = null; renderStat(); } else closeStat();
        });
    }

    renderSavedEvents();
    // Explicit, because renderSavedEvents bails early if the events card is
    // absent and the feed must not depend on that.
    renderActivity();

    // After the first paint, not before it: the meetings already on the
    // server are what almost every load has, and holding the card back on an
    // upload that only matters once would delay all of them for none of them.
    // Repaints only if it actually moved something across.
    const before = events.length;
    await migrateLocalEvents();
    if (events.length !== before) renderSavedEvents();
});
