// ---------------------------------------------------------------------------
// Hero scene: scroll-driven bridge build + cursor parallax
//
// Two effects, two independent drivers:
//   1. Scroll assembles the bridge. --build (0..1) is written to the scene and
//      pp.css remaps it onto each part.
//   2. Each layer translates by an amount proportional to its depth, so near
//      ridges move further than distant ones as the cursor moves.
//
// The scroll build runs on touch as well -- scrolling is the one interaction
// every visitor has -- while the parallax needs a real pointer. Reduced motion
// skips both and leaves the scene finished.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const scene = document.getElementById('heroScene');
    const hero = document.querySelector('.hero');
    if (!scene || !hero) return;

    const layers = [...scene.querySelectorAll('.scene-layer')].map(el => ({
        el,
        depth: parseFloat(el.dataset.depth) || 0
    }));

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(pointer: fine)').matches;

    // --- Scroll build ----------------------------------------------------
    const BUILD_FRACTION = 0.6;  // of a viewport height to go from bare to built

    let buildQueued = false;
    let buildStart = 0;   // scrollY at which the build begins
    let buildSpan = 1;    // how much further scrolling completes it

    // The window the build runs over has to be derived from where the scene
    // actually sits, not from raw scroll depth. On a short viewport the hero
    // content pushes the scene below the fold, so a build keyed to scrollY
    // alone would finish before the bridge was ever on screen. Anchoring to
    // the scene's own document position keeps the animation in view in both
    // cases: it starts at 0 when the scene is already visible at rest (tall
    // viewports) and defers until the scene is entering when it is not.
    function measureBuildWindow() {
        const vh = window.innerHeight;
        const sceneDocTop = scene.getBoundingClientRect().top + window.scrollY;
        buildStart = Math.max(0, sceneDocTop - vh * 0.95);
        buildSpan = Math.max(1, vh * BUILD_FRACTION);
    }

    function applyBuild() {
        buildQueued = false;
        const build = Math.min(1, Math.max(0,
            (window.scrollY - buildStart) / buildSpan));
        scene.style.setProperty('--build', build.toFixed(4));
    }

    function onScroll() {
        if (buildQueued) return;
        buildQueued = true;
        requestAnimationFrame(applyBuild);
    }

    if (!reduceMotion) {
        window.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', () => {
            measureBuildWindow();
            onScroll();
        });
        measureBuildWindow();
        applyBuild();  // honour a restored scroll position on reload

        // The webfont lands after DOMContentLoaded and changes the hero's
        // height, which moves the scene and so the window measured above.
        window.addEventListener('load', () => {
            measureBuildWindow();
            onScroll();
        });
    }

    // Reduced motion keeps the CSS default of --build: 1 (fully assembled).
    // Touch keeps the scroll build above but stops here: there is no cursor to
    // parallax against.
    if (reduceMotion || !finePointer) return;

    const MAX_SHIFT_X = 46;   // px of travel for a depth of 1.0
    const MAX_SHIFT_Y = 22;

    let targetX = 0, targetY = 0;   // normalised cursor offset, -1..1
    let currentX = 0, currentY = 0; // smoothed values actually rendered
    let running = false;
    let inside = false;

    function render() {
        // Ease toward the target so the scene glides rather than snapping.
        currentX += (targetX - currentX) * 0.08;
        currentY += (targetY - currentY) * 0.08;

        layers.forEach(({ el, depth }) => {
            const dx = -currentX * depth * MAX_SHIFT_X;
            const dy = -currentY * depth * MAX_SHIFT_Y;
            el.style.transform = `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0)`;
        });

        const settled = Math.abs(targetX - currentX) < 0.001 && Math.abs(targetY - currentY) < 0.001;
        if (settled && !inside) {
            running = false;
            return;
        }
        requestAnimationFrame(render);
    }

    function start() {
        if (running) return;
        running = true;
        requestAnimationFrame(render);
    }

    hero.addEventListener('mousemove', (e) => {
        const r = hero.getBoundingClientRect();
        targetX = ((e.clientX - r.left) / r.width - 0.5) * 2;
        targetY = ((e.clientY - r.top) / r.height - 0.5) * 2;
        inside = true;
        start();
    });

    hero.addEventListener('mouseleave', () => {
        // Drift back to centre.
        inside = false;
        targetX = 0;
        targetY = 0;
        start();
    });

    // Paint the initial (centred) state.
    start();
});

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

    const el = {
        score: document.getElementById('matchScore'),
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

    paint(0);
    start();
});

// ---------------------------------------------------------------------------
// Modals: the instructions guide and the "Request a demo" contact form.
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

    // --- Request a demo -----------------------------------------------------
    const contactModal = document.getElementById('contact-modal');
    const contactForm = document.getElementById('contactForm');
    const requestDemoBtn = document.getElementById('requestDemoBtn');

    if (requestDemoBtn && contactModal) {
        requestDemoBtn.addEventListener('click', () => {
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
                message: document.getElementById('contactMessage').value.trim()
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
            if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
                entry.target.classList.add('active');
                
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
        threshold: 0.5, // Requires 50% of element to be visible
        rootMargin: '0px 0px -100px 0px' // 100px offset from bottom
    });
    
    // Observe all scroll sections
    document.querySelectorAll('.scroll-section').forEach(section => {
        observer.observe(section);
    });
    
    // Testimonial carousel functionality
    const testimonials = document.querySelectorAll('.testimonial');
    let currentTestimonial = 0;
    
    function showTestimonial(index) {
        testimonials.forEach((testimonial, i) => {
            testimonial.classList.toggle('active', i === index);
        });
    }
    
    // Auto-rotate testimonials only while the carousel is on screen.
    // A single interval is started and stopped as visibility changes -- the
    // previous version created a new one on every re-entry and leaked them.
    if (testimonials.length > 1) {
        let carouselInterval = null;

        const startRotation = () => {
            if (carouselInterval) return;
            carouselInterval = setInterval(() => {
                currentTestimonial = (currentTestimonial + 1) % testimonials.length;
                showTestimonial(currentTestimonial);
            }, 5000);
        };

        const stopRotation = () => {
            clearInterval(carouselInterval);
            carouselInterval = null;
        };

        const testimonialObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) startRotation();
                else stopRotation();
            });
        }, { threshold: 0.3 });

        document.querySelectorAll('.testimonial-carousel').forEach(carousel => {
            testimonialObserver.observe(carousel);
        });

        // Don't keep a timer running on a backgrounded tab.
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) stopRotation();
        });
    }
});