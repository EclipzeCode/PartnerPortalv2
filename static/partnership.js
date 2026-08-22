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
                <h3>${esc(p.name)}${
                    p.deleted
                        ? '<span class="party-closed">account closed</span>'
                        : ''
                }</h3>
                <p class="party-meta">${esc(p.organization_type || '')}${
                    p.location ? ' · ' + esc(p.location) : ''
                }</p>
                <h4>Provides</h4>
                <ul class="party-gives">${gives}</ul>
            </section>
        `;
    }

    // What the badge and the date line say depends on where the partnership
    // got to. A page that still reads "Agreed partnership" a year after it
    // finished is telling whoever was sent the link something that is no
    // longer true -- and the record is more useful, not less, for saying so.
    const finished = {
        completed: {
            cls: 'complete',
            icon: 'bx-check-double',
            label: 'Completed partnership',
            line: (d) => `Both organizations confirmed this ran its course${
                d ? ' on ' + esc(d) : ''}.`,
        },
        ended: {
            cls: 'ended',
            icon: 'bx-stop-circle',
            label: 'Ended partnership',
            // Deliberately silent on who ended it and why. Those are one
            // organization's account, and this page is read by people with
            // no account, no stake and no way to hear the other side.
            line: (d) => `This partnership ended${d ? ' on ' + esc(d) : ''}.`,
        },
    }[partnership.status];

    const finishedOn = (partnership.completed_at || partnership.ended_at)
        ? new Date(partnership.completed_at || partnership.ended_at)
            .toLocaleDateString('en-US',
                { year: 'numeric', month: 'long', day: 'numeric' })
        : '';

    // When it runs, which is the question `timeline_label` ("3-6 months")
    // cannot answer for somebody reading this months later.
    const onDay = (iso) => {
        // Split rather than `new Date(iso)`: a bare date string is parsed as
        // UTC midnight and renders as the day before west of Greenwich.
        const [y, m, d] = String(iso || '').split('-').map(Number);
        if (!y || !m || !d) return '';
        return new Date(y, m - 1, d).toLocaleDateString('en-US', {
            day: 'numeric', month: 'long', year: 'numeric',
        });
    };
    const from = partnership.starts_on ? onDay(partnership.starts_on) : '';
    const until = partnership.ends_on ? onDay(partnership.ends_on) : '';
    const runs = (from && until) ? `Runs ${from} to ${until}`
        : from ? `Starts ${from}`
        : until ? `Runs until ${until}` : '';

    card.innerHTML = `
        <div class="agreement-badge${finished ? ' ' + finished.cls : ''}">
            <i class='bx ${finished ? finished.icon : 'bx-check-shield'}'></i>
            ${finished ? finished.label : 'Agreed partnership'}
        </div>
        <h1>${esc(partnership.parties[0].name)} &amp; ${esc(partnership.parties[1].name)}</h1>
        <p class="agreement-date">
            Confirmed by both organizations${agreed ? ' on ' + esc(agreed) : ''}${
                partnership.timeline_label
                    ? ' · ' + esc(partnership.timeline_label)
                    : ''
            }
        </p>
        ${runs
            ? `<p class="agreement-runs"><i class='bx bx-calendar'></i> ${esc(runs)}</p>`
            : ''}
        ${finished
            ? `<p class="agreement-outcome">${finished.line(finishedOn)}</p>`
            : ''}

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
