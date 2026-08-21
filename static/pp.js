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
            a: { initials: 'CB', name: 'Coders Over Borders', type: 'Non-profit', offer: 'Web Development' },
            b: { initials: 'RT', name: 'Riverside Tech', type: 'Small Business', offer: 'Student Internships' }
        },
        {
            score: 88,
            a: { initials: 'GE', name: 'Green Earth Initiative', type: 'NGO', offer: 'Volunteer Network' },
            b: { initials: 'LC', name: 'Lakeside Community Centre', type: 'Community Org', offer: 'Event Space' }
        },
        {
            score: 85,
            a: { initials: 'AP', name: 'APEERS', type: 'Non-profit', offer: 'Youth Audience' },
            b: { initials: 'SM', name: 'Studio Meridian', type: 'Design Studio', offer: 'Brand & Design Help' }
        }
    ];

    // --- The overlap matrix ------------------------------------------------
    //
    // Rows are categories one organization offers, columns are categories the
    // other needs; a filled cell is one both of them named. It is an
    // illustration rather than live data -- these three pairings are
    // fictional -- but it is drawn under the same rules the real thing
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
            // Alternating directions, so neither colour dominates and the
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
// Modals: the instructions guide and the contact form.
//
// Close handlers are scoped per-modal with modal.querySelector rather than a
// bare document.querySelector, so adding a second modal to the page cannot
// hand one modal the other's close button.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    // Focus is common.js's dialogOpened/dialogClosed: trapped inside while
    // open, returned to whatever opened it on close.
    function openModal(modal) {
        if (!modal) return;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(modal);
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
    }

    document.querySelectorAll('.modal').forEach((modal) => {
        const closeBtn = modal.querySelector('.close-modal');
        if (closeBtn) closeBtn.addEventListener('click', () => closeModal(modal));

        const confirmBtn = modal.querySelector('.btn-confirm');
        if (confirmBtn) confirmBtn.addEventListener('click', () => closeModal(modal));

        // Click on the backdrop, but not inside the dialog itself.
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal(modal);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('.modal.active').forEach((m) => closeModal(m));
    });

    // The guide modal has no trigger button on the page yet, hence the guard.
    const instructionsBtn = document.getElementById('instructions-btn');
    const instructionsModal = document.getElementById('instructions-modal');
    if (instructionsBtn && instructionsModal) {
        instructionsBtn.addEventListener('click', () => openModal(instructionsModal));
    }

    // --- Contact us ---------------------------------------------------------
    const contactModal = document.getElementById('contact-modal');
    const contactForm = document.getElementById('contactForm');
    const contactBtn = document.getElementById('contactBtn');

    if (contactBtn && contactModal) {
        contactBtn.addEventListener('click', () => {
            setFormMessage(contactForm, '');
            openModal(contactModal);
        });
    }

    // The form carries no message element in the markup, so one is created on
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

    if (contactForm) {
        contactForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const submitBtn = contactForm.querySelector('button[type="submit"]');
            const payload = {
                name: document.getElementById('contactName').value.trim(),
                email: document.getElementById('contactEmail').value.trim(),
                phone: document.getElementById('contactPhone').value.trim(),
                message: document.getElementById('contactMessage').value.trim(),
                website: document.getElementById('contactWebsite').value
            };

            setFormMessage(contactForm, '');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Sending...';
            }

            try {
                const res = await fetch(`${window.API_BASE}/api/contact`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (!res.ok) {
                    throw new Error(result.error || `Could not send message (${res.status})`);
                }

                contactForm.reset();
                setFormMessage(contactForm, 'Thanks — we got your message and will be in touch.', 'success');
            } catch (error) {
                console.error('Contact form failed:', error);
                setFormMessage(contactForm, error.message);
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Send message';
                }
            }
        });
    }
});

document.addEventListener('DOMContentLoaded', function() {
    // Animate numbers when scrolling
    const animateNumbers = () => {
        // Only elements that actually declare a target. The hero stats use
        // `.hero-stat` and are static text ("1,000+", "24h") -- selecting them
        // here is what previously overwrote them with NaN.
        const statItems = document.querySelectorAll('.stat-item[data-target]');

        statItems.forEach(item => {
            const target = parseInt(item.getAttribute('data-target'), 10);
            const numberEl = item.querySelector('.stat-number');
            if (!numberEl || Number.isNaN(target)) return;

            const suffix = item.getAttribute('data-suffix') || '';
            const duration = 2000; // Animation duration in ms
            const startTime = performance.now();

            const animate = (currentTime) => {
                const elapsedTime = currentTime - startTime;
                const progress = Math.min(elapsedTime / duration, 1);
                const value = Math.floor(progress * target);

                numberEl.textContent = value.toLocaleString() + suffix;

                if (progress < 1) {
                    requestAnimationFrame(animate);
                }
            };

            requestAnimationFrame(animate);
        });
    };
    
    // More precise Intersection Observer with higher threshold and rootMargin
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                entry.target.classList.remove('pending');
                
                // If this is the platform section, animate numbers
                if (entry.target.classList.contains('platform-section')) {
                    // Only animate numbers if not already animated
                    if (!entry.target.classList.contains('numbers-animated')) {
                        animateNumbers();
                        entry.target.classList.add('numbers-animated');
                    }
                }
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

    document.querySelectorAll('.scroll-section').forEach(section => {
        if (canAnimate) section.classList.add('pending');
        observer.observe(section);
    });
});
