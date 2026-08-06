// Dashboard page behaviour.
//
// NOTE: the stats, activity feed, connections and the three sample events in
// ppdashboard.html are still hardcoded placeholder markup. They stay that way
// until the accounts/profiles/matches data model lands, at which point this
// file should fetch real data instead. The event handling below is deliberately
// isolated behind loadEvents()/saveEvents() so swapping localStorage for an API
// call is a two-function change.

document.addEventListener('DOMContentLoaded', () => {
    const EVENTS_KEY = 'partnerPortalEvents';

    const modal = document.getElementById('eventModal');
    const addEventBtn = document.getElementById('addEventBtn');
    const eventForm = document.getElementById('eventForm');
    const eventsList = document.querySelector('.events-list');
    const closeBtn = modal ? modal.querySelector('.close-modal') : null;

    // --- Helpers ------------------------------------------------------------
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

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

    // --- Greeting -----------------------------------------------------------
    // pplogin.js stores this on a successful login.
    const username = localStorage.getItem('username');
    const heading = document.querySelector('.section-header h2');
    if (username && heading) {
        heading.innerHTML = `Welcome back, <span>${escapeHtml(username)}</span>`;
    }

    // --- Modal --------------------------------------------------------------
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

    // --- Rendering ----------------------------------------------------------
    function renderEvent(event) {
        // Parse as local time; a bare "YYYY-MM-DD" is treated as UTC by Date
        // and would render as the previous day in western timezones.
        const [year, month, day] = event.date.split('-').map(Number);
        const date = new Date(year, month - 1, day);
        const monthLabel = date
            .toLocaleString('en-US', { month: 'short' })
            .toUpperCase();

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
                <h4>${escapeHtml(event.title)}</h4>
                <p>With ${escapeHtml(event.partner)}</p>
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

        // Remove previously rendered entries, leaving the placeholder markup.
        eventsList
            .querySelectorAll('.event-item[data-saved="true"]')
            .forEach((el) => el.remove());

        const events = loadEvents().sort((a, b) =>
            `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`)
        );

        events.forEach((event) => {
            const item = renderEvent(event);
            item.dataset.saved = 'true';
            eventsList.prepend(item);
        });

        updateUpcomingCount(events.length);
    }

    function updateUpcomingCount(savedCount) {
        const counter = document.getElementById('upcomingEvents');
        if (!counter) return;
        const placeholders = eventsList
            ? eventsList.querySelectorAll('.event-item:not([data-saved="true"])').length
            : 0;
        counter.textContent = savedCount + placeholders;
    }

    if (eventsList) {
        eventsList.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-event[data-event-id]');
            if (!btn) return;
            const remaining = loadEvents().filter(
                (ev) => String(ev.id) !== btn.dataset.eventId
            );
            saveEvents(remaining);
            renderSavedEvents();
        });
    }

    // --- Form ---------------------------------------------------------------
    if (eventForm) {
        eventForm.addEventListener('submit', (e) => {
            e.preventDefault();

            const partnerSelect = document.getElementById('eventPartner');
            const newEvent = {
                id: Date.now(),
                title: document.getElementById('eventTitle').value.trim(),
                date: document.getElementById('eventDate').value,
                time: document.getElementById('eventTime').value,
                duration: parseFloat(document.getElementById('eventDuration').value) || 1,
                partner: partnerSelect.options[partnerSelect.selectedIndex].text,
                description: document.getElementById('eventDescription').value.trim(),
                location: document.getElementById('eventLocation').value.trim()
            };

            if (!newEvent.title || !newEvent.date || !newEvent.time || !partnerSelect.value) {
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
