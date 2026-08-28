// The "Get in touch" modal, wherever it appears.
//
// It started on the home page as part of pp.js. The help page needed the same
// form, and its button pointed at index.html#contact -- which resolved to
// nothing, because the form is a modal and there is no #contact element to
// scroll to. Sending someone to another page to fill in a form they asked for
// on this one is not much better than sending them nowhere, so the form lives
// here instead and both pages open their own copy.
//
// One module rather than one per page: the markup, the field names and the
// endpoint all have to agree, and two copies of that agreement is one copy
// too many. A page opts in by including the modal markup and this script.
//
// Modals are wired per-page throughout this frontend (settings.js, invites.js,
// analytics.js all do their own) using common.js's dialogOpened/dialogClosed
// for focus. This follows that pattern rather than inventing a shared modal
// layer for one dialog.
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('contact-modal');
    const form = document.getElementById('contactForm');
    if (!modal) return;

    function open() {
        setMessage('');
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(modal);
    }

    function close() {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(modal);
    }

    // Every button that asks for this form, rather than one id: the home page
    // opens it from its CTA and the help page from the panel at the bottom,
    // and a third will want it eventually.
    document.querySelectorAll('[data-contact-open]').forEach((trigger) => {
        trigger.addEventListener('click', open);
    });

    // Scoped to this modal, so a page with a second dialog cannot hand this
    // one the other's close button.
    const closeBtn = modal.querySelector('.close-modal');
    if (closeBtn) closeBtn.addEventListener('click', close);

    modal.addEventListener('click', (event) => {
        // The backdrop, not the dialog sitting on it.
        if (event.target === modal) close();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && modal.classList.contains('active')) close();
    });

    // The form carries no message element in the markup, so one is created on
    // first use and reused after that.
    function setMessage(text, kind = 'error') {
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

    if (!form) return;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();

        const submitBtn = form.querySelector('button[type="submit"]');
        const payload = {
            name: document.getElementById('contactName').value.trim(),
            email: document.getElementById('contactEmail').value.trim(),
            phone: document.getElementById('contactPhone').value.trim(),
            message: document.getElementById('contactMessage').value.trim(),
            website: document.getElementById('contactWebsite').value,
        };

        setMessage('');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Sending...';
        }

        try {
            const res = await fetch(`${window.API_BASE}/api/contact`, {
                method: 'POST',
                headers: window.csrfHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) {
                throw new Error(result.error
                    || `Could not send message (${res.status})`);
            }

            form.reset();
            setMessage('Thanks — we got your message and will be in touch.',
                       'success');
        } catch (error) {
            console.error('Contact form failed:', error);
            setMessage(error.message);
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send message';
            }
        }
    });
});
