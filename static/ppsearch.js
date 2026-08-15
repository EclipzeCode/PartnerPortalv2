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
    const pageIndicator = document.getElementById('pageIndicator');

    const filterBtn = document.getElementById('filter-btn');
    const addBtn = document.getElementById('add-btn');
    const filterModal = document.getElementById('filterModal');
    const detailModal = document.getElementById('partnerDetailModal');
    const filterForm = document.getElementById('filterForm');
    const clearFiltersBtn = document.getElementById('clearFiltersBtn');

    const PAGE_SIZE = 9;
    const esc = window.escapeHtml;

    let allMatches = [];
    let exampleMatches = [];
    let showingExamples = false;
    let displayed = [];
    let currentPage = 1;
    let mutualOnly = false;

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

    let savedIds = new Set();
    let savedList = [];
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

    function applyView() {
        const q = (searchInput.value || '').toLowerCase().trim();
        const norm = (v) => (v || '').toLowerCase();

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
            currentPage = 1;
            render();
            return;
        }

        // No real matches yet, but seeded examples exist: show those instead
        // of an empty page. They are visibly flagged and cannot be proposed to.
        showingExamples = allMatches.length === 0 && exampleMatches.length > 0;
        const source = showingExamples ? exampleMatches : allMatches;

        displayed = q
            ? source.filter((m) =>
                norm(m.name).includes(q) ||
                norm(m.organization_type).includes(q) ||
                norm(m.location).includes(q) ||
                (m.offers_labels || []).some((l) => norm(l).includes(q)) ||
                (m.needs_labels || []).some((l) => norm(l).includes(q)))
            : [...source];

        currentPage = 1;
        render();
    }

    // --- Rendering ------------------------------------------------------
    function render() {
        partnersGrid.innerHTML = '';
        const banner = document.getElementById('exampleBanner');
        if (banner) banner.classList.toggle('hidden', !showingExamples);

        const pages = Math.max(1, Math.ceil(displayed.length / PAGE_SIZE));
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
                message = mutualOnly
                    ? 'No two-way matches yet. Turn off the two-way filter to ' +
                      'see one-directional matches.'
                    : 'No matches yet. Adding more needs and offers to your ' +
                      'profile widens the search.';
            }
            partnersGrid.innerHTML = `<p class="empty-state">${esc(message)}</p>`;
            updatePagination(pages);
            return;
        }

        const start = (currentPage - 1) * PAGE_SIZE;
        displayed.slice(start, start + PAGE_SIZE).forEach((m, offset) => {
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

            card.innerHTML = `
                <div class="partner-score">${m.match_score}</div>
                ${saveBtn}
                <div class="partner-content">
                    ${badge}
                    <h3>${esc(m.name)}</h3>
                    <p><strong>Type:</strong> ${esc(m.organization_type)}</p>
                    <p><strong>Location:</strong> ${esc(m.location)}</p>
                    <p><strong>Offers:</strong> ${esc((m.offers_labels || []).join(', '))}</p>
                    <div class="match-reasons">
                        <strong>Why match:</strong>
                        <ul>${reasons}</ul>
                    </div>
                </div>
            `;
            partnersGrid.appendChild(card);
        });

        updatePagination(pages);
    }

    function updatePagination(pages) {
        const count = displayed.length;
        if (count === 0) {
            pageIndicator.textContent = 'No results';
        } else {
            const first = (currentPage - 1) * PAGE_SIZE + 1;
            const last = Math.min(currentPage * PAGE_SIZE, count);
            pageIndicator.textContent =
                `Page ${currentPage} of ${pages}  ·  ${first}-${last} of ${count}`;
        }
        prevBtn.disabled = currentPage <= 1;
        nextBtn.disabled = currentPage >= pages;
    }

    function goToPage(page) {
        const pages = Math.max(1, Math.ceil(displayed.length / PAGE_SIZE));
        currentPage = Math.min(Math.max(1, page), pages);
        render();
        partnersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // --- Modals ---------------------------------------------------------
    function openModal(modal) {
        if (!modal) return;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
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

        // The shareable profile, for sending to someone without an account.
        const profileLink = document.getElementById('viewProfileBtn');
        if (profileLink) {
            profileLink.href = `organization.html?id=${encodeURIComponent(m.id)}`;
        }

        openModal(detailModal);
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
            // The card behind the dialog carries the same state.
            applyView();
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
                applyView();
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
    if (filterForm) {
        filterForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const box = document.getElementById('mutualOnlyInput');
            mutualOnly = Boolean(box && box.checked);
            filterBtn.classList.toggle('has-filters', mutualOnly);
            filterBtn.innerHTML = mutualOnly
                ? `<i class='bx bx-filter-alt'></i> Filters (1)`
                : `<i class='bx bx-filter-alt'></i> Filters`;
            closeModal(filterModal);
            await loadMatches();
        });
    }

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', async () => {
            filterForm.reset();
            mutualOnly = false;
            filterBtn.classList.remove('has-filters');
            filterBtn.innerHTML = `<i class='bx bx-filter-alt'></i> Filters`;
            closeModal(filterModal);
            await loadMatches();
        });
    }

    prevBtn.addEventListener('click', () => goToPage(currentPage - 1));
    nextBtn.addEventListener('click', () => goToPage(currentPage + 1));
    searchInput.addEventListener('input', applyView);

    // Arriving from the dashboard's "Two-way matches" card, which links to
    // ppsearch.html?mutual=1. The filter UI is synced too, so the state is
    // visible and can be cleared the usual way rather than being a hidden
    // mode that only the URL knows about.
    if (new URLSearchParams(location.search).get('mutual') === '1') {
        mutualOnly = true;
        const box = document.getElementById('mutualOnlyInput');
        if (box) box.checked = true;
        if (filterBtn) {
            filterBtn.classList.add('has-filters');
            filterBtn.innerHTML = `<i class='bx bx-filter-alt'></i> Filters (1)`;
        }
    }

    await loadMatches();
});
