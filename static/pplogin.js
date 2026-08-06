// Login / registration.
//
// Auth is a signed session cookie set by the server. Nothing about the user is
// kept in localStorage any more -- the previous version stored a name string
// that any page could invent, which was not authentication in any real sense.

const container = document.getElementById('container');
const registerBtn = document.querySelector('.toggle-right .hidden');
const loginBtn = document.querySelector('.toggle-left .hidden');

const showRegister = () => container.classList.add('active');
const showLogin = () => container.classList.remove('active');

if (registerBtn) registerBtn.addEventListener('click', showRegister);
if (loginBtn) loginBtn.addEventListener('click', showLogin);

const toSignUp = document.getElementById('toSignUp');
const toSignIn = document.getElementById('toSignIn');
if (toSignUp) toSignUp.addEventListener('click', showRegister);
if (toSignIn) toSignIn.addEventListener('click', showLogin);

// Where to land after signing in. An org that has not finished onboarding is
// sent there first, because matches are meaningless without a profile.
function destinationFor(organization) {
    const params = new URLSearchParams(location.search);
    const next = params.get('next');
    if (!organization.onboarding_complete) return 'onboarding.html';
    if (next && /^[a-z0-9_-]+\.html$/i.test(next)) return next;
    return 'ppdashboard.html';
}

function setFieldState(input, message, ok) {
    input.value = '';
    input.placeholder = message;
    input.classList.toggle('error', !ok);
    input.classList.toggle('success', ok);
}

// --- Register ---------------------------------------------------------------
document.querySelector('.sign-up form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('register-name');
    const emailInput = document.getElementById('register-email');
    const passwordInput = document.getElementById('register-password');

    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    const password = passwordInput.value;

    if (!name) return setFieldState(nameInput, 'Please fill in your organization name.', false);
    if (!email) return setFieldState(emailInput, 'Please fill in your email.', false);
    if (!password) return setFieldState(passwordInput, 'Please fill in your password.', false);
    if (password.length < 8) {
        return setFieldState(passwordInput, 'Password must be at least 8 characters.', false);
    }

    nameInput.classList.remove('error');
    emailInput.classList.remove('error');
    passwordInput.classList.remove('error');

    try {
        const result = await window.api('/register', {
            method: 'POST',
            body: { name, email, password },
            allowUnauthenticated: true
        });
        // Registering signs you in, so go straight to building the profile.
        window.location.href = destinationFor(result.organization);
    } catch (error) {
        setFieldState(emailInput, error.message, false);
        console.error('Registration error:', error);
    }
});

// --- Login ------------------------------------------------------------------
document.querySelector('.sign-in form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const emailInput = document.getElementById('login-email');
    const passwordInput = document.getElementById('login-password');

    const email = emailInput.value.trim();
    const password = passwordInput.value;

    if (!email) return setFieldState(emailInput, 'Please fill in your email.', false);
    if (!password) return setFieldState(passwordInput, 'Please fill in your password.', false);

    emailInput.classList.remove('error');
    passwordInput.classList.remove('error');

    try {
        const result = await window.api('/login', {
            method: 'POST',
            body: { email, password },
            allowUnauthenticated: true
        });
        window.location.href = destinationFor(result.organization);
    } catch (error) {
        setFieldState(emailInput, error.message, false);
        console.error('Login error:', error);
    }
});

const style = document.createElement('style');
style.innerHTML = `
    .error { border: 1px solid red; }
    .success { border: 1px solid green; }
`;
document.head.appendChild(style);
