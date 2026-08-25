// The public directory.
//
// Deliberately its own page rather than a signed-out mode inside ppsearch.js.
// That file is sixteen hundred lines built around a viewer: every card
// carries a match score, a save star and a propose button, and threading "no
// viewer" through all of it would put a branch on each of them for the
// benefit of the one visitor who has no account yet. It would also be the
// wrong page. Signed out, the useful things to say are what an organization
// does and that seeing fit is what an account is for -- not a column of
// dashes where the scores go.
//
// So this reads /api/directory, which answers without a session and carries
// no contact details, and renders what a stranger can act on.

document.addEventListener('DOMContentLoaded', async () => {
    const esc = window.escapeHtml;

    const grid = document.getElementById('dirGrid');
    const countLine = document.getElementById('dirCount');
    const pager = document.getElementById('dirPager');
    const pageIndicator = document.getElementById('dirPageIndicator');
    const prevBtn = document.getElementById('dirPrev');
    const nextBtn = document.getElementById('dirNext');
    const clearBtn = document.getElementById('dirClear');

    const controls = document.getElementById('dirControls');
    const searchInput = document.getElementById('dirSearch');
    const typeSelect = document.getElementById('dirType');
    const offersSelect = document.getElementById('dirOffers');
    const needsSelect = document.getElementById('dirNeeds');
    const sortSelect = document.getElementById('dirSort');
    const remoteBox = document.getElementById('dirRemote');

    // A form, so Enter submits -- and submitting must not navigate, since
    // every control here re-queries in place.
    controls.addEventListener('submit', (e) => e.preventDefault());

    const state = { page: 1, pages: 1, total: 0 };

    // Same guard the directory inside ppsearch.js uses. Typing is debounced,
    // which narrows the window without closing it: a select and a keystroke
    // are two triggers and can each have a request in the air, and the slower
    // answer would otherwise win and repaint the grid with results for a
    // query that is no longer on screen.
    let generation = 0;
    let searchTimer = null;

    // --- The query --------------------------------------------------------

    function currentFilters() {
        return {
            q: searchInput.value.trim(),
            type: typeSelect.value,
            offers: offersSelect.value,
            needs: needsSelect.value,
            sort: sortSelect.value,
            remote: remoteBox.checked ? '1' : '',
        };
    }

    function anyFilterSet() {
        const f = currentFilters();
        return Boolean(f.q || f.type || f.offers || f.needs || f.remote)
            || f.sort !== 'name';
    }

    function buildParams() {
        const params = new URLSearchParams({ page: String(state.page) });
        const filters = currentFilters();
        // Only what is actually set. An empty parameter is not the same as an
        // absent one to anyone reading the URL, and the endpoint would have
        // to treat "" as "any" for every field rather than simply not being
        // asked about it.
        Object.entries(filters).forEach(([key, value]) => {
            if (value) params.set(key, value);
        });
        return params;
    }

    // The search term rides in the address bar so a filtered directory can be
    // linked to and survives a reload. replaceState rather than pushState:
    // typing a query is not six entries in the back button.
    function syncUrl() {
        const params = buildParams();
        params.delete('page');
        // The default sort is what the page does anyway, so naming it in the
        // address bar only makes a shared link look like it carries a
        // decision somebody made.
        if (params.get('sort') === 'name') params.delete('sort');
        const query = params.toString();
        history.replaceState(
            null, '', query ? `?${query}` : location.pathname);
    }

    function readUrl() {
        const params = new URLSearchParams(location.search);
        searchInput.value = params.get('q') || '';
        typeSelect.value = params.get('type') || '';
        offersSelect.value = params.get('offers') || '';
        needsSelect.value = params.get('needs') || '';
        sortSelect.value = params.get('sort') === 'newest' ? 'newest' : 'name';
        remoteBox.checked = params.get('remote') === '1';
    }

    // --- Rendering --------------------------------------------------------

    function skeletons(count = 6) {
        grid.innerHTML = Array.from({ length: count }, () => `
            <div class="dir-card skeleton-card" aria-hidden="true">
                <div class="skeleton skeleton-line title"></div>
                <div class="skeleton skeleton-line short"></div>
                <div class="skeleton skeleton-line"></div>
                <div class="skeleton skeleton-line"></div>
            </div>
        `).join('');
    }

    // At most four, then "+n more". A card is a reason to open a profile,
    // not the profile.
    function chips(labels, kind) {
        const list = labels || [];
        if (!list.length) return '';
        const shown = list.slice(0, 4)
            .map((l) => `<span class="dir-chip ${kind}">${esc(l)}</span>`)
            .join('');
        const rest = list.length - 4;
        return shown + (rest > 0
            ? `<span class="dir-chip more">+${rest} more</span>` : '');
    }

    function card(org) {
        const meta = [org.organization_type, org.location]
            .filter(Boolean).map(esc).join(' &middot; ');

        return `
            <article class="dir-card">
                ${org.is_demo ? `
                    <p class="dir-demo">
                        <i class='bx bx-info-circle' aria-hidden="true"></i>
                        Example organization
                    </p>` : ''}
                <h2 class="dir-name">
                    <a href="organization.html?id=${encodeURIComponent(org.id)}">${esc(org.name)}</a>
                </h2>
                ${meta ? `<p class="dir-meta">${meta}</p>` : ''}
                ${org.remote_friendly ? `
                    <p class="dir-remote-tag">
                        <i class='bx bx-globe' aria-hidden="true"></i> Open to remote
                    </p>` : ''}
                ${org.description
                    ? `<p class="dir-bio">${esc(org.description)}</p>` : ''}
                <div class="dir-exchange">
                    <div class="dir-side">
                        <h3><i class='bx bx-up-arrow-alt' aria-hidden="true"></i> Offers</h3>
                        <div class="dir-chips">
                            ${chips(org.offers_labels, 'give')
                                || '<span class="dir-chip empty">Nothing listed</span>'}
                        </div>
                    </div>
                    <div class="dir-side">
                        <h3><i class='bx bx-down-arrow-alt' aria-hidden="true"></i> Needs</h3>
                        <div class="dir-chips">
                            ${chips(org.needs_labels, 'take')
                                || '<span class="dir-chip empty">Nothing listed</span>'}
                        </div>
                    </div>
                </div>
                <a class="dir-open"
                   href="organization.html?id=${encodeURIComponent(org.id)}">
                    See full profile <i class='bx bx-right-arrow-alt' aria-hidden="true"></i>
                </a>
            </article>`;
    }

    function emptyState() {
        const filtered = anyFilterSet();
        grid.innerHTML = `
            <div class="dir-empty">
                <i class='bx bx-search-alt' aria-hidden="true"></i>
                <p>${filtered
                    ? 'No organizations match those filters yet.'
                    : 'No organizations have finished a profile yet.'}</p>
                ${filtered
                    ? '<button type="button" class="btn-ghost" id="dirEmptyClear">'
                      + 'Clear filters</button>'
                    : '<a class="btn-primary" href="onboarding.html">'
                      + 'Be the first</a>'}
            </div>`;
        const btn = document.getElementById('dirEmptyClear');
        if (btn) btn.addEventListener('click', clearFilters);
    }

    function paintCount() {
        if (!state.total) {
            countLine.textContent = '';
            return;
        }
        const n = state.total;
        countLine.textContent = state.pages > 1
            ? `${n} organization${n === 1 ? '' : 's'} · page ${state.page} of ${state.pages}`
            : `${n} organization${n === 1 ? '' : 's'}`;
    }

    function paintPager() {
        pager.hidden = state.pages <= 1;
        prevBtn.disabled = state.page <= 1;
        nextBtn.disabled = state.page >= state.pages;
        pageIndicator.textContent = `${state.page} / ${state.pages}`;
    }

    // --- Loading ----------------------------------------------------------

    async function load({ scroll = false } = {}) {
        const mine = ++generation;
        grid.setAttribute('aria-busy', 'true');
        skeletons();
        clearBtn.hidden = !anyFilterSet();

        let data;
        try {
            data = await window.api(`/api/directory?${buildParams()}`);
        } catch (error) {
            if (mine !== generation) return;
            grid.removeAttribute('aria-busy');
            grid.innerHTML = `
                <div class="dir-empty">
                    <i class='bx bx-error-circle' aria-hidden="true"></i>
                    <p>${esc(error.message)}</p>
                </div>`;
            countLine.textContent = '';
            pager.hidden = true;
            return;
        }
        // A newer request is already on screen as skeletons and its answer is
        // the one that should land.
        if (mine !== generation) return;

        grid.removeAttribute('aria-busy');
        state.page = data.page;
        state.pages = data.pages;
        state.total = data.total;

        const rows = data.organizations || [];
        if (!rows.length) emptyState();
        else grid.innerHTML = rows.map(card).join('');

        paintCount();
        paintPager();

        if (scroll) {
            grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function reload() {
        state.page = 1;
        syncUrl();
        load();
    }

    function clearFilters() {
        searchInput.value = '';
        typeSelect.value = '';
        offersSelect.value = '';
        needsSelect.value = '';
        sortSelect.value = 'name';
        remoteBox.checked = false;
        reload();
    }

    // --- Wiring -----------------------------------------------------------

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimer);
        // Every keystroke is a request against the whole directory, so this
        // waits for a pause rather than racing the typing.
        searchTimer = setTimeout(reload, 300);
    });

    [typeSelect, offersSelect, needsSelect, sortSelect, remoteBox]
        .forEach((el) => el.addEventListener('change', reload));

    clearBtn.addEventListener('click', clearFilters);

    prevBtn.addEventListener('click', () => {
        if (state.page <= 1) return;
        state.page -= 1;
        load({ scroll: true });
    });
    nextBtn.addEventListener('click', () => {
        if (state.page >= state.pages) return;
        state.page += 1;
        load({ scroll: true });
    });

    // Back and forward should move through whatever was linked to, since the
    // filters live in the address bar.
    window.addEventListener('popstate', () => {
        readUrl();
        state.page = 1;
        load();
    });

    // --- Vocabulary -------------------------------------------------------
    // /api/categories is public and cached for an hour, so this costs a
    // conditional request at worst. Filled after the first load rather than
    // before it: the grid is what the visitor came for, and a select with no
    // options for a moment is a smaller problem than an empty page.

    async function fillVocabulary() {
        let data;
        try {
            data = await window.api('/api/categories');
        } catch {
            // The filters stay as they are -- "Any type", "Offers anything" --
            // which is a working directory with fewer ways to narrow it.
            return;
        }

        (data.organization_types || []).forEach((type) => {
            const option = document.createElement('option');
            option.value = type;
            option.textContent = type;
            typeSelect.appendChild(option);
        });

        // Grouped exactly as onboarding groups them, so a category sits where
        // somebody who filled the form in would look for it.
        [offersSelect, needsSelect].forEach((select) => {
            (data.groups || []).forEach((group) => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = group.name;
                (group.categories || []).forEach((cat) => {
                    const option = document.createElement('option');
                    option.value = cat.slug;
                    option.textContent = cat.label;
                    optgroup.appendChild(option);
                });
                select.appendChild(optgroup);
            });
        });

        // The URL may have named one before the options existed.
        readUrl();
    }

    // --- Signed in? -------------------------------------------------------
    // Not a redirect. Somebody signed in who followed a link here asked for
    // this page, and bouncing them off it would be answering a question they
    // did not ask -- but the scored version is strictly better for them, so
    // it is offered.

    async function noteSignedIn() {
        try {
            const data = await window.api(
                '/api/me', { allowUnauthenticated: true });
            if (data && data.organization) {
                // The nav link itself is routed by common.js, which does it
                // for every page; this only offers the better page in prose.
                document.getElementById('signedInNote').hidden = false;
            }
        } catch {
            // Signed out, which is who this page is for.
        }
    }

    readUrl();
    await load();
    fillVocabulary();
    noteSignedIn();
});
