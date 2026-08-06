document.addEventListener('DOMContentLoaded', () => {
    const partnersGrid = document.getElementById('partnersGrid');
    const searchInput = document.getElementById('searchInput');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const pageIndicator = document.getElementById('pageIndicator');

    const addBtn = document.getElementById('add-btn');
    const filterBtn = document.getElementById('filter-btn');
    const addPartnerModal = document.getElementById('addPartnerModal');
    const filterModal = document.getElementById('filterModal');
    const detailModal = document.getElementById('partnerDetailModal');
    const addPartnerForm = document.getElementById('addPartnerForm');
    const filterForm = document.getElementById('filterForm');
    const clearFiltersBtn = document.getElementById('clearFiltersBtn');

    const PAGE_SIZE = 9;

    let allPartners = [];
    let displayedPartners = [];
    let currentPage = 1;
    // Server-side filters from the filter modal, e.g. { Location: 'Austin' }.
    let activeFilters = {};

    // Load onboarding profile
    const userProfile = JSON.parse(localStorage.getItem('partnerPortalOnboardingProfile'));

    // Partner records are supplied by users, so any value interpolated into
    // markup has to be escaped or a crafted name becomes stored XSS.
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // --- Data ---------------------------------------------------------------
    async function fetchPartners() {
        // Only non-empty filters are sent; the API treats an absent parameter
        // as "no constraint" but an empty one as LIKE '%%'.
        const params = new URLSearchParams(
            Object.entries(activeFilters).filter(([, v]) => v)
        );
        const query = params.toString() ? `?${params}` : '';

        try {
            const res = await fetch(`${window.API_BASE}/api/partners${query}`);
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            allPartners = await res.json();
        } catch (error) {
            console.error('Could not load partners:', error);
            allPartners = [];
            partnersGrid.innerHTML =
                '<p class="empty-state">Could not load partners right now. ' +
                'Please make sure the server is running and refresh.</p>';
            return;
        }

        applyView();
    }

    // Ranks, then applies the search box text. Called after any change to the
    // underlying data, the filters, or the search query.
    function applyView() {
        const ranked = userProfile
            ? rankPartners(userProfile, allPartners)
            : [...allPartners];

        const q = (searchInput.value || '').toLowerCase().trim();
        const norm = value => (value || '').toLowerCase();

        displayedPartners = q
            ? ranked.filter(p =>
                norm(p.Name).includes(q) ||
                norm(p.OrganizationType).includes(q) ||
                norm(p.Expertise).includes(q))
            : ranked;

        currentPage = 1;
        renderPartners();
    }

    // --- Matching -----------------------------------------------------------
    function rankPartners(user, partners) {
        return partners.map(p => {
            const { score, reasons } = calculateScore(user, p);
            return { ...p, matchScore: score, reasons };
        }).sort((a, b) => b.matchScore - a.matchScore);
    }

    function calculateScore(user, partner) {
        let score = 0;
        let reasons = [];

        const normalize = str => (str || "").toLowerCase();

        const userNeeds = normalize(user.needs);
        const userOffers = normalize(user.offers);

        const pExpertise = normalize(partner.Expertise);
        const pResources = normalize(partner.Resources);
        const pBio = normalize(partner.Bio);
        const pType = normalize(partner.OrganizationType);
        const pLocation = normalize(partner.Location);

        // 1. NEED -> PARTNER MATCH (most important)
        if (userNeeds.includes(pExpertise) || pExpertise.includes(userNeeds)) {
            score += 30;
            reasons.push("Matches your needs");
        }

        if (userNeeds.includes(pResources) || pResources.includes(userNeeds)) {
            score += 25;
            reasons.push("Provides resources you need");
        }

        // 2. REVERSE MATCH (mutual benefit)
        if (userOffers.includes(pExpertise) || pExpertise.includes(userOffers)) {
            score += 15;
            reasons.push("You can help them");
        }

        // 3. TYPE COMPATIBILITY
        if (user.organization_type && partner.OrganizationType) {
            if (user.organization_type.toLowerCase() !== pType) {
                score += 10;
                reasons.push("Complementary organization type");
            }
        }

        // 4. LOCATION
        if (user.location && partner.Location) {
            if (normalize(user.location).includes(pLocation)) {
                score += 10;
                reasons.push("Same location");
            }
        }

        // 5. BIO KEYWORD MATCH
        if (pBio.includes(userNeeds)) {
            score += 10;
            reasons.push("Similar goals");
        }

        return {
            score: Math.min(score, 100),
            reasons
        };
    }

    // --- Pagination ---------------------------------------------------------
    function totalPages() {
        return Math.max(1, Math.ceil(displayedPartners.length / PAGE_SIZE));
    }

    function updatePaginationControls() {
        const pages = totalPages();
        const count = displayedPartners.length;

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
        currentPage = Math.min(Math.max(1, page), totalPages());
        renderPartners();
        // Bring the top of the results back into view after a page change,
        // otherwise you land mid-list on the new page.
        partnersGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // --- Rendering ----------------------------------------------------------
    function renderPartners() {
        partnersGrid.innerHTML = "";

        // A filter can shrink the list below the current page.
        if (currentPage > totalPages()) currentPage = totalPages();

        if (displayedPartners.length === 0) {
            const filtered = Object.values(activeFilters).some(Boolean);
            partnersGrid.innerHTML = filtered
                ? '<p class="empty-state">No partners match those filters. ' +
                  'Try clearing them from the Filters panel.</p>'
                : '<p class="empty-state">No partners match your search yet.</p>';
            updatePaginationControls();
            return;
        }

        const start = (currentPage - 1) * PAGE_SIZE;
        const pageItems = displayedPartners.slice(start, start + PAGE_SIZE);

        pageItems.forEach((partner, offset) => {
            const card = document.createElement('div');
            card.className = 'partner-card';
            // The card opens the detail modal, so it has to be reachable and
            // operable without a mouse.
            card.tabIndex = 0;
            card.setAttribute('role', 'button');
            card.setAttribute('aria-label', `View details for ${partner.Name || 'partner'}`);
            // Index into displayedPartners, so the handler can find the record
            // without depending on the row having an id column.
            card.dataset.index = String(start + offset);

            // `reasons` is generated by this file, not user input, but escape
            // it anyway so the rule "everything interpolated is escaped" holds.
            const reasonsHTML = partner.reasons
                ? partner.reasons.map(r => `<li>${escapeHtml(r)}</li>`).join("")
                : "";

            card.innerHTML = `
                <div class="partner-score">${partner.matchScore || "--"}</div>
                <div class="partner-content">
                    <h3>${escapeHtml(partner.Name)}</h3>
                    <p><strong>Type:</strong> ${escapeHtml(partner.OrganizationType)}</p>
                    <p><strong>Expertise:</strong> ${escapeHtml(partner.Expertise)}</p>
                    <p><strong>Resources:</strong> ${escapeHtml(partner.Resources)}</p>

                    <div class="match-reasons">
                        <strong>Why match:</strong>
                        <ul>${reasonsHTML}</ul>
                    </div>
                </div>
            `;

            partnersGrid.appendChild(card);
        });

        updatePaginationControls();
    }

    // --- Modals -------------------------------------------------------------
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

    function closeAllModals() {
        document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'));
        document.body.style.overflow = 'auto';
    }

    // Each modal closes via its own × , a click on the backdrop, or Escape.
    document.querySelectorAll('.modal').forEach(modal => {
        const closeX = modal.querySelector('.close-modal');
        if (closeX) closeX.addEventListener('click', () => closeModal(modal));
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal(modal);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAllModals();
    });

    if (addBtn) addBtn.addEventListener('click', () => {
        setFormMessage(addPartnerForm, '');
        openModal(addPartnerModal);
    });

    if (filterBtn) filterBtn.addEventListener('click', () => openModal(filterModal));

    // --- Partner detail -----------------------------------------------------
    function showPartnerDetail(partner) {
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value || '--';
        };

        set('partnerDetailTitle', partner.Name);
        set('partnerDetailType', partner.OrganizationType);
        set('partnerDetailExpertise', partner.Expertise);
        set('partnerDetailResources', partner.Resources);
        set('partnerDetailBio', partner.Bio);
        set('partnerDetailEmail', partner.Email);
        set('partnerDetailPhone', partner.PhoneNumber);
        set('partnerDetailLocation', partner.Location);
        set('partnerDetailScore', partner.matchScore || '--');

        // There is no image asset in the repo, so the placeholder <img> would
        // render as a broken icon. Show it only if it genuinely decoded --
        // checking `complete` matters because a cached image fires `load`
        // before this ever runs.
        const img = document.getElementById('partnerDetailImage');
        if (img) {
            const well = img.closest('.partner-image');
            const apply = (loaded) => {
                img.style.display = loaded ? '' : 'none';
                // Collapse the fixed-height image well too, or hiding the img
                // just leaves a blank 250px band.
                if (well) well.classList.toggle('no-image', !loaded);
            };
            apply(img.complete && img.naturalWidth > 0);
            if (!img.complete) {
                img.addEventListener('load', () => apply(true), { once: true });
            }
        }

        openModal(detailModal);
    }

    partnersGrid.addEventListener('click', (e) => {
        const card = e.target.closest('.partner-card');
        if (!card) return;
        const partner = displayedPartners[Number(card.dataset.index)];
        if (partner) showPartnerDetail(partner);
    });

    partnersGrid.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('.partner-card');
        if (!card) return;
        e.preventDefault();
        const partner = displayedPartners[Number(card.dataset.index)];
        if (partner) showPartnerDetail(partner);
    });

    // --- Filters ------------------------------------------------------------
    function updateFilterButtonState() {
        if (!filterBtn) return;
        const count = Object.values(activeFilters).filter(Boolean).length;
        filterBtn.innerHTML = count
            ? `<i class='bx bx-filter-alt'></i> Filters (${count})`
            : `<i class='bx bx-filter-alt'></i> Filters`;
        filterBtn.classList.toggle('has-filters', count > 0);
    }

    if (filterForm) {
        filterForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            activeFilters = {
                OrganizationType: document.getElementById('typeInput').value.trim(),
                Location: document.getElementById('locationInput').value.trim(),
                Resources: document.getElementById('resourcesInput').value.trim()
            };
            updateFilterButtonState();
            closeModal(filterModal);
            await fetchPartners();
        });
    }

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', async () => {
            filterForm.reset();
            activeFilters = {};
            updateFilterButtonState();
            closeModal(filterModal);
            await fetchPartners();
        });
    }

    // --- Add partner --------------------------------------------------------
    // The form has no message element in the markup, so one is created on
    // first use and reused after that.
    function setFormMessage(form, text, kind = 'error') {
        if (!form) return;
        let box = form.querySelector('.form-message');
        if (!box) {
            box = document.createElement('p');
            box.className = 'form-message';
            form.prepend(box);
        }
        box.textContent = text;
        box.classList.toggle('success', kind === 'success');
        box.classList.toggle('hidden', !text);
    }

    if (addPartnerForm) {
        addPartnerForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const submitBtn = addPartnerForm.querySelector('button[type="submit"]');
            const payload = {
                name: document.getElementById('addName').value.trim(),
                organization_type: document.getElementById('addType').value.trim(),
                expertise: document.getElementById('addExpertise').value.trim(),
                resources: document.getElementById('addResources').value.trim(),
                email: document.getElementById('addEmail').value.trim(),
                phone_number: document.getElementById('addPhone').value.trim(),
                location: document.getElementById('addLocation').value.trim(),
                bio: document.getElementById('addBio').value.trim()
            };

            setFormMessage(addPartnerForm, '');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Adding...';
            }

            try {
                const res = await fetch(`${window.API_BASE}/api/partners/add`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (!res.ok) {
                    throw new Error(result.error || `Could not add partner (${res.status})`);
                }

                addPartnerForm.reset();
                closeModal(addPartnerModal);
                // Show the new record straight away rather than making the
                // user guess whether it saved.
                await fetchPartners();
            } catch (error) {
                console.error('Add partner failed:', error);
                setFormMessage(addPartnerForm, error.message);
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Add Partner';
                }
            }
        });
    }

    // --- Wiring -------------------------------------------------------------
    prevBtn.addEventListener('click', () => goToPage(currentPage - 1));
    nextBtn.addEventListener('click', () => goToPage(currentPage + 1));

    searchInput.addEventListener('input', applyView);

    updateFilterButtonState();
    fetchPartners();
});
