// ---------------------------------------------------------------------------
// The home page.
//
// The scroll-driven bridge build and the cursor parallax that used to open
// this file are gone with the illustration they animated. The hero's visual
// is now the match matrix below, which is drawn from the same data that
// drives the rest of the demo rather than being decoration laid behind it.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Hero match demo
// Cycles through example pairings to show, rather than describe, the two-way
// match the product is built around.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const demo = document.getElementById('matchDemo');
    const dotsWrap = document.getElementById('matchDots');
    if (!demo || !dotsWrap) return;

    const EXAMPLES = [
        {
            score: 92,
            a: { initials: 'CN', name: 'A coding nonprofit', type: 'Non-profit', offer: 'Web Development' },
            b: { initials: 'TF', name: 'A local tech firm', type: 'Small Business', offer: 'Student Internships' }
        },
        {
            score: 88,
            a: { initials: 'EG', name: 'An environmental group', type: 'NGO', offer: 'Volunteer Network' },
            b: { initials: 'CC', name: 'A community center', type: 'Community Org', offer: 'Event Space' }
        },
        {
            score: 85,
            a: { initials: 'YP', name: 'A youth program', type: 'Non-profit', offer: 'Youth Audience' },
            b: { initials: 'DS', name: 'A design studio', type: 'Design Studio', offer: 'Brand & Design Help' }
        }
    ];

    // --- The overlap matrix ------------------------------------------------
    //
    // Rows are categories one organization offers, columns are categories the
    // other needs; a filled cell is one both of them named. It is an
    // illustration rather than live data -- these three pairings describe
    // kinds of organization, not real ones -- but it is drawn under the same rules the real thing
    // follows, which is the point of showing it at all.
    //
    // Two properties matter and both are easy to get wrong:
    //
    //   * It is deterministic. Seeded from the example's own score, so a
    //     pairing draws the same overlap every time it comes round. A grid
    //     that reshuffled on each pass would be telling the visitor, loudly,
    //     that the pattern stands for nothing.
    //
    //   * Its density tracks the score. A 92% match has visibly more lit
    //     cells than an 85% one. The number and the picture are claiming the
    //     same thing, so they cannot be allowed to disagree.
    const LATTICE_ROWS = 6;
    const lattice = document.getElementById('matchLattice');

    // The 14-column grid collapses to 7 on a narrow screen (see pp.css), so
    // the cell count has to follow or half the matrix hangs off the panel.
    const narrow = window.matchMedia('(max-width: 34rem)');

    function latticeCols() {
        return narrow.matches ? 7 : 14;
    }

    // mulberry32: small, fast, and adequate for choosing which squares to
    // fill in. Nothing here is a security decision.
    function seeded(seed) {
        let a = seed >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) >>> 0;
            let t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function drawLattice(ex) {
        if (!lattice) return;

        const cols = latticeCols();
        const total = cols * LATTICE_ROWS;
        const rand = seeded(ex.score);

        // A fifth to a third of the grid, scaled by the score. Beyond about a
        // third the lit cells stop reading as an overlap and start reading as
        // the background, which inverts the whole image.
        const lit = Math.round(total * (ex.score / 100) * 0.3);

        const chosen = new Map();
        let guard = 0;
        while (chosen.size < lit && guard++ < total * 8) {
            const i = Math.floor(rand() * total);
            if (chosen.has(i)) continue;
            // Alternating directions, so neither color dominates and the
            // grid reads as an exchange rather than as one side's inventory.
            chosen.set(i, chosen.size % 2 === 0 ? 'give' : 'take');
        }

        const frag = document.createDocumentFragment();
        for (let i = 0; i < total; i++) {
            const cell = document.createElement('div');
            cell.className = 'lattice-cell' + (chosen.has(i) ? ' ' + chosen.get(i) : '');
            // Stagger left-to-right so the matrix resolves across the panel
            // instead of every square appearing at once. Capped, or the last
            // column arrives after the example has already changed.
            cell.style.animationDelay = Math.min(i * 5, 420) + 'ms';
            frag.appendChild(cell);
        }

        lattice.replaceChildren(frag);
    }

    const el = {
        score: document.getElementById('matchScore'),
        dirA: document.getElementById('exchangeDirA'),
        dirB: document.getElementById('exchangeDirB'),
        avatarA: document.getElementById('orgAvatarA'),
        nameA: document.getElementById('orgNameA'),
        typeA: document.getElementById('orgTypeA'),
        offerA: document.getElementById('offerA'),
        avatarB: document.getElementById('orgAvatarB'),
        nameB: document.getElementById('orgNameB'),
        typeB: document.getElementById('orgTypeB'),
        offerB: document.getElementById('offerB')
    };

    // Everything that changes between examples fades together.
    Object.values(el).forEach(node => node && node.classList.add('swap'));

    const dots = [...dotsWrap.querySelectorAll('.match-dot')];
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let index = 0;
    let timer = null;

    function paint(i) {
        const ex = EXAMPLES[i];
        el.score.textContent = ex.score;
        el.avatarA.textContent = ex.a.initials;
        el.nameA.textContent = ex.a.name;
        el.typeA.textContent = ex.a.type;
        el.offerA.textContent = ex.a.offer;
        el.avatarB.textContent = ex.b.initials;
        el.nameB.textContent = ex.b.name;
        el.typeB.textContent = ex.b.type;
        el.offerB.textContent = ex.b.offer;
        // The chips name the direction with the same initials as the two
        // markers above and below the grid, so the exchange can be read
        // without a legend.
        if (el.dirA) el.dirA.textContent = ex.a.initials + ' \u2192 ' + ex.b.initials;
        if (el.dirB) el.dirB.textContent = ex.b.initials + ' \u2192 ' + ex.a.initials;
        drawLattice(ex);
        dots.forEach((d, di) => d.classList.toggle('active', di === i));
    }

    function show(i) {
        index = (i + EXAMPLES.length) % EXAMPLES.length;
        if (reduceMotion) {
            paint(index);
            return;
        }
        demo.classList.add('swapping');
        setTimeout(() => {
            paint(index);
            demo.classList.remove('swapping');
        }, 350);
    }

    function start() {
        if (timer || reduceMotion) return;
        timer = setInterval(() => show(index + 1), 4500);
    }

    function stop() {
        clearInterval(timer);
        timer = null;
    }

    // Once someone steers the demo themselves, the auto-advance is done for
    // good: having it resume would move the card on while they are reading the
    // pairing they just picked.
    let manual = false;

    function stepTo(i) {
        manual = true;
        stop();
        show(i);
    }

    dots.forEach(dot => {
        dot.addEventListener('click', () => stepTo(Number(dot.dataset.index)));
    });

    const prevBtn = document.getElementById('matchPrev');
    const nextBtn = document.getElementById('matchNext');
    if (prevBtn) prevBtn.addEventListener('click', () => stepTo(index - 1));
    if (nextBtn) nextBtn.addEventListener('click', () => stepTo(index + 1));

    // Pause while the visitor is reading it, or when the tab is hidden.
    demo.addEventListener('mouseenter', stop);
    demo.addEventListener('mouseleave', () => { if (!manual) start(); });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stop();
        else if (!manual) start();
    });

    // Crossing the breakpoint changes the column count, and a 14-column
    // matrix left in a 7-column grid is 84 squares in twelve rows running out
    // of the bottom of the panel.
    const onBreakpoint = () => drawLattice(EXAMPLES[index]);
    if (narrow.addEventListener) narrow.addEventListener('change', onBreakpoint);
    else narrow.addListener(onBreakpoint);   // Safari < 14

    paint(0);
    start();
});

// ---------------------------------------------------------------------------
// Scroll reveal for the sections below the hero. The contact dialog is
// contact.js, which owns it because the help page has one too; the "guide"
// modal that used to be wired here had no button that opened it and copy
// that named a nav item this site no longer has, so it is gone.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                entry.target.classList.remove('pending');
            }
        });
    }, {
        // Was 0.5, and the callback above tested for 0.5 a second time. These
        // sections are now tall enough on a laptop that half of one is never
        // on screen at once, so neither test could ever pass and the section
        // stayed at opacity 0 -- content on the page, and invisible. Lowering
        // the threshold alone would not have helped: the observer would fire
        // at a ratio of 0.1 and the guard would reject it. Both had to go.
        // A tenth of the section entering means it is being read.
        threshold: 0.1,
        rootMargin: '0px 0px -80px 0px'
    });
    
    // Hide, then observe -- in that order, and only here. pp.css leaves the
    // sections visible; .pending is what hides them, and it is added at the
    // same moment something exists that will take it off again. If this line
    // is never reached the page simply does not animate, which is the failure
    // worth having.
    //
    // The visibility check is the second half of that. A document that is
    // hidden when this runs -- a page opened in a background tab, a
    // prerender, an embedded frame that is not on screen -- gets no
    // intersection callbacks at all, because nothing can intersect a viewport
    // that is not being composited. Hiding the sections there would mean
    // hiding them for good: the callbacks do not arrive retroactively when
    // the tab is finally looked at. So a hidden document keeps the content on
    // screen and loses the animation, which is the right way round.
    const canAnimate = document.visibilityState === 'visible';

    document.querySelectorAll('.scroll-section, .stats-band').forEach(section => {
        if (canAnimate) section.classList.add('pending');
        observer.observe(section);
    });
});

// ---------------------------------------------------------------------------
// The headline, word by word
//
// The h1 carries an <em> around half of it, so this cannot be an innerHTML
// split on spaces -- that would flatten the emphasis the sentence is built
// on. It walks the text nodes instead and rewrites only those, which leaves
// every element in place and every word inside the element it belongs to.
//
// Each word becomes a clipped wrapper around a span, and the span is what
// moves; pp.css animates it out from under the clip. The words are numbered
// through a custom property so the stagger is one rule rather than one per
// word.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const title = document.querySelector('.hero-title');
    if (!title) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // Collected first: wrapping a text node replaces it, and a live walk
    // would then be standing on a node that is no longer in the tree.
    const walker = document.createTreeWalker(title, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) textNodes.push(n);

    let index = 0;
    textNodes.forEach((node) => {
        // Kept: the separators are the spaces between words, and dropping
        // them would run the sentence together once each word is a box.
        const parts = node.nodeValue.split(/(\s+)/).filter((p) => p !== '');
        if (parts.length === 0) return;

        const frag = document.createDocumentFragment();
        parts.forEach((part) => {
            if (/^\s+$/.test(part)) {
                frag.appendChild(document.createTextNode(part));
                return;
            }
            const outer = document.createElement('span');
            outer.className = 'rise-word';
            const inner = document.createElement('span');
            inner.style.setProperty('--word-index', String(index));
            inner.textContent = part;
            index += 1;
            outer.appendChild(inner);
            frag.appendChild(outer);
        });
        node.parentNode.replaceChild(frag, node);
    });
});

// ---------------------------------------------------------------------------
// Latest requests
// The three newest open requests from the board, under the figures. Hidden
// unless there are at least three: a strip with one card in it advertises an
// empty board.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    const section = document.getElementById('latestRequests');
    const grid = document.getElementById('latestGrid');
    if (!section || !grid) return;
    const esc = window.escapeHtml;
    try {
        const res = await fetch('/api/requests?sort=newest', { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        if (data.requests.length < 3) return;
        grid.innerHTML = data.requests.slice(0, 3).map((r) => `
            <a class="latest-card" href="/requests?id=${encodeURIComponent(r.id)}">
                <span class="latest-kind ${esc(r.kind)}">${r.kind === 'need' ? 'Needs' : 'Offering'}</span>
                <span class="latest-title">${esc(r.title)}</span>
                <span class="latest-meta">${esc(r.organization ? r.organization.name : '')}
                    &middot; ${esc(r.category_label)}</span>
            </a>`).join('');
        section.hidden = false;
    } catch (error) {
        // The strip is extra; the page is complete without it.
    }
});
