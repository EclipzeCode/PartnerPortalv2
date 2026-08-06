// Dashboard.
//
// The stat cards, activity feed and connections list used to be hardcoded
// markup. They are now filled from /api/dashboard, which reports the
// signed-in org's real match counts and its actual top matches.
//
// Events remain local to the browser: there is no events table yet, so
// loadEvents/saveEvents still read localStorage. They are kept isolated so
// swapping in an API call later is a two-function change.

document.addEventListener('DOMContentLoaded', async () => {
    const EVENTS_KEY = 'partnerPortalEvents';
    const esc = window.escapeHtml;

    const modal = document.getElementById('eventModal');
    const addEventBtn = document.getElementById('addEventBtn');
    const eventForm = document.getElementById('eventForm');
    const eventsList = document.querySelector('.events-list');
    const closeBtn = modal ? modal.querySelector('.close-modal') : null;

    // --- Live data ------------------------------------------------------
    let dashboard = null;
    try {
        dashboard = await window.api('/api/dashboard');
    } catch (error) {
        console.error('Could not load dashboard:', error);
        return; // api() redirects on 401; anything else leaves the page as-is
    }

    const org = dashboard.organization;
    const stats = dashboard.stats;

    // Greeting
    const heading = document.querySelector('.section-header h2');
    if (heading) {
        heading.innerHTML = `Welcome back, <span>${esc(org.name)}</span>`;
    }

    // Stat cards. The markup labels are updated too, because "Active Partners"
    // and "Partner Score" described numbers that never existed.
    setStat('activePartners', stats.total_matches, 'Matches',
            stats.mutual_matches ? `${stats.mutual_matches} two-way` : 'no two-way yet');
    setStat('unreadMessages', stats.mutual_matches, 'Two-way matches',
            'both sides benefit');
    setStat('partnerScore', stats.needs_count + stats.offers_count, 'Profile tags',
            `${stats.needs_count} needs · ${stats.offers_count} offers`);

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
    if (dashboard.needs_onboarding) {
        const grid = document.querySelector('.connections-grid');
        if (grid) {
            grid.innerHTML =
                '<p class="empty-state">Your profile is not finished yet, so ' +
                'there is nothing to match against.<br><br>' +
                '<a class="btn-primary" href="onboarding.html">Complete your profile</a></p>';
        }
        replaceActivity([{
            icon: 'bx-user-plus',
            text: 'Finish your profile to start matching',
            time: 'Now'
        }]);
    } else {
        renderConnections(dashboard.top_matches || []);
        renderActivity(dashboard.top_matches || [], org);
    }

    // --- Connections ----------------------------------------------------
    function renderConnections(matches) {
        const grid = document.querySelector('.connections-grid');
        if (!grid) return;
        grid.innerHTML = '';

        if (matches.length === 0) {
            grid.innerHTML =
                '<p class="empty-state">No matches yet. Adding more needs and ' +
                'offers to your profile widens the search.<br><br>' +
                '<a class="btn-primary" href="onboarding.html">Edit profile</a></p>';
            return;
        }

        matches.forEach((m) => {
            const initials = (m.name || '?')
                .split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
            const card = document.createElement('div');
            card.className = 'connection-card';
            card.innerHTML = `
                <div class="connection-avatar">${esc(initials)}</div>
                <div class="connection-info">
                    <h4>${esc(m.name)}</h4>
                    <p>${esc(m.organization_type || '')} · ${esc(m.location || '')}</p>
                    <span class="connection-score">${m.match_score} match${
                        m.match_detail.mutual ? ' · two-way' : ''
                    }</span>
                </div>
                <a class="btn-connection" href="ppsearch.html">View</a>
            `;
            grid.appendChild(card);
        });
    }

    // --- Activity -------------------------------------------------------
    function renderActivity(matches, me) {
        const items = [];
        const mutual = matches.filter((m) => m.match_detail.mutual);

        if (mutual.length) {
            items.push({
                icon: 'bx-transfer',
                text: `Two-way match with <strong>${esc(mutual[0].name)}</strong>`,
                time: 'From your profile'
            });
        }
        matches.slice(0, 3).forEach((m) => {
            const gives = (m.match_detail.they_give_labels || [])[0];
            items.push({
                icon: 'bx-link',
                text: gives
                    ? `<strong>${esc(m.name)}</strong> offers ${esc(gives)}`
                    : `<strong>${esc(m.name)}</strong> could use what you offer`,
                time: `${m.match_score} match`
            });
        });
        if (me.location) {
            items.push({
                icon: 'bx-map',
                text: `Matching against organizations near ${esc(me.location)}`,
                time: 'Profile'
            });
        }
        replaceActivity(items);
    }

    function replaceActivity(items) {
        const list = document.querySelector('.activity-list');
        if (!list) return;
        list.innerHTML = '';
        items.forEach((item) => {
            const row = document.createElement('div');
            row.className = 'activity-item';
            row.innerHTML = `
                <div class="activity-icon"><i class='bx ${esc(item.icon)}'></i></div>
                <div class="activity-content">
                    <p>${item.text}</p>
                    <span class="activity-time">${esc(item.time)}</span>
                </div>
            `;
            list.appendChild(row);
        });
    }

    // --- Event partner dropdown -----------------------------------------
    // Was a hardcoded list of four invented organizations.
    const partnerSelect = document.getElementById('eventPartner');
    if (partnerSelect) {
        partnerSelect.innerHTML = '<option value="">Select a partner</option>';
        (dashboard.top_matches || []).forEach((m) => {
            const opt = document.createElement('option');
            opt.value = String(m.id);
            opt.textContent = m.name;
            partnerSelect.appendChild(opt);
        });
    }

    // --- Events (still local) -------------------------------------------
    function loadEvents() {
        try {
            return JSON.parse(localStorage.getItem(EVENTS_KEY)) || [];
        } catch {
            return [];
        }
    }

    function saveEvents(events) {
        localStorage.setItem(EVENTS_KEY, JSON.stringify(events));
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
        return formatTime(`${endHours}:${String(endMinutes).padStart(2, '0')}`);
    }

    function openModal() {
        if (!modal) return;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
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

    function renderEvent(event) {
        // Parse as local time; a bare "YYYY-MM-DD" is treated as UTC by Date
        // and would render as the previous day in western timezones.
        const [year, month, day] = event.date.split('-').map(Number);
        const date = new Date(year, month - 1, day);
        const monthLabel = date.toLocaleString('en-US', { month: 'short' }).toUpperCase();

        const endTime = addHours(event.time, event.duration);
        const timeLabel = endTime
            ? `${formatTime(event.time)} - ${endTime}`
            : formatTime(event.time);

        const item = document.createElement('div');
        item.className = 'event-item';
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

        if (events.length === 0) {
            eventsList.innerHTML =
                '<p class="empty-state">No meetings scheduled yet.</p>';
        } else {
            events.forEach((event) => eventsList.appendChild(renderEvent(event)));
        }

        const counter = document.getElementById('upcomingEvents');
        if (counter) counter.textContent = events.length;
    }

    if (eventsList) {
        eventsList.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-event[data-event-id]');
            if (!btn) return;
            saveEvents(loadEvents().filter(
                (ev) => String(ev.id) !== btn.dataset.eventId
            ));
            renderSavedEvents();
        });
    }

    if (eventForm) {
        eventForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const select = document.getElementById('eventPartner');
            const newEvent = {
                id: Date.now(),
                title: document.getElementById('eventTitle').value.trim(),
                date: document.getElementById('eventDate').value,
                time: document.getElementById('eventTime').value,
                duration: parseFloat(document.getElementById('eventDuration').value) || 1,
                partner: select.options[select.selectedIndex].text,
                description: document.getElementById('eventDescription').value.trim(),
                location: document.getElementById('eventLocation').value.trim()
            };

            if (!newEvent.title || !newEvent.date || !newEvent.time || !select.value) {
                return; // `required` attributes already surface the message
            }

            saveEvents([...loadEvents(), newEvent]);
            renderSavedEvents();
            eventForm.reset();
            closeModal();
        });
    }

    renderSavedEvents();
});
