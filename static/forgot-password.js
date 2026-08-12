// Forgot-password request form.
//
// Loads common.js for the shared nav (someone can land here signed in, if
// they followed the link out of curiosity rather than being locked out), but
// the form submit itself goes through plain fetch rather than window.api --
// api() treats a 401 as "redirect to login", and /forgot-password never
// returns one, so nothing about that helper is needed here.

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('forgotForm');
    const emailInput = document.getElementById('email');
    const emailError = document.getElementById('email-error');
    const banner = document.getElementById('formBanner');
    const submitBtn = document.getElementById('submitBtn');
    const card = document.getElementById('resetCard');

    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    function setBanner(message, tone) {
        banner.textContent = message || '';
        banner.className = 'form-banner' + (tone ? ` ${tone}` : '');
        banner.hidden = !message;
    }

    function setFieldError(message) {
        emailError.textContent = message || '';
        emailInput.classList.toggle('input-error', Boolean(message));
    }

    emailInput.addEventListener('input', () => setFieldError(''));

    // Replaces the form with the same message whether or not the address
    // turned out to have an account -- the server's response does not say,
    // and the page should not either.
    function showSent(email) {
        card.innerHTML = `
            <div class="reset-icon info"><i class='bx bx-envelope'></i></div>
            <h1>Check your email</h1>
            <p class="reset-body">
                If an account exists for <strong>${escapeHtml(email)}</strong>,
                a password reset link is on its way. It expires in 1 hour.
            </p>
            <a class="btn-primary" href="pplogin.html">Back to sign in</a>
        `;
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        setBanner('');
        setFieldError('');

        const email = emailInput.value.trim();
        if (!email) {
            setFieldError('Enter your email.');
            emailInput.focus();
            return;
        }
        if (!EMAIL_RE.test(email)) {
            setFieldError('That does not look like a valid email address.');
            emailInput.focus();
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending...';

        try {
            const res = await fetch('/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ email }),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok) {
                // The only failures this endpoint returns are format and
                // rate-limit errors -- never "no such account" -- so a
                // banner is enough; nothing here is specific to the email
                // field.
                setBanner(data.error || 'Something went wrong. Please try again.', 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send reset link';
                return;
            }

            showSent(email);
        } catch {
            setBanner('Could not reach PartnerPortal. Check your connection and try again.', 'error');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Send reset link';
        }
    });
});
