// Partner matching results.
//
// Ranking happens on the server now (see matching.py) against the signed-in
// org's stored profile, rather than in the browser against a localStorage
// blob. The page renders what it is given and filters locally.

document.addEventListener('DOMContentLoaded', async () => {
    const partnersGrid = document.getElementById('partnersGrid');
    const searchInput = document.getElementById('searchInput');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const showAllBtn = document.getElementById('showAllBtn');
    const pageIndicator = document.getElementById('pageIndicator');

    const filterBtn = document.getElementById('filter-btn');
    const addBtn = document.getElementById('add-btn');
    const filterModal = document.getElementById('filterModal');
    const detailModal = document.getElementById('partnerDetailModal');
    const filterForm = document.getElementById('filterForm');
    const clearFiltersBtn = document.getElementById('clearFiltersBtn');

    const esc = window.escapeHtml;

    // How many cards a page holds, matched to the column count the grid is
    // actually using (see the breakpoints in ppsearch.css). Kept even at
    // every width so a page never ends on a half-filled row: three across
    // fills two rows of three, two across fills two rows of two.
    const PAGE_SIZES = [
        { query: '(min-width: 64em)', size: 6 },   // 3 columns
        { query: '(min-width: 40em)', size: 4 },   // 2 columns
    ];
    const NARROW_PAGE_SIZE = 4;                    // 1 column

    function pageSize() {
        if (showAll) return Infinity;
        const hit = PAGE_SIZES.find((p) => window.matchMedia(p.query).matches);
        return hit ? hit.size : NARROW_PAGE_SIZE;
    }

    // Everything at once, for when paging through is the slower way to find
    // something. Off by default so the first screen is the strongest matches
    // rather than the whole directory.
    let showAll = false;

    let allMatches = [];
    let exampleMatches = [];
    let showingExamples = false;
    let displayed = [];
    let currentPage = 1;
    let mutualOnly = false;
    // Applied in the browser rather than as another query parameter: the
    // overlap is already in every match's detail, so this is a filter over
    // data the page holds, not a different question for the server.
    let sharedFocusOnly = false;

    // --- Shortlist --------------------------------------------------------
    // Which organizations are saved, and (when the shortlist is being shown)
    // the organizations themselves. Kept as a Set because the only question
    // the cards ask is "is this one saved", once per card per render.
    //
    // The shortlist is fetched separately rather than filtered out of
    // allMatches: saving is a decision, and matches move as either side edits
    // its profile. An organization that has stopped matching is exactly the
    // one worth keeping hold of, and filtering the match list would drop it.
    const savedToggle = document.getElementById('savedToggle');
    const savedCount = document.getElementById('savedCount');
    const detailSaveBtn = document.getElementById('detailSaveBtn');
    const detailSaveLabel = document.getElementById('detailSaveLabel');

    const detailNoteBlock = document.getElementById('detailNoteBlock');
    const detailNote = document.getElementById('detailNote');
    const detailNoteSave = document.getElementById('detailNoteSave');
    const detailNoteStatus = document.getElementById('detailNoteStatus');

    let savedIds = new Set();
    let savedList = [];
    // id -> note, so a card in the shortlist and the dialog behind it read
    // the same text without either having to re-fetch.
    let savedNotes = new Map();
    let viewMode = 'matches';   // 'matches' | 'saved'

    // Adding a partner by hand is gone: organizations create themselves by
    // registering and completing onboarding. Leaving a form that writes rows
    // nobody owns would reintroduce exactly the orphaned-profile problem the
    // organizations model was built to remove.
    if (addBtn) addBtn.remove();

    // Stands in for the cards that are about to arrive, rather than a line of
    // text that occupies none of their space -- the grid used to be one short
    // sentence and then suddenly a screen of cards, which moved everything
    // below it. Six is a full first page, so the page height is roughly right
    // before the data lands.
    function renderSkeletonCards(count = 6) {
        partnersGrid.innerHTML = Array.from({ length: count }, () => `
            <div class="partner-card skeleton-card" aria-hidden="true">
                <div class="skeleton skeleton-score"></div>
                <div class="partner-content">
                    <div class="skeleton skeleton-line title"></div>
                    <div class="skeleton skeleton-line"></div>
                    <div class="skeleton skeleton-line"></div>
                    <div class="skeleton skeleton-line short"></div>
                </div>
            </div>
        `).join('');
    }

    // --- Data -----------------------------------------------------------
    async function loadMatches() {
        // Screen readers get the status line; sighted users get the shapes.
        partnersGrid.setAttribute('aria-busy', 'true');
        renderSkeletonCards();
        try {
            const data = await window.api(
                `/api/matches${mutualOnly ? '?mutual=1' : ''}`
            );
            allMatches = data.matches || [];
            exampleMatches = data.examples || [];
            // Rides along with the matches, so the stars are right on the
            // first paint rather than filling in a moment later.
            savedIds = new Set(data.saved_ids || []);
            updateSavedCount();
        } catch (error) {
            partnersGrid.removeAttribute('aria-busy');
            if (error.status === 409 && error.data && error.data.needs_onboarding) {
                partnersGrid.innerHTML =
                    '<p class="empty-state">Tell us about your organization first — ' +
                    'matches are built from what you need and what you offer.<br><br>' +
                    '<a class="btn-primary" href="onboarding.html">Complete your profile</a></p>';
                updatePagination(0);
                return;
            }
            console.error('Could not load matches:', error);
            partnersGrid.innerHTML =
                `<p class="empty-state">${esc(error.message)}</p>`;
            updatePagination(0);
            return;
        }
        partnersGrid.removeAttribute('aria-busy');
        applyView();
    }

    // Loaded on first use rather than with the page: most visits never open
    // the shortlist, and the star states already arrive with the matches.
    async function loadSaved() {
        partnersGrid.setAttribute('aria-busy', 'true');
        renderSkeletonCards(3);
        try {
            const data = await window.api('/api/saved');
            savedList = data.saved || [];
            savedIds = new Set(savedList.map((s) => s.id));
            savedNotes = new Map(savedList.map((s) => [s.id, s.note || '']));
        } catch (error) {
            partnersGrid.removeAttribute('aria-busy');
            partnersGrid.innerHTML =
                `<p class="empty-state">${esc(error.message)}</p>`;
            updatePagination(0);
            return false;
        }
        partnersGrid.removeAttribute('aria-busy');
        updateSavedCount();
        return true;
    }

    function updateSavedCount() {
        if (!savedCount) return;
        const n = savedIds.size;
        savedCount.textContent = n;
        savedCount.hidden = n === 0;
    }

    async function setViewMode(mode) {
        viewMode = mode;
        if (savedToggle) {
            savedToggle.setAttribute('aria-pressed', String(mode === 'saved'));
            savedToggle.classList.toggle('active', mode === 'saved');
        }
        // Re-fetched on every switch back in, not just the first: scores are
        // computed against the current profile, and the shortlist is where a
        // stale one would be least obvious.
        if (mode === 'saved' && !(await loadSaved())) return;
        currentPage = 1;
        applyView();
    }

    if (savedToggle) {
        savedToggle.addEventListener('click', () => {
            setViewMode(viewMode === 'saved' ? 'matches' : 'saved');
        });
    }

    // `keepPage` is for renders caused by something the reader did to one
    // card -- bookmarking it, writing a note on it. Those used to send the
    // grid back to page 1, so acting on a card on page 4 meant losing your
    // place and paging back to find where you were. A new search or a
    // different view really is a different list and still starts at the top.
    function applyView({ keepPage = false } = {}) {
        const q = (searchInput.value || '').toLowerCase().trim();
        const norm = (v) => (v || '').toLowerCase();
        const page = currentPage;

        if (viewMode === 'saved') {
            showingExamples = false;
            displayed = q
                ? savedList.filter((m) =>
                    norm(m.name).includes(q) ||
                    norm(m.organization_type).includes(q) ||
                    norm(m.location).includes(q) ||
                    (m.offers_labels || []).some((l) => norm(l).includes(q)) ||
                    (m.needs_labels || []).some((l) => norm(l).includes(q)))
                : [...savedList];
            currentPage = keepPage ? page : 1;
            render();
            return;
        }

        // No real matches yet, but seeded examples exist: show those instead
        // of an empty page. They are visibly flagged and cannot be proposed to.
        showingExamples = allMatches.length === 0 && exampleMatches.length > 0;
        let source = showingExamples ? exampleMatches : allMatches;

        // Only the match list. The shortlist is what someone chose to keep,
        // and quietly hiding part of it behind a search filter would be a
        // different promise than the one that view makes.
        if (sharedFocusOnly) {
            source = source.filter(
                (m) => ((m.match_detail || {}).shared_focus || []).length > 0,
            );
        }

        displayed = q
            ? source.filter((m) =>
                norm(m.name).includes(q) ||
                norm(m.organization_type).includes(q) ||
                norm(m.location).includes(q) ||
                (m.offers_labels || []).some((l) => norm(l).includes(q)) ||
                (m.needs_labels || []).some((l) => norm(l).includes(q)))
            : [...source];

        currentPage = keepPage ? page : 1;
        render();
    }

    // --- Rendering ------------------------------------------------------
    function render() {
        partnersGrid.innerHTML = '';
        const banner = document.getElementById('exampleBanner');
        if (banner) banner.classList.toggle('hidden', !showingExamples);

        const size = pageSize();
        const pages = Math.max(1, Math.ceil(displayed.length / size));
        if (currentPage > pages) currentPage = pages;

        if (displayed.length === 0) {
            let message;
            if (viewMode === 'saved') {
                message = savedList.length === 0
                    ? 'Nothing saved yet. Use the bookmark on a match to keep ' +
                      'it here — saved organizations stay on this list even if ' +
                      'your profile changes and they stop matching.'
                    : 'No saved organizations match that search.';
            } else {
                if (sharedFocusOnly) {
                    message = 'No matches work on the same things you do. '
                        + 'Clear the focus filter to see the rest, or add more '
                        + 'focus areas to your profile.';
                } else if (mutualOnly) {
                    message = 'No two-way matches yet. Turn off the two-way '
                        + 'filter to see one-directional matches.';
                } else {
                    message = 'No matches yet. Adding more needs and offers to '
                        + 'your profile widens the search.';
                }
            }
            partnersGrid.innerHTML = `<p class="empty-state">${esc(message)}</p>`;
            updatePagination(pages);
            return;
        }

        const start = showAll ? 0 : (currentPage - 1) * size;
        const slice = showAll ? displayed : displayed.slice(start, start + size);
        slice.forEach((m, offset) => {
            const card = document.createElement('div');
            card.className = 'partner-card'
                + (m.match_detail.mutual ? ' mutual' : '')
                + (m.is_demo ? ' is-example' : '');
            card.tabIndex = 0;
            card.setAttribute('role', 'button');
            card.setAttribute('aria-label', `View details for ${m.name}`);
            card.dataset.index = String(start + offset);

            const badge = m.is_demo
                ? '<span class="example-tag">Example</span>'
                : (m.match_detail.mutual
                    ? '<span class="mutual-badge"><i class="bx bx-transfer"></i> Two-way match</span>'
                    : '');

            const reasons = (m.reasons || [])
                .map((r) => `<li>${esc(r)}</li>`).join('');

            // Examples have no owner and nothing to follow up on, so they get
            // no bookmark -- the same line the Propose button draws.
            const isSaved = savedIds.has(m.id);
            const saveBtn = m.is_demo ? '' : `
                <button type="button" class="card-save${isSaved ? ' saved' : ''}"
                        data-save-id="${m.id}"
                        aria-pressed="${isSaved}"
                        title="${isSaved ? 'Remove from saved' : 'Save for later'}"
                        aria-label="${isSaved ? 'Remove' : 'Save'} ${esc(m.name)}">
                    <i class='bx ${isSaved ? 'bxs-bookmark' : 'bx-bookmark'}'></i>
                </button>`;

            // Only in the shortlist, and then on every card in it, so the
            // fixed heights stay consistent within the view. Adding it to
            // matches too would spend a slot on something none of them have.
            const noteSlot = viewMode === 'saved'
                ? `<div class="card-note${savedNotes.get(m.id) ? '' : ' empty'}">${
                      savedNotes.get(m.id)
                          ? esc(savedNotes.get(m.id))
                          : 'No note yet — open this card to add one.'
                  }</div>`
                : '';

            // Every region below is given a fixed height in CSS, and the
            // badge gets a slot whether or not there is one to put in it.
            // Without that, a card with no badge or a one-line name pulled
            // everything under it upwards, so "Why match" started at a
            // different height on each card and the tallest card in a row
            // stretched the rest to match it.
            card.innerHTML = `
                <div class="partner-score">${m.match_score}</div>
                ${saveBtn}
                <div class="partner-content">
                    <div class="card-badge-slot">${badge}</div>
                    <h3>${esc(m.name)}</h3>
                    <p class="card-line card-type"><strong>Type:</strong> ${esc(m.organization_type)}</p>
                    <p class="card-line card-location"><strong>Location:</strong> ${esc(m.location)}</p>
                    <p class="card-line card-offers"><strong>Offers:</strong> ${esc((m.offers_labels || []).join(', '))}</p>
                    <div class="match-reasons">
                        <strong>Why match:</strong>
                        <ul>${reasons}</ul>
                    </div>
                    ${noteSlot}
                </div>
            `;
            partnersGrid.appendChild(card);
        });

        markTruncated();
        updatePagination(pages);
    }

    // The reason lists are clipped to a fixed height so every card is the
    // same size, which means some cards are hiding text. CSS cannot tell
    // which, so this measures after layout and marks only those that
    // actually overflow -- a fade drawn over a half-empty box would suggest
    // there is more to read when there is not. The full text is in the
    // dialog the card already opens.
    function markTruncated() {
        partnersGrid.querySelectorAll('.match-reasons').forEach((block) => {
            const list = block.querySelector('ul');
            if (!list) return;
            block.classList.toggle(
                'is-truncated', list.scrollHeight > list.clientHeight + 1,
            );
        });
    }

    function updatePagination(pages) {
        const count = displayed.length;
        const size = pageSize();
        if (count === 0) {
            pageIndicator.textContent = 'No results';
        } else if (showAll) {
            pageIndicator.textContent = `Showing all ${count}`;
        } else {
            const first = (currentPage - 1) * size + 1;
            const last = Math.min(currentPage * size, count);
            pageIndicator.textContent =
                `Page ${currentPage} of ${pages}  ·  ${first}-${last} of ${count}`;
        }
        // The arrows are meaningless while everything is on screen, and a
        // page count is not a thing to step through when there is one page.
        prevBtn.disabled = showAll || currentPage <= 1;
        nextBtn.disabled = showAll || currentPage >= pages;
        if (showAllBtn) {
            showAllBtn.textContent = showAll ? 'Show pages' : 'Show all';
            showAllBtn.setAttribute('aria-pressed', String(showAll));
            // Nothing to expand when a single page already holds everything.
            showAllBtn.hidden = count <= size && !showAll;
        }
    }

    function goToPage(page) {
        const pages = Math.max(1, Math.ceil(displayed.length / pageSize()));
        currentPage = Math.min(Math.max(1, page), pages);
        render();
        partnersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // --- Modals ---------------------------------------------------------
    // All three dialogs on this page share these, and focus for all three is
    // common.js's dialogOpened/dialogClosed: trapped inside while open,
    // returned to whatever opened it on close.
    function openModal(modal, preferred) {
        if (!modal) return;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(modal, preferred);
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
    }

    document.querySelectorAll('.modal').forEach((modal) => {
        const x = modal.querySelector('.close-modal');
        if (x) x.addEventListener('click', () => closeModal(modal));
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal(modal);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('.modal.active').forEach((m) => closeModal(m));
    });

    if (filterBtn) filterBtn.addEventListener('click', () => openModal(filterModal));

    // --- Detail ---------------------------------------------------------
    function showDetail(m) {
        // Remembered so the Propose button knows who it is proposing to.
        detailTarget = m;
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value || '--';
        };

        set('partnerDetailTitle', m.name);
        set('partnerDetailType', m.organization_type);
        set('partnerDetailLocation', m.location);
        set('partnerDetailScore', m.match_score);
        set('partnerDetailBio', m.description);
        set('partnerDetailEmail', m.contact_email);
        set('partnerDetailPhone', m.contact_phone);

        // Highlight the categories that actually drove the match, so the two
        // lists are scannable rather than an undifferentiated wall of tags.
        const detail = m.match_detail || {};
        fillList('partnerDetailOffers', m.offers_labels, detail.they_give_labels);
        fillList('partnerDetailNeeds', m.needs_labels, detail.i_give_labels);

        const badge = document.getElementById('partnerDetailMutual');
        if (badge) badge.classList.toggle('hidden', !detail.mutual);

        // What they work on, with anything you also work on marked. The
        // shared ones are the point -- the rest are shown so the list is
        // their profile rather than only the part that flatters the match.
        const focusBlock = document.getElementById('detailFocusBlock');
        const focusChips = document.getElementById('partnerDetailFocus');
        const focusLabels = m.focus_area_labels || [];
        if (focusBlock && focusChips) {
            focusBlock.classList.toggle('hidden', focusLabels.length === 0);
            const sharedFocus = new Set(detail.shared_focus_labels || []);
            focusChips.innerHTML = focusLabels.map((label) => `
                <span class="${sharedFocus.has(label) ? 'shared' : ''}">${
                    sharedFocus.has(label) ? "<i class='bx bx-check'></i> " : ''
                }${esc(label)}</span>`).join('');
        }

        // Examples cannot be proposed to (they have no owner), so the button is
        // hidden and a short note takes its place. Saving one leads nowhere
        // for the same reason, so that goes too.
        const proposeBtn = document.getElementById('proposeBtn');
        const exampleNote = document.getElementById('detailExampleNote');
        if (proposeBtn) proposeBtn.classList.toggle('hidden', Boolean(m.is_demo));
        if (exampleNote) exampleNote.classList.toggle('hidden', !m.is_demo);
        if (detailSaveBtn) {
            detailSaveBtn.classList.toggle('hidden', Boolean(m.is_demo));
            paintDetailSave(savedIds.has(m.id));
        }
        paintDetailNote(m.id);

        // The shareable profile, for sending to someone without an account.
        const profileLink = document.getElementById('viewProfileBtn');
        if (profileLink) {
            profileLink.href = `organization.html?id=${encodeURIComponent(m.id)}`;
        }

        openModal(detailModal);
    }

    // The note only has somewhere to live once the organization is saved,
    // so the whole block follows that state rather than sitting there
    // inert.
    function paintDetailNote(id) {
        if (!detailNoteBlock) return;
        const isSaved = savedIds.has(id);
        detailNoteBlock.classList.toggle('hidden', !isSaved);
        if (detailNoteStatus) detailNoteStatus.textContent = '';
        if (isSaved && detailNote) detailNote.value = savedNotes.get(id) || '';
    }

    function paintDetailSave(isSaved) {
        if (!detailSaveBtn) return;
        detailSaveBtn.classList.toggle('saved', isSaved);
        detailSaveBtn.setAttribute('aria-pressed', String(isSaved));
        if (detailSaveLabel) detailSaveLabel.textContent = isSaved ? 'Saved' : 'Save';
        const icon = detailSaveBtn.querySelector('i');
        if (icon) icon.className = `bx ${isSaved ? 'bxs-bookmark' : 'bx-bookmark'}`;
    }

    if (detailSaveBtn) {
        detailSaveBtn.addEventListener('click', async () => {
            if (!detailTarget) return;
            const id = detailTarget.id;
            const wantSaved = !savedIds.has(id);
            detailSaveBtn.disabled = true;
            const ok = await toggleSaved(id, wantSaved);
            detailSaveBtn.disabled = false;
            if (!ok) return;
            paintDetailSave(wantSaved);
            paintDetailNote(id);
            // The card behind the dialog carries the same state.
            applyView({ keepPage: true });
        });
    }

    if (detailNoteSave) {
        detailNoteSave.addEventListener('click', async () => {
            if (!detailTarget) return;
            const id = detailTarget.id;
            const note = detailNote.value.trim();
            detailNoteSave.disabled = true;
            detailNoteStatus.textContent = 'Saving…';
            detailNoteStatus.className = 'detail-note-status';
            try {
                const data = await window.api(
                    `/api/saved/${encodeURIComponent(id)}`,
                    { method: 'PATCH', body: { note } },
                );
                savedNotes.set(id, data.note || '');
                // The shortlist entry carries the note too, so the card
                // behind this dialog does not go stale.
                const entry = savedList.find((sv) => sv.id === id);
                if (entry) entry.note = data.note || '';
                detailNoteStatus.textContent = 'Saved.';
                detailNoteStatus.className = 'detail-note-status ok';
                applyView({ keepPage: true });
            } catch (error) {
                detailNoteStatus.textContent =
                    error.message || 'Could not save that note.';
                detailNoteStatus.className = 'detail-note-status error';
            } finally {
                detailNoteSave.disabled = false;
            }
        });
    }

    function fillList(id, labels, highlighted) {
        const ul = document.getElementById(id);
        if (!ul) return;
        ul.innerHTML = '';
        const hot = new Set(highlighted || []);
        if (!labels || labels.length === 0) {
            ul.innerHTML = '<li class="none">Nothing listed</li>';
            return;
        }
        labels.forEach((label) => {
            const li = document.createElement('li');
            li.textContent = label;
            // A match on this category is the reason they are in the list.
            if (hot.has(label)) li.className = 'matched';
            ul.appendChild(li);
        });
    }

    // Save or unsave. Returns whether it worked, so callers can leave the
    // control showing the truth when it did not.
    async function toggleSaved(id, wantSaved) {
        try {
            if (wantSaved) {
                await window.api('/api/saved', {
                    method: 'POST',
                    body: { organization_id: id },
                });
                savedIds.add(id);
            } else {
                await window.api(`/api/saved/${encodeURIComponent(id)}`, {
                    method: 'DELETE',
                });
                savedIds.delete(id);
                // Drop it from the shortlist too, so the list this is
                // rendering from does not still contain what was just removed.
                savedList = savedList.filter((s) => s.id !== id);
                // The server drops the note with the row; this keeps the
                // page from showing one for something no longer saved.
                savedNotes.delete(id);
            }
            updateSavedCount();
            return true;
        } catch (error) {
            window.toast(
                error.message || 'Could not update your saved list.',
                'error',
            );
            return false;
        }
    }

    partnersGrid.addEventListener('click', async (e) => {
        // The bookmark sits inside the card, and the card opens the detail
        // dialog -- without this, saving would also open it.
        const save = e.target.closest('.card-save[data-save-id]');
        if (save) {
            e.stopPropagation();
            const id = Number(save.dataset.saveId);
            const wantSaved = !savedIds.has(id);
            save.disabled = true;
            const ok = await toggleSaved(id, wantSaved);
            save.disabled = false;
            if (!ok) return;
            if (viewMode === 'saved') {
                // Removing the last thing on screen should not leave an empty
                // grid with stale pagination.
                applyView({ keepPage: true });
            } else {
                save.classList.toggle('saved', wantSaved);
                save.setAttribute('aria-pressed', String(wantSaved));
                save.title = wantSaved ? 'Remove from saved' : 'Save for later';
                const icon = save.querySelector('i');
                if (icon) icon.className = `bx ${wantSaved ? 'bxs-bookmark' : 'bx-bookmark'}`;
            }
            return;
        }

        const card = e.target.closest('.partner-card');
        if (!card) return;
        const m = displayed[Number(card.dataset.index)];
        if (m) showDetail(m);
    });

    partnersGrid.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('.partner-card');
        if (!card) return;
        e.preventDefault();
        const m = displayed[Number(card.dataset.index)];
        if (m) showDetail(m);
    });

    // --- Propose a partnership ------------------------------------------
    const proposeModal = document.getElementById('proposeModal');
    const proposeForm = document.getElementById('proposeForm');
    const proposeBtn = document.getElementById('proposeBtn');
    const proposeCancel = document.getElementById('proposeCancel');
    const proposeTitle = document.getElementById('proposeTitle');
    const proposeTimeline = document.getElementById('proposeTimeline');

    // The org whose detail modal is open, and the term selections for it.
    let detailTarget = null;
    const proposeSelected = { proposerGives: new Set(), recipientGives: new Set() };
    let me = null;
    let categoryGroups = [];

    try {
        const [meData, catData] = await Promise.all([
            window.api('/api/me'),
            window.api('/api/categories')
        ]);
        me = meData.organization;
        categoryGroups = catData.groups;
        catData.timelines.forEach((t) => {
            const opt = document.createElement('option');
            opt.value = t.slug;
            opt.textContent = t.label;
            proposeTimeline.appendChild(opt);
        });
        proposeTimeline.value = 'three_months';
    } catch {
        // api() redirects on 401. Anything else leaves the propose flow off,
        // which is better than a half-built form.
    }

    // Terms are drawn from what each side can actually supply: your own offers
    // for your column, theirs for theirs. Anything outside that is not a thing
    // that organization has said it can provide.
    function buildProposePickers(target) {
        const columns = [
            ['proposerGives', document.getElementById('proposerGivesPicker'),
             new Set(me ? me.offers : [])],
            ['recipientGives', document.getElementById('recipientGivesPicker'),
             new Set(target.offers || [])]
        ];

        columns.forEach(([side, container, allowed]) => {
            container.innerHTML = '';
            proposeSelected[side].clear();

            if (allowed.size === 0) {
                container.innerHTML =
                    '<p class="picker-empty">Nothing listed yet.</p>';
                return;
            }

            categoryGroups.forEach((group) => {
                const options = group.categories.filter((c) => allowed.has(c.slug));
                if (options.length === 0) return;

                const wrap = document.createElement('div');
                wrap.className = 'category-group';
                wrap.innerHTML = `<h4>${esc(group.name)}</h4>`;
                const row = document.createElement('div');
                row.className = 'category-options';
                options.forEach((c) => {
                    const id = `prop-${side}-${c.slug}`;
                    const label = document.createElement('label');
                    label.className = 'category-chip';
                    label.setAttribute('for', id);
                    label.innerHTML = `
                        <input type="checkbox" id="${id}" value="${esc(c.slug)}">
                        <span>${esc(c.label)}</span>`;
                    row.appendChild(label);
                });
                wrap.appendChild(row);
                container.appendChild(wrap);
            });

            container.onchange = (e) => {
                const box = e.target.closest('input[type="checkbox"]');
                if (!box) return;
                if (box.checked) proposeSelected[side].add(box.value);
                else proposeSelected[side].delete(box.value);
                box.closest('.category-chip').classList.toggle('checked', box.checked);
                updateProposeCounts();
            };
        });
    }

    function updateProposeCounts() {
        Object.entries(proposeSelected).forEach(([side, set]) => {
            const counter = document.querySelector(`.picker-count[data-for="${side}"]`);
            if (counter) {
                counter.textContent = set.size === 0 ? 'None selected' : `${set.size} selected`;
            }
        });
    }

    // Preselect the categories the match already identified. That is the whole
    // point of proposing from a match: the terms are already worked out.
    function prefillFromMatch(target) {
        const detail = target.match_detail || {};
        [['proposerGives', detail.i_give], ['recipientGives', detail.they_give]]
            .forEach(([side, slugs]) => {
                (slugs || []).forEach((slug) => {
                    const box = document.getElementById(`prop-${side}-${slug}`);
                    if (box) {
                        box.checked = true;
                        box.closest('.category-chip').classList.add('checked');
                        proposeSelected[side].add(slug);
                    }
                });
            });
        updateProposeCounts();
    }

    if (proposeBtn) {
        proposeBtn.addEventListener('click', () => {
            if (!detailTarget || !me) return;
            proposeTitle.textContent = `Propose a Partnership with ${detailTarget.name}`;
            buildProposePickers(detailTarget);
            prefillFromMatch(detailTarget);
            document.getElementById('proposeMessage').value = '';
            setProposeMessage('');
            closeModal(detailModal);
            openModal(proposeModal);
        });
    }

    if (proposeCancel) {
        proposeCancel.addEventListener('click', () => closeModal(proposeModal));
    }

    function setProposeMessage(text) {
        let box = proposeForm.querySelector('.form-message');
        if (!box) {
            box = document.createElement('p');
            box.className = 'form-message';
            proposeForm.prepend(box);
        }
        box.textContent = text;
        box.classList.toggle('hidden', !text);
    }

    if (proposeForm) {
        proposeForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!detailTarget) return;

            const submitBtn = proposeForm.querySelector('button[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Sending...';
            setProposeMessage('');

            try {
                await window.api('/api/proposals', {
                    method: 'POST',
                    body: {
                        recipient_id: detailTarget.id,
                        proposer_gives: [...proposeSelected.proposerGives],
                        recipient_gives: [...proposeSelected.recipientGives],
                        timeline: proposeTimeline.value,
                        message: document.getElementById('proposeMessage').value.trim()
                    }
                });
                closeModal(proposeModal);
                // Queued rather than shown: the redirect below would destroy
                // a toast raised here before anyone could read it. common.js
                // picks this up on the dashboard, which is the first moment
                // there is a page around long enough to say it worked.
                window.toastAfterRedirect(
                    `Proposal sent to ${detailTarget.name}.`);
                window.location.href = 'ppdashboard.html#outgoing';
            } catch (error) {
                setProposeMessage(error.message);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send proposal';
            }
        });
    }

    // --- Filters --------------------------------------------------------
    // One place that knows how many filters are on, so the count on the
    // button cannot drift out of step with the checkboxes behind it.
    function paintFilterButton() {
        if (!filterBtn) return;
        const active = [mutualOnly, sharedFocusOnly].filter(Boolean).length;
        filterBtn.classList.toggle('has-filters', active > 0);
        filterBtn.innerHTML = active
            ? `<i class='bx bx-filter-alt'></i> Filters (${active})`
            : `<i class='bx bx-filter-alt'></i> Filters`;
    }

    if (filterForm) {
        filterForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const box = document.getElementById('mutualOnlyInput');
            const focusBox = document.getElementById('sharedFocusInput');
            mutualOnly = Boolean(box && box.checked);
            sharedFocusOnly = Boolean(focusBox && focusBox.checked);
            paintFilterButton();
            closeModal(filterModal);
            // Both filters describe the match list, and the shortlist is
            // deliberately not filtered by either -- it is what someone chose
            // to keep. Applying one from inside the saved view used to reload
            // the matches and then render the shortlist unchanged, so the
            // button claimed a filter the visible list did not have. Asking
            // for a filter is asking to see the list it applies to.
            if (viewMode === 'saved') {
                await setViewMode('matches');
            }
            await loadMatches();
        });
    }

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', async () => {
            filterForm.reset();
            mutualOnly = false;
            sharedFocusOnly = false;
            paintFilterButton();
            closeModal(filterModal);
            if (viewMode === 'saved') {
                await setViewMode('matches');
            }
            await loadMatches();
        });
    }

    prevBtn.addEventListener('click', () => goToPage(currentPage - 1));
    nextBtn.addEventListener('click', () => goToPage(currentPage + 1));
    // Wrapped rather than passed directly: the handler receives an Event,
    // which would arrive here as applyView's options object.
    searchInput.addEventListener('input', () => applyView());

    if (showAllBtn) {
        showAllBtn.addEventListener('click', () => {
            showAll = !showAll;
            // Back to the first page on collapse, so turning paging back on
            // does not land on a page number that no longer exists.
            currentPage = 1;
            render();
            partnersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }

    // The page holds a different number of cards at each column count, so a
    // window crossing a breakpoint has to be re-paged -- otherwise a page
    // built for three columns keeps showing six cards in two.
    //
    // Listening to the queries themselves rather than to `resize`: these
    // fire once, when a breakpoint is actually crossed, instead of on every
    // pixel of a drag with a debounce guessing at when it stopped.
    PAGE_SIZES.forEach(({ query }) => {
        const mql = window.matchMedia(query);
        const onChange = () => {
            // A page number from the previous width can point past the end of
            // the list once the page holds more.
            currentPage = 1;
            if (displayed.length) render();
        };
        if (mql.addEventListener) mql.addEventListener('change', onChange);
        else mql.addListener(onChange);   // Safari < 14
    });

    // Arriving from the dashboard's "Two-way matches" card, which links to
    // ppsearch.html?mutual=1. The filter UI is synced too, so the state is
    // visible and can be cleared the usual way rather than being a hidden
    // mode that only the URL knows about.
    if (new URLSearchParams(location.search).get('mutual') === '1') {
        mutualOnly = true;
        const box = document.getElementById('mutualOnlyInput');
        if (box) box.checked = true;
        paintFilterButton();
    }

    await loadMatches();
});
