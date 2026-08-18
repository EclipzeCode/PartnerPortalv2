// Public organization profile.
//
// Standalone on purpose, like partnership.js: this page must work for someone
// with no account and no session, so it does not load common.js (whose api()
// helper redirects to the login page on 401).
//
// The unauthenticated payload carries no contact details. If the visitor does
// happen to be signed in, the authenticated endpoint is tried as well and
// fills in the contact block and the match score -- otherwise arriving here
// from search would show a signed-in org *less* than the page they came from.

(async function () {
    const card = document.getElementById('orgCard');

    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const id = new URLSearchParams(location.search).get('id');
    if (!id || !/^\d+$/.test(id)) {
        card.innerHTML =
            '<p class="org-error">This link is missing an organization id. ' +
            'Ask whoever shared it to send the full URL.</p>';
        return;
    }

    let org;
    try {
        const res = await fetch(`/api/organizations/${encodeURIComponent(id)}/public`);
        if (!res.ok) throw new Error('not found');
        org = (await res.json()).organization;
    } catch {
        card.innerHTML =
            '<p class="org-error">This organization could not be found. ' +
            'The link may be incorrect, or the profile may not be finished yet.</p>';
        return;
    }

    // Signed-in extras. A 401 here is the normal case for a public visitor,
    // so it is swallowed rather than surfaced.
    let viewer = null;
    try {
        const res = await fetch(`/api/organizations/${encodeURIComponent(id)}`);
        if (res.ok) viewer = (await res.json()).organization;
    } catch {
        // Offline or blocked; the public payload is enough to render.
    }

    function list(items, emptyText) {
        if (!items || items.length === 0) {
            return `<li class="none">${esc(emptyText)}</li>`;
        }
        return items.map((i) => `<li>${esc(i)}</li>`).join('');
    }

    const meta = [org.organization_type, org.location]
        .filter(Boolean).map(esc).join(' &middot; ');

    const initials = (org.name || '?')
        .split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

    // Links come from whichever payload has them. A signed-in viewer always
    // gets them (public_dict); a signed-out visitor only when the org ticked
    // links_public, which is what puts them in the unauthenticated payload at
    // all. So there is no visibility decision to make here -- the server has
    // already made it by choosing what to send.
    //
    // Every URL was normalised by links.py to http(s) on a known host, which
    // is what makes it safe to put in an href.
    const LINKS = [
        { key: 'website_url', icon: 'bx-globe', label: 'Website' },
        { key: 'linkedin_url', icon: 'bxl-linkedin-square', label: 'LinkedIn' },
        { key: 'instagram_url', icon: 'bxl-instagram', label: 'Instagram' },
        { key: 'x_url', icon: 'bxl-twitter', label: 'X' },
    ];

    // links.py already guarantees http(s), so this is belt-and-braces: esc()
    // stops an injected value breaking out of the attribute, but it does not
    // stop `javascript:` *inside* an href, which runs on click. Anything that
    // ever writes these columns without going through links.py -- an import
    // script, a seed file -- would otherwise turn this render into live XSS.
    const safeHref = (url) => /^https?:\/\//i.test(String(url || '')) ? url : null;

    const linkSource = viewer || org;
    const linkChips = LINKS
        .map((l) => ({ ...l, href: safeHref(linkSource[l.key]) }))
        .filter((l) => l.href)
        .map((l) => `
            <a class="org-link" href="${esc(l.href)}"
               target="_blank" rel="noopener noreferrer nofollow">
                <i class='bx ${esc(l.icon)}'></i> ${esc(l.label)}
            </a>`).join('');

    const linksBlock = linkChips
        ? `<div class="org-links">${linkChips}</div>` : '';

    let contact;
    if (viewer) {
        // Signed in: contact details and links together.
        contact = `
            <section class="org-section org-contact">
                <h2>Contact</h2>
                ${viewer.contact_email
                    ? `<p><i class='bx bx-envelope'></i>
                         <a href="mailto:${esc(viewer.contact_email)}">${esc(viewer.contact_email)}</a></p>`
                    : ''}
                ${viewer.contact_phone
                    ? `<p><i class='bx bx-phone'></i> ${esc(viewer.contact_phone)}</p>`
                    : ''}
                ${linksBlock}
            </section>`;
    } else if (linkChips) {
        // Signed out, but this org published its links. They show; contact
        // details still do not, so the lock note stays alongside them.
        contact = `
            <section class="org-section org-contact">
                <h2>Links</h2>
                ${linksBlock}
                <p class="org-contact-locked-inline">
                    <i class='bx bx-lock-alt'></i>
                    Contact details are shown to signed-in organizations.
                    <a href="pplogin.html">Sign in</a> or
                    <a href="onboarding.html">create a profile</a> to get in touch.
                </p>
            </section>`;
    } else {
        contact = `
            <section class="org-section org-contact-locked">
                <p>
                    <i class='bx bx-lock-alt'></i>
                    Contact details are shown to signed-in organizations.
                    <a href="pplogin.html">Sign in</a> or
                    <a href="onboarding.html">create a profile</a> to get in touch.
                </p>
            </section>`;
    }

    const score = viewer && typeof viewer.match_score === 'number'
        ? `
            <div class="org-match">
                <span class="org-match-score">${esc(viewer.match_score)}</span>
                <span class="org-match-label">match with you${
                    viewer.match_detail && viewer.match_detail.mutual
                        ? ' &middot; two-way'
                        : ''
                }</span>
            </div>
          `
        : '';

    card.innerHTML = `
        ${org.is_demo
            ? `<div class="org-demo-banner">
                   <i class='bx bx-info-circle'></i>
                   Example organization &mdash; seeded to show how PartnerPortal
                   works. Not a real group, and not matchable.
               </div>`
            : ''}

        <header class="org-head">
            <div class="org-avatar" aria-hidden="true">${esc(initials)}</div>
            <div class="org-headings">
                <h1>${esc(org.name)}</h1>
                ${meta ? `<p class="org-meta">${meta}</p>` : ''}
                ${org.remote_friendly
                    ? `<span class="org-tag"><i class='bx bx-globe'></i> Open to remote partnerships</span>`
                    : ''}
            </div>
            ${score}
        </header>

        ${org.description
            ? `<p class="org-bio">${esc(org.description)}</p>`
            : ''}

        ${(org.focus_area_labels || []).length
            ? `<section class="org-focus">
                   <h2>What they work on</h2>
                   <div class="org-focus-chips">${
                       org.focus_area_labels
                           .map((l) => `<span>${esc(l)}</span>`).join('')
                   }</div>
               </section>`
            : ''}

        <div class="org-exchange">
            <section class="org-side">
                <h2><i class='bx bx-up-arrow-alt'></i> What they offer</h2>
                <ul>${list(org.offers_labels, 'Nothing listed yet')}</ul>
                ${org.offers_note
                    ? `<p class="org-note">${esc(org.offers_note)}</p>`
                    : ''}
            </section>
            <section class="org-side">
                <h2><i class='bx bx-down-arrow-alt'></i> What they need</h2>
                <ul>${list(org.needs_labels, 'Nothing listed yet')}</ul>
                ${org.needs_note
                    ? `<p class="org-note">${esc(org.needs_note)}</p>`
                    : ''}
            </section>
        </div>

        ${org.partnership_goals
            ? `<section class="org-section">
                   <h2>What they are looking for in a partner</h2>
                   <p>${esc(org.partnership_goals)}</p>
               </section>`
            : ''}

        ${contact}

        <div class="org-actions">
            <button type="button" class="btn-share" id="shareBtn">
                <i class='bx bx-link'></i> Copy link to this profile
            </button>
            <a class="btn-find" href="ppsearch.html">Find partners like this</a>
        </div>
    `;

    document.title = `${org.name} | PartnerPortal`;

    const shareBtn = document.getElementById('shareBtn');
    shareBtn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(location.href);
            shareBtn.innerHTML = "<i class='bx bx-check'></i> Link copied";
            setTimeout(() => {
                shareBtn.innerHTML = "<i class='bx bx-link'></i> Copy link to this profile";
            }, 1800);
        } catch {
            // Clipboard needs a secure context; show the URL so it can still
            // be copied by hand.
            window.prompt('Copy this link:', location.href);
        }
    });
})();
