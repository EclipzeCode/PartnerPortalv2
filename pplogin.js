// Toggle between Login and Register
const container = document.getElementById('container');
const registerBtn = document.querySelector('.toggle-right .hidden');
const loginBtn = document.querySelector('.toggle-left .hidden');

const showRegister = () => container.classList.add("active");
const showLogin = () => container.classList.remove("active");

// Desktop: the sliding panel buttons.
if (registerBtn) registerBtn.addEventListener('click', showRegister);
if (loginBtn) loginBtn.addEventListener('click', showLogin);

// Mobile: the panel is hidden, so these in-form links do the switching.
const toSignUp = document.getElementById('toSignUp');
const toSignIn = document.getElementById('toSignIn');
if (toSignUp) toSignUp.addEventListener('click', showRegister);
if (toSignIn) toSignIn.addEventListener('click', showLogin);

// Register form submission
document.querySelector('.sign-up form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('register-name');
    const emailInput = document.getElementById('register-email');
    const passwordInput = document.getElementById('register-password');

    const name = nameInput.value;
    const email = emailInput.value;
    const password = passwordInput.value;

    // Basic validation
    if (name === '') {
        nameInput.placeholder = 'Please fill in your name.';
        nameInput.value = ''; // Clear the current text
        nameInput.classList.add('error');
        return;
    } else {
        nameInput.classList.remove('error');
    }

    if (email === '') {
        emailInput.placeholder = 'Please fill in your email.';
        emailInput.value = ''; // Clear the current text
        emailInput.classList.add('error');
        return;
    } else {
        emailInput.classList.remove('error');
    }

    if (password === '') {
        passwordInput.placeholder = 'Please fill in your password.';
        passwordInput.value = ''; // Clear the current text
        passwordInput.classList.add('error');
        return;
    } else {
        passwordInput.classList.remove('error');
    }

    // API call to register user
    try {
        const response = await fetch(`${window.API_BASE}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password })
        });

        const result = await response.json();

        if (!response.ok) {
            // The server explains what actually went wrong (e.g. duplicate
            // email), so show that instead of a generic failure.
            throw new Error(result.error || `Registration failed (${response.status})`);
        }

        emailInput.placeholder = result.message;
        emailInput.value = ''; // Clear the current text
        emailInput.classList.remove('error');
        emailInput.classList.add('success');
    }
    catch (error) {
        emailInput.placeholder = error.message;
        emailInput.value = ''; // Clear the current text
        emailInput.classList.remove('success');
        emailInput.classList.add('error');
        console.error('Registration error:', error);
    }
});

// Login form submission
document.querySelector('.sign-in form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const emailInput = document.getElementById('login-email');
    const passwordInput = document.getElementById('login-password');

    const email = emailInput.value;
    const password = passwordInput.value;

    // Basic validation
    if (email === '') {
        emailInput.placeholder = 'Please fill in your email.';
        emailInput.value = ''; // Clear the current text
        emailInput.classList.add('error');
        return;
    } else {
        emailInput.classList.remove('error');
    }

    if (password === '') {
        passwordInput.placeholder = 'Please fill in your password.';
        passwordInput.value = ''; // Clear the current text
        passwordInput.classList.add('error');
        return;
    } else {
        passwordInput.classList.remove('error');
    }

    // API call to login user
    try {
        const response = await fetch(`${window.API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || result.error || 'Invalid credentials');
        }

        emailInput.placeholder = result.message;
        emailInput.value = ''; // Clear the current text
        emailInput.classList.remove('error');
        emailInput.classList.add('success');

        // Store the username in local storage. The server returns `name` on a
        // successful login, so this no longer stores `undefined`.
        localStorage.setItem('username', result.name);
        localStorage.setItem('userEmail', result.email);

        // Redirect to the search page after successful login
        window.location.href = 'ppsearch.html';

    } catch (error) {
        emailInput.placeholder = error.message;
        emailInput.value = ''; // Clear the current text
        emailInput.classList.remove('success');
        emailInput.classList.add('error');
        console.error('Login error:', error);
    }
});

// Optional: Add CSS to highlight error fields
const style = document.createElement('style');
style.innerHTML = `
    .error {
        border: 1px solid red;
    }
    .success {
        border: 1px solid green;
    }
`;
document.head.appendChild(style);
