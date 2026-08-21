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
            b: { initials: 'LC', name: 'Lakeside Community Center', type: 'Community Org', offer: 'Event Space' }
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

    // The lede band rides the same observer. It is not a .scroll-section --
    // it holds one sentence, not a two-column block -- but it is under the
    // fold, so it should arrive the way everything under the fold arrives.
    document.querySelectorAll('.scroll-section, .hero-lede').forEach(section => {
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
// The hero's dot field
//
// body.home tiles a 24px dot lattice across the whole page as a CSS texture.
// Over the first screen the same lattice is drawn here instead, so it can
// answer the cursor: dots near the pointer lift away from it, grow, and warm
// towards the accent, and settle back when it leaves.
//
// It is painted on the same grid, measured from the same origin, so the drawn
// half and the tiled half meet without a seam at the fold. The hero is the
// first thing in the body and the header above it is position:fixed, so the
// canvas's top-left corner really is the document's -- which is what the CSS
// background-position resolves against too.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('heroField');
    const hero = canvas && canvas.closest('.hero');
    if (!canvas || !hero) return;

    // Nothing is drawn at all in that case: the canvas stays empty and
    // transparent, and the page's own texture shows through it unchanged.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    // Matches body.home's background-size, and the circle a radial-gradient
    // tile puts at its center.
    const STEP = 24;
    const HALF = STEP / 2;
    const BASE_RADIUS = 1;
    // How far the cursor is felt, and how hard. Both in CSS pixels.
    const REACH = 165;
    const PUSH = 9;

    let width = 0;
    let height = 0;
    let cols = 0;
    let rows = 0;
    let dpr = 1;

    // Where the pointer is, and where the field currently believes it is.
    // The gap between the two is the whole easing: the field chases, so a
    // fast flick draws a trail that catches up rather than teleporting.
    let pointerX = -9999;
    let pointerY = -9999;
    let fieldX = -9999;
    let fieldY = -9999;
    let strength = 0;      // 0 when the pointer is away, 1 when it is over
    let targetStrength = 0;

    let paper = '#F5F2EB';
    let dotColor = 'rgba(0,0,0,0.06)';
    let accent = '#1E3A6E';
    let accentRGB = [30, 58, 110];

    function readColors() {
        const style = getComputedStyle(document.body);
        paper = style.getPropertyValue('--h-paper').trim() || paper;
        dotColor = style.getPropertyValue('--h-dot').trim() || dotColor;
        accent = style.getPropertyValue('--h-give').trim() || accent;
        accentRGB = parseColor(accent) || accentRGB;
    }

    // --h-give is a hex literal in both palettes; this is deliberately not a
    // general CSS color parser, and falls back rather than guessing.
    function parseColor(value) {
        const hex = value.replace('#', '');
        if (hex.length === 6) {
            return [
                parseInt(hex.slice(0, 2), 16),
                parseInt(hex.slice(2, 4), 16),
                parseInt(hex.slice(4, 6), 16),
            ];
        }
        const m = value.match(/rgba?\(([^)]+)\)/);
        if (m) {
            const parts = m[1].split(',').map((p) => parseFloat(p));
            if (parts.length >= 3) return [parts[0], parts[1], parts[2]];
        }
        return null;
    }

    function resize() {
        const rect = hero.getBoundingClientRect();
        width = Math.ceil(rect.width);
        height = Math.ceil(rect.height);
        // Capped: a 3x display over a full-screen hero is a lot of pixels to
        // repaint every frame for a texture, and the difference above 2x is
        // not visible on a 2px dot.
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cols = Math.ceil(width / STEP);
        rows = Math.ceil(height / STEP);
        readColors();
        // Immediately, not on the next frame. Setting canvas.width resets the
        // bitmap, and an alpha:false canvas resets to opaque black -- so any
        // moment between here and the next paint is a black rectangle over
        // the hero. That gap is the whole first screen when the loop is
        // paused, which is exactly the case on a page opened in a background
        // tab: no frames arrive until it is looked at.
        draw(performance.now());
    }

    // Smoothstep. Linear falloff leaves a visible circular edge where the
    // reach ends; this one arrives at zero flat.
    function ease(t) {
        return t * t * (3 - 2 * t);
    }

    function draw(now) {
        ctx.fillStyle = paper;
        ctx.fillRect(0, 0, width, height);

        // The field eases towards the pointer rather than snapping to it.
        fieldX += (pointerX - fieldX) * 0.14;
        fieldY += (pointerY - fieldY) * 0.14;
        // Quick to light, slow to let go. Symmetrical easing made the field
        // feel like it was catching up with the cursor rather than answering
        // it, and made the fade an abrupt switching-off.
        strength += (targetStrength - strength) * (targetStrength > strength ? 0.16 : 0.05);

        const reach = REACH;
        const reachSq = reach * reach;
        // Only the block of dots the cursor can actually reach is considered
        // for the lit pass; the rest are one batched path.
        const minCol = Math.max(0, Math.floor((fieldX - reach - HALF) / STEP));
        const maxCol = Math.min(cols, Math.ceil((fieldX + reach - HALF) / STEP) + 1);
        const minRow = Math.max(0, Math.floor((fieldY - reach - HALF) / STEP));
        const maxRow = Math.min(rows, Math.ceil((fieldY + reach - HALF) / STEP) + 1);

        // A slow diagonal swell, so the field is not perfectly still when
        // nobody is touching it. Small enough to read as the paper breathing.
        const t = now / 1000;

        ctx.fillStyle = dotColor;
        ctx.beginPath();
        for (let row = 0; row < rows; row += 1) {
            const y = row * STEP + HALF;
            for (let col = 0; col < cols; col += 1) {
                if (strength > 0.01
                    && col >= minCol && col < maxCol
                    && row >= minRow && row < maxRow) {
                    const dx = col * STEP + HALF - fieldX;
                    const dy = y - fieldY;
                    if (dx * dx + dy * dy < reachSq) continue;   // drawn lit, below
                }
                const x = col * STEP + HALF;
                const breathe = 0.9 + 0.1 * Math.sin(t * 0.6 + (col + row) * 0.22);
                ctx.moveTo(x + BASE_RADIUS * breathe, y);
                ctx.arc(x, y, BASE_RADIUS * breathe, 0, Math.PI * 2);
            }
        }
        ctx.fill();

        // The lit neighborhood, one dot at a time -- each has its own offset,
        // size and alpha, so there is nothing to batch.
        if (strength > 0.01) {
            for (let row = minRow; row < maxRow; row += 1) {
                for (let col = minCol; col < maxCol; col += 1) {
                    const x = col * STEP + HALF;
                    const y = row * STEP + HALF;
                    const dx = x - fieldX;
                    const dy = y - fieldY;
                    const distSq = dx * dx + dy * dy;
                    if (distSq >= reachSq) continue;

                    const dist = Math.sqrt(distSq) || 0.0001;
                    const falloff = ease(1 - dist / reach) * strength;

                    // Pushed away from the cursor, so the lattice opens
                    // around it rather than lighting up in place.
                    const offset = falloff * PUSH;
                    const px = x + (dx / dist) * offset;
                    const py = y + (dy / dist) * offset;

                    const radius = BASE_RADIUS + falloff * 1.7;
                    const alpha = 0.1 + falloff * 0.75;
                    ctx.fillStyle =
                        `rgba(${accentRGB[0]}, ${accentRGB[1]}, ${accentRGB[2]}, ${alpha})`;
                    ctx.beginPath();
                    ctx.arc(px, py, radius, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }
    }

    // --- The loop ---------------------------------------------------------
    // Running only while the hero is on screen and the tab is being looked
    // at. A texture is not worth a frame of work behind a scrolled-past fold
    // or in a background tab.
    let frame = null;
    let visible = document.visibilityState === 'visible';
    let onScreen = true;

    function tick(now) {
        draw(now);
        frame = requestAnimationFrame(tick);
    }

    function play() {
        if (frame === null && visible && onScreen) frame = requestAnimationFrame(tick);
    }

    function pause() {
        if (frame !== null) {
            cancelAnimationFrame(frame);
            frame = null;
        }
    }

    hero.addEventListener('pointermove', (e) => {
        const rect = hero.getBoundingClientRect();
        pointerX = e.clientX - rect.left;
        pointerY = e.clientY - rect.top;
        // First contact: start the field where the cursor is rather than
        // easing it in from the corner it was parked in.
        if (targetStrength === 0) {
            fieldX = pointerX;
            fieldY = pointerY;
        }
        targetStrength = 1;
    });

    hero.addEventListener('pointerleave', () => { targetStrength = 0; });

    // A touch is a tap, not a hover: the field answers it and then lets go,
    // rather than leaving a bright patch where a finger last was.
    hero.addEventListener('pointerdown', (e) => {
        if (e.pointerType !== 'touch') return;
        const rect = hero.getBoundingClientRect();
        pointerX = fieldX = e.clientX - rect.left;
        pointerY = fieldY = e.clientY - rect.top;
        targetStrength = 1;
        setTimeout(() => { targetStrength = 0; }, 900);
    });

    document.addEventListener('visibilitychange', () => {
        visible = document.visibilityState === 'visible';
        if (visible) play(); else pause();
    });

    if ('IntersectionObserver' in window) {
        new IntersectionObserver((entries) => {
            onScreen = entries[0].isIntersecting;
            if (onScreen) play(); else pause();
        }, { threshold: 0 }).observe(hero);
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(resize, 120);
    });

    // resize() paints its own first frame, so the field is already the right
    // texture before the loop has run once -- including when the loop is not
    // going to run at all yet.
    resize();
    play();
});
