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

    // --- Browse -----------------------------------------------------------
    // The directory, paged by the server rather than sliced in the browser.
    // Matches and the shortlist are both lists this page holds in full, so
    // paging them is arithmetic on an array. Browse cannot work that way --
    // the whole point is that it is not capped at fifty and not restricted
    // to organizations that already overlap with you -- so its page number
    // is a request parameter and its total comes back with the results.
    const browseState = { page: 1, pages: 1, total: 0, sort: 'name' };

    // The directory's own filters, mirroring what /api/organizations accepts.
    // Sets rather than arrays for the three category pickers: every read is
    // "is this slug chosen", once per checkbox per render.
    const browseFilters = {
        offers: new Set(),
        needs: new Set(),
        focus: new Set(),
        type: '',
        location: '',
        remote: false,
    };
    let browseTimer = null;
    const browseToggle = document.getElementById('browseToggle');
    const browseBar = document.getElementById('browseBar');
    const browseSort = document.getElementById('browseSort');

    let savedIds = new Set();
    let savedList = [];
    // id -> note, so a card in the shortlist and the dialog behind it read
    // the same text without either having to re-fetch.
    let savedNotes = new Map();
    let viewMode = 'matches';   // 'matches' | 'browse' | 'saved'

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

    async function loadBrowse() {
        partnersGrid.setAttribute('aria-busy', 'true');
        renderSkeletonCards();
        const params = new URLSearchParams({
            page: String(browseState.page),
            sort: browseState.sort,
            per_page: String(browsePageSize()),
        });
        const term = searchQuery();
        if (term) params.set('q', term);

        // Only what is actually set. An empty parameter is not the same as an
        // absent one to a reader of the URL, and the endpoint would have to
        // treat "" as "any" for every field rather than simply not being
        // asked about it.
        if (browseFilters.offers.size) {
            params.set('offers', [...browseFilters.offers].join(','));
        }
        if (browseFilters.needs.size) {
            params.set('needs', [...browseFilters.needs].join(','));
        }
        if (browseFilters.focus.size) {
            params.set('focus', [...browseFilters.focus].join(','));
        }
        if (browseFilters.type) params.set('type', browseFilters.type);
        if (browseFilters.location) params.set('location', browseFilters.location);
        if (browseFilters.remote) params.set('remote', '1');

        try {
            const data = await window.api(`/api/organizations?${params}`);
            displayed = data.organizations || [];
            browseState.page = data.page;
            browseState.pages = data.pages;
            browseState.total = data.total;
            // The star states ride along, so they are right on first paint
            // rather than filling in after a second request.
            savedIds = new Set(data.saved_ids || []);
            updateSavedCount();
        } catch (error) {
            partnersGrid.removeAttribute('aria-busy');
            partnersGrid.innerHTML =
                `<div class="empty-state"><p>${esc(error.message)}</p></div>`;
            updatePagination(1);
            return;
        }
        partnersGrid.removeAttribute('aria-busy');
        render();
    }

    // Asked for whole pages so the grid never ends on a half-filled row, the
    // same reason the client-side page sizes are even numbers.
    function browsePageSize() {
        const size = pageSize();
        return Number.isFinite(size) ? size * 2 : 24;
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
        if (browseToggle) {
            browseToggle.setAttribute('aria-pressed', String(mode === 'browse'));
            browseToggle.classList.toggle('active', mode === 'browse');
        }
        if (browseBar) browseBar.classList.toggle('hidden', mode !== 'browse');
        // The dialog now carries a set of filters for each list and shows the
        // set that applies, so the button stays available in every view. The
        // two match filters are still never applied to the directory: they
        // are answered by comparing two profiles, and most of the directory
        // is organizations you do not match with at all.
        paintFilterSections();
        paintFilterButton();
        if (searchInput) {
            searchInput.placeholder = mode === 'browse'
                ? 'Search every organization...'
                : 'Search partners...';
        }

        currentPage = 1;
        if (mode === 'browse') {
            browseState.page = 1;
            await loadBrowse();
            return;
        }
        // Re-fetched on every switch back in, not just the first: scores are
        // computed against the current profile, and the shortlist is where a
        // stale one would be least obvious.
        if (mode === 'saved' && !(await loadSaved())) return;
        applyView();
    }

    if (savedToggle) {
        savedToggle.addEventListener('click', () => {
            setViewMode(viewMode === 'saved' ? 'matches' : 'saved');
        });
    }

    if (browseToggle) {
        browseToggle.addEventListener('click', () => {
            setViewMode(viewMode === 'browse' ? 'matches' : 'browse');
        });
    }

    if (browseSort) {
        browseSort.addEventListener('change', () => {
            browseState.sort = browseSort.value;
            browseState.page = 1;
            loadBrowse();
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

        // Browse is already exactly the page the server was asked for.
        // Filtering it again here would hide rows out of a page whose size
        // and total the pagination has already been told, so the count and
        // the grid would disagree.
        if (viewMode === 'browse') {
            render();
            return;
        }

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
    // Read here rather than passed down from applyView: render() also runs on
    // paging and on a breakpoint change, where no one recomputed the query.
    function searchQuery() {
        return (searchInput.value || '').trim();
    }

    function render() {
        partnersGrid.innerHTML = '';
        const banner = document.getElementById('exampleBanner');
        if (banner) banner.classList.toggle('hidden', !showingExamples);

        const browsing = viewMode === 'browse';
        const size = pageSize();
        const pages = browsing
            ? browseState.pages
            : Math.max(1, Math.ceil(displayed.length / size));
        if (!browsing && currentPage > pages) currentPage = pages;

        if (displayed.length === 0) {
            // An empty state should say what to do next, not only that there
            // is nothing here. Which of these applies is knowable -- a
            // filter is on, a search matched nothing, or the profile itself
            // is too narrow to match anyone -- and each has a different
            // answer, so the action offered is the one that fits.
            let message;
            let action = '';
            const searching = Boolean(searchQuery());

            if (viewMode === 'browse') {
                message = searching
                    ? 'No organization here matches that search. It looks at '
                      + 'names, locations and descriptions.'
                    : 'No organizations have finished a profile yet.';
                if (searching) {
                    action = '<button type="button" class="btn-ghost" '
                        + 'data-empty-action="clear-search">Clear the search</button>';
                }
            } else if (viewMode === 'saved') {
                message = savedList.length === 0
                    ? 'Nothing saved yet. Use the bookmark on a match to keep '
                      + 'it here — saved organizations stay on this list even '
                      + 'if your profile changes and they stop matching.'
                    : 'No saved organizations match that search.';
            } else if (searching) {
                message = 'Nothing here matches that search. It looks at '
                    + 'names, locations, and what each organization needs and '
                    + 'offers.';
                action = '<button type="button" class="btn-ghost" '
                    + 'data-empty-action="clear-search">Clear the search</button>';
            } else if (sharedFocusOnly || mutualOnly) {
                message = sharedFocusOnly
                    ? 'No matches work on the same things you do.'
                    : 'No two-way matches yet — nobody currently needs what '
                      + 'you offer and offers what you need.';
                action = '<button type="button" class="btn-ghost" '
                    + 'data-empty-action="clear-filters">Clear filters</button>';
            } else {
                // The one case that is about the profile rather than the
                // controls: matching only considers organizations that
                // overlap in one direction or the other, so a short list of
                // needs and offers is what makes the result empty.
                message = 'No matches yet. Every match is built from what you '
                    + 'need and what you can offer, so the quickest way to '
                    + 'widen this is to list more of either.';
                action = '<a class="btn-primary" href="onboarding.html">'
                    + 'Add to your profile</a>';
            }

            partnersGrid.innerHTML =
                `<div class="empty-state">
                    <p>${esc(message)}</p>
                    ${action ? `<div class="empty-actions">${action}</div>` : ''}
                </div>`;
            updatePagination(pages);
            return;
        }

        // Browse already holds exactly one page; slicing it again would
        // show a fraction of what the server was asked for and what the
        // pagination below has been told about.
        const start = (browsing || showAll) ? 0 : (currentPage - 1) * size;
        const slice = (browsing || showAll)
            ? displayed
            : displayed.slice(start, start + size);
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

            // Browse lists organizations that have nothing to exchange with
            // you, which matches never did. A bare "0" in the score badge
            // reads as a judgement on them rather than on the pairing, and
            // "Why match" over an empty list reads as a page that failed to
            // load. Both say what is actually true instead.
            const noOverlap = !m.match_score
                && !(m.match_detail.they_give || []).length
                && !(m.match_detail.i_give || []).length;

            const reasons = (m.reasons || [])
                .map((r) => `<li>${esc(r)}</li>`).join('')
                || '<li class="none">Nothing either of you has listed lines '
                   + 'up yet.</li>';

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
                <div class="partner-score${noOverlap ? ' none' : ''}"${
                    noOverlap ? ' title="No overlap with your profile yet"' : ''
                }>${noOverlap ? '&mdash;' : m.match_score}</div>
                ${saveBtn}
                <div class="partner-content">
                    <div class="card-badge-slot">${badge}</div>
                    <h3>${esc(m.name)}</h3>
                    <p class="card-line card-type"><strong>Type:</strong> ${esc(m.organization_type)}</p>
                    <p class="card-line card-location"><strong>Location:</strong> ${esc(m.location)}</p>
                    <p class="card-line card-offers"><strong>Offers:</strong> ${esc((m.offers_labels || []).join(', '))}</p>
                    <div class="match-reasons">
                        <strong>${noOverlap ? 'Overlap:' : 'Why match:'}</strong>
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
        if (viewMode === 'browse') {
            const { page, total } = browseState;
            const per = browsePageSize();
            if (total === 0) {
                pageIndicator.textContent = 'No results';
            } else {
                const first = (page - 1) * per + 1;
                const last = Math.min(page * per, total);
                pageIndicator.textContent =
                    `Page ${page} of ${browseState.pages}  ·  ${first}-${last} of ${total}`;
            }
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= browseState.pages;
            // Show-all is arithmetic over a list this page holds; the
            // directory is not that list and could be any size.
            if (showAllBtn) showAllBtn.hidden = true;
            return;
        }

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
        if (viewMode === 'browse') {
            const wanted = Math.min(Math.max(1, page), browseState.pages);
            if (wanted === browseState.page) return;
            browseState.page = wanted;
            loadBrowse().then(() => {
                partnersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
            return;
        }
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

    if (filterBtn) {
        filterBtn.addEventListener('click', () => {
            paintFilterSections();
            openModal(filterModal);
        });
    }

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

        paintScoreBreakdown(m, detail);

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

    // Where the number came from. matching.py already does this arithmetic to
    // produce the score; it used to be discarded before anyone could see it,
    // leaving a bare number to be taken on faith as the basis for the whole
    // ranking.
    function paintScoreBreakdown(m, detail) {
        const block = document.getElementById('detailScoreWhy');
        const list = document.getElementById('detailScoreBreakdown');
        const total = document.getElementById('detailScoreTotal');
        if (!block || !list || !total) return;

        const parts = detail.breakdown || [];
        // An older payload has no breakdown in it. Hiding the block is
        // better than showing an empty explanation of a visible number.
        block.classList.toggle('hidden', parts.length === 0);
        if (parts.length === 0) return;

        // Closed each time the dialog is opened for someone new: it is a
        // second question, and it should not be left open from the last card.
        block.open = false;

        list.innerHTML = parts.map((part) => `
            <li>
                <span class="score-label">${esc(part.label)}</span>
                <span class="score-points">+${esc(part.points)}</span>
            </li>`).join('');

        // The cap is stated rather than left to look like bad arithmetic:
        // a breakdown adding to 118 beside a score of 100 otherwise reads as
        // a bug in the page.
        total.textContent = detail.capped
            ? `${detail.raw_score} total, capped at ${detail.max_score}.`
            : `${m.match_score} out of ${detail.max_score || 100}.`;
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

        // The empty state offers whichever way out actually applies. These
        // are rendered into the grid, so they are handled here alongside the
        // cards rather than bound at load, when they do not exist yet.
        const emptyAction = e.target.closest('[data-empty-action]');
        if (emptyAction) {
            if (emptyAction.dataset.emptyAction === 'clear-search') {
                searchInput.value = '';
                if (viewMode === 'browse') {
                    browseState.page = 1;
                    await loadBrowse();
                } else {
                    applyView();
                }
                searchInput.focus();
            } else {
                mutualOnly = false;
                sharedFocusOnly = false;
                if (filterForm) filterForm.reset();
                paintFilterButton();
                await loadMatches();
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
    // The same payload already carries these two; the filter dialog builds
    // its type list and focus picker from them rather than making a second
    // request for a vocabulary this page has already been told.
    let organizationTypes = [];
    let focusAreas = [];

    try {
        const [meData, catData] = await Promise.all([
            window.api('/api/me'),
            window.api('/api/categories')
        ]);
        me = meData.organization;
        categoryGroups = catData.groups;
        organizationTypes = catData.organization_types || [];
        focusAreas = catData.focus_areas || [];
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
    // button cannot drift out of step with the controls behind it. Which
    // filters count depends on which list is on screen -- the match filters
    // do nothing to the directory and the directory filters do nothing to
    // the match list, so counting both would advertise filters that are not
    // being applied to what the reader is looking at.
    function activeFilterCount() {
        if (viewMode === 'browse') {
            return [
                browseFilters.offers.size > 0,
                browseFilters.needs.size > 0,
                browseFilters.focus.size > 0,
                Boolean(browseFilters.type),
                Boolean(browseFilters.location),
                browseFilters.remote,
            ].filter(Boolean).length;
        }
        return [mutualOnly, sharedFocusOnly].filter(Boolean).length;
    }

    function paintFilterButton() {
        if (!filterBtn) return;
        const active = activeFilterCount();
        filterBtn.classList.toggle('has-filters', active > 0);
        filterBtn.innerHTML = active
            ? `<i class='bx bx-filter-alt'></i> Filters (${active})`
            : `<i class='bx bx-filter-alt'></i> Filters`;
    }

    // Built once, the first time the dialog is opened while browsing. The
    // vocabulary is the same one the propose dialog fetched at load, so this
    // costs no request.
    let filterPickersBuilt = false;

    function buildFilterPickers() {
        if (filterPickersBuilt || !categoryGroups.length) return;
        filterPickersBuilt = true;

        const typeSelect = document.getElementById('filterType');
        if (typeSelect && organizationTypes.length) {
            organizationTypes.forEach((label) => {
                const opt = document.createElement('option');
                opt.value = label;
                opt.textContent = label;
                typeSelect.appendChild(opt);
            });
        }

        const build = (containerId, options, key, prefix) => {
            const container = document.getElementById(containerId);
            if (!container) return;
            container.innerHTML = '';
            options.forEach((group) => {
                const entries = group.categories || group.items;
                if (!entries || !entries.length) return;
                const wrap = document.createElement('div');
                wrap.className = 'category-group';
                if (group.name) wrap.innerHTML = `<h4>${esc(group.name)}</h4>`;
                const row = document.createElement('div');
                row.className = 'category-options';
                entries.forEach((c) => {
                    const id = `${prefix}-${c.slug}`;
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

            // Selections are read on Apply rather than tracked per click:
            // these do nothing until the form is submitted, so the set and
            // the checkboxes cannot drift apart in between.
            container.addEventListener('change', (e) => {
                const box = e.target.closest('input[type="checkbox"]');
                if (!box) return;
                box.closest('.category-chip').classList.toggle('checked', box.checked);
                paintFilterCounts();
            });
        };

        build('filterOffersPicker', categoryGroups, 'offers', 'filter-offers');
        build('filterNeedsPicker', categoryGroups, 'needs', 'filter-needs');
        // Focus areas are a flat list, wrapped so the same builder handles it.
        build('filterFocusPicker', [{ name: '', categories: focusAreas }],
              'focus', 'filter-focus');
        paintFilterCounts();
    }

    // How many are ticked inside each collapsed section, so a section that is
    // doing something says so without having to be opened.
    function paintFilterCounts() {
        [['filterOffersPicker', 'filterOffersCount'],
         ['filterNeedsPicker', 'filterNeedsCount'],
         ['filterFocusPicker', 'filterFocusCount']].forEach(([pickerId, countId]) => {
            const picker = document.getElementById(pickerId);
            const badge = document.getElementById(countId);
            if (!picker || !badge) return;
            const n = picker.querySelectorAll('input:checked').length;
            badge.textContent = n ? String(n) : '';
            badge.hidden = n === 0;
        });
    }

    function readFilterPicker(pickerId) {
        const picker = document.getElementById(pickerId);
        if (!picker) return new Set();
        return new Set([...picker.querySelectorAll('input:checked')]
            .map((box) => box.value));
    }

    // The dialog shows the filters that apply to the list on screen.
    function paintFilterSections() {
        const browsing = viewMode === 'browse';
        const match = document.getElementById('filterMatchSection');
        const browse = document.getElementById('filterBrowseSection');
        if (match) match.hidden = browsing;
        if (browse) browse.hidden = !browsing;
        if (browsing) buildFilterPickers();
    }

    if (filterForm) {
        filterForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            closeModal(filterModal);

            if (viewMode === 'browse') {
                browseFilters.offers = readFilterPicker('filterOffersPicker');
                browseFilters.needs = readFilterPicker('filterNeedsPicker');
                browseFilters.focus = readFilterPicker('filterFocusPicker');
                const typeSel = document.getElementById('filterType');
                const locInput = document.getElementById('filterLocation');
                const remoteBox = document.getElementById('filterRemote');
                browseFilters.type = typeSel ? typeSel.value : '';
                browseFilters.location = locInput ? locInput.value.trim() : '';
                browseFilters.remote = Boolean(remoteBox && remoteBox.checked);
                paintFilterButton();
                // Back to the first page: the filters just changed what the
                // pages are, so page four of the previous result set is not a
                // place in this one.
                browseState.page = 1;
                await loadBrowse();
                return;
            }

            const box = document.getElementById('mutualOnlyInput');
            const focusBox = document.getElementById('sharedFocusInput');
            mutualOnly = Boolean(box && box.checked);
            sharedFocusOnly = Boolean(focusBox && focusBox.checked);
            paintFilterButton();
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
            // form.reset() returns the checkboxes to their markup defaults but
            // leaves the .checked class the chip styling is drawn from, so the
            // pickers would still look ticked.
            filterForm.reset();
            filterForm.querySelectorAll('.category-chip.checked')
                .forEach((chip) => chip.classList.remove('checked'));
            paintFilterCounts();
            closeModal(filterModal);

            if (viewMode === 'browse') {
                browseFilters.offers.clear();
                browseFilters.needs.clear();
                browseFilters.focus.clear();
                browseFilters.type = '';
                browseFilters.location = '';
                browseFilters.remote = false;
                paintFilterButton();
                browseState.page = 1;
                await loadBrowse();
                return;
            }

            mutualOnly = false;
            sharedFocusOnly = false;
            paintFilterButton();
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
    //
    // Browsing searches the whole directory, which means a request rather
    // than a filter over what is already here -- debounced, because that is
    // one request per keystroke otherwise.
    searchInput.addEventListener('input', () => {
        if (viewMode !== 'browse') {
            applyView();
            return;
        }
        clearTimeout(browseTimer);
        browseTimer = setTimeout(() => {
            browseState.page = 1;
            loadBrowse();
        }, 300);
    });

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
            if (viewMode === 'browse') {
                // per_page is a request parameter here, so a new width means
                // a new request rather than a re-slice.
                browseState.page = 1;
                loadBrowse();
                return;
            }
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
