// Public partnership summary.
//
// Standalone on purpose: this page must work for someone with no account and
// no session, so it does not load common.js (whose api() helper redirects to
// the login page on 401). The share token in the URL is the only credential.

(async function () {
    const card = document.getElementById('agreementCard');

    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const token = new URLSearchParams(location.search).get('token');
    if (!token) {
        card.innerHTML =
            '<p class="agreement-error">This link is missing its token. ' +
            'Ask whoever shared it to send the full URL.</p>';
        return;
    }

    let partnership;
    try {
        const res = await fetch(`/api/partnerships/${encodeURIComponent(token)}`);
        if (!res.ok) throw new Error('not found');
        partnership = (await res.json()).partnership;
    } catch {
        card.innerHTML =
            '<p class="agreement-error">This partnership could not be found. ' +
            'The link may be incorrect, or the agreement may have been ' +
            'withdrawn.</p>';
        return;
    }

    const agreed = partnership.agreed_at
        ? new Date(partnership.agreed_at).toLocaleDateString('en-US',
            { year: 'numeric', month: 'long', day: 'numeric' })
        : '';

    function partyBlock(p) {
        const gives = (p.gives || []).map((g) => `<li>${esc(g)}</li>`).join('')
            || '<li class="none">Nothing listed</li>';
        return `
            <section class="party">
                <h3>${esc(p.name)}</h3>
                <p class="party-meta">${esc(p.organization_type || '')}${
                    p.location ? ' · ' + esc(p.location) : ''
                }</p>
                <h4>Provides</h4>
                <ul class="party-gives">${gives}</ul>
            </section>
        `;
    }

    card.innerHTML = `
        <div class="agreement-badge"><i class='bx bx-check-shield'></i> Agreed partnership</div>
        <h1>${esc(partnership.parties[0].name)} &amp; ${esc(partnership.parties[1].name)}</h1>
        <p class="agreement-date">
            Confirmed by both organizations${agreed ? ' on ' + esc(agreed) : ''}${
                partnership.timeline_label
                    ? ' · ' + esc(partnership.timeline_label)
                    : ''
            }
        </p>

        <div class="parties">
            ${partyBlock(partnership.parties[0])}
            <div class="exchange-arrow"><i class='bx bx-transfer'></i></div>
            ${partyBlock(partnership.parties[1])}
        </div>

        ${partnership.message
            ? `<blockquote class="agreement-message">${esc(partnership.message)}</blockquote>`
            : ''}

        <p class="agreement-note">
            Both organizations confirmed these terms through PartnerPortal.
            This summary is a record of what each side agreed to provide; it is
            not a legal contract.
        </p>
    `;

    document.title =
        `${partnership.parties[0].name} & ${partnership.parties[1].name} | Partnership`;
})();
