// Shared behaviour loaded on every page.
// Must be included BEFORE the page-specific script.

// Base URL for API calls. Locally the Flask server runs on its own port; once
// deployed the API is served from the same origin, so the base is empty.
// Keeping this in one place means deploying never requires a find-and-replace.
//
// 127.0.0.1 rather than localhost on purpose: on macOS, "localhost" resolves to
// ::1 first, and AirPlay Receiver listens on port 5000 over IPv6. Calling
// localhost:5000 there hits AirPlay and returns 403 even with Flask running.
// Flask's dev server binds 127.0.0.1, so the IPv4 literal always reaches it.
window.API_BASE = ['localhost', '127.0.0.1'].includes(location.hostname)
    ? 'http://127.0.0.1:5000'
    : '';

document.addEventListener('DOMContentLoaded', () => {
    // Mobile navigation toggle. The `.navbar.active` styling already exists in
    // each stylesheet's max-width:768px block -- this supplies the click
    // handler that was never wired up.
    const menuIcon = document.getElementById('menu-icon');
    const navbar = document.querySelector('.navbar');

    if (!menuIcon || !navbar) return;

    menuIcon.addEventListener('click', () => {
        const isOpen = navbar.classList.toggle('active');
        menuIcon.classList.toggle('bx-menu', !isOpen);
        menuIcon.classList.toggle('bx-x', isOpen);
        menuIcon.setAttribute('aria-expanded', String(isOpen));
    });

    // Close the menu after following a link, otherwise it stays open over the
    // new page section on mobile.
    navbar.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', () => {
            navbar.classList.remove('active');
            menuIcon.classList.add('bx-menu');
            menuIcon.classList.remove('bx-x');
            menuIcon.setAttribute('aria-expanded', 'false');
        });
    });

    // Close when tapping outside the menu.
    document.addEventListener('click', (e) => {
        if (!navbar.contains(e.target) && !menuIcon.contains(e.target)) {
            navbar.classList.remove('active');
            menuIcon.classList.add('bx-menu');
            menuIcon.classList.remove('bx-x');
            menuIcon.setAttribute('aria-expanded', 'false');
        }
    });
});
