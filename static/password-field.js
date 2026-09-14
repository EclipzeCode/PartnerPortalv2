// Password fields: a reveal toggle and a caps-lock warning.
//
// Its own file rather than part of common.js because the pages that most
// need it are the ones that deliberately do not load common.js. The reset
// and claim pages are reached from a link with no session guaranteed, and
// window.api's redirect-on-401 is the wrong default there -- see the header
// of reset-password.js. A password field should not have to choose between
// working logged out and having a reveal button.
//
// Self-initializing, and also exported as window.wirePasswordToggles for
// forms built after load (reset-password.js and claim.js both build theirs).

// --- Password fields ---------------------------------------------------
// A reveal toggle and a caps-lock warning on every password input, wired
// here for the same reason the counters above are: there are nine of these
// across four pages, and a rule that lives in one place cannot be forgotten
// on the tenth.
//
// The reveal is not a nicety. Signing up here means clearing ten characters
// with a lowercase letter, an uppercase letter, a digit and a symbol, and
// until now that had to be typed blind -- with the checklist below the field
// reporting failures against something the person cannot see. Caps Lock is
// the other half of the same problem: it is the single most common reason a
// password someone is certain about is rejected, and nothing said so.
//
// The input is wrapped rather than the surrounding markup being changed,
// because these fields sit inside three different layouts (.field in
// pplogin, .form-group in settings, and the block reset-password.js builds
// for itself) and the button has to sit against the input in all of them.
function wirePasswordToggles(root = document) {
    root.querySelectorAll('input[type="password"]').forEach((input) => {
        if (input.dataset.revealWired) return;
        input.dataset.revealWired = '1';

        const wrap = document.createElement('span');
        wrap.className = 'pw-field';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        const button = document.createElement('button');
        button.type = 'button';       // never submits the form it sits in
        button.className = 'pw-reveal';
        button.setAttribute('aria-label', 'Show password');
        button.setAttribute('aria-pressed', 'false');
        // tabindex -1: Tab should go from the password field to the submit
        // button, which is what someone typing a password is heading for.
        // The toggle is reachable by pointer, and by Shift+Tab from submit.
        button.tabIndex = -1;
        button.innerHTML = "<i class='bx bx-show' aria-hidden='true'></i>";
        wrap.appendChild(button);

        button.addEventListener('click', () => {
            const revealed = input.type === 'text';
            input.type = revealed ? 'password' : 'text';
            button.setAttribute('aria-pressed', String(!revealed));
            button.setAttribute(
                'aria-label', revealed ? 'Show password' : 'Hide password');
            const icon = button.firstElementChild;
            if (icon) icon.className = revealed ? 'bx bx-show' : 'bx bx-hide';
            // Focus goes back to the field with the caret at the end, rather
            // than being left on the button or dropping the caret to the
            // start -- either would interrupt someone mid-password.
            const end = input.value.length;
            input.focus();
            try {
                input.setSelectionRange(end, end);
            } catch {
                // Some browsers refuse setSelectionRange on a password
                // input. The focus still landed, which is the important half.
            }
        });

        // Caps Lock. Announced politely rather than assertively: it is a
        // hint about what is being typed, not an error, and it comes and
        // goes while the person is still typing.
        const warning = document.createElement('p');
        warning.className = 'pw-capslock';
        warning.setAttribute('role', 'status');
        warning.setAttribute('aria-live', 'polite');
        warning.hidden = true;
        warning.innerHTML = "<i class='bx bx-up-arrow-alt' aria-hidden='true'></i> Caps Lock is on";
        wrap.insertAdjacentElement('afterend', warning);

        const checkCaps = (e) => {
            // getModifierState is absent on a few synthetic events; an
            // unknown state is reported as off rather than guessed at.
            const on = typeof e.getModifierState === 'function'
                && e.getModifierState('CapsLock');
            warning.hidden = !on;
        };
        input.addEventListener('keydown', checkCaps);
        input.addEventListener('keyup', checkCaps);
        // Leaving the field takes the warning with it -- it describes typing
        // into this input, and would otherwise sit under a field nobody is
        // in any more.
        input.addEventListener('blur', () => { warning.hidden = true; });
    });
}

window.wirePasswordToggles = wirePasswordToggles;

// --- The rules, and the meter that shows them ------------------------------
//
// The same five checks app.py's password_problem() enforces, in the same
// order every checklist lists them, in one place. They used to be restated
// in pplogin.js, settings.js, claim.js and reset-password.js -- four copies
// of a regex and a scoring table that had to agree with each other and with
// the server, and could only drift. This file is already what those four
// pages share.
const PASSWORD_SPECIAL_RE = /[!@#$%^&*()_+\-=[\]{}|;:,.<>?/~`"'\\]/;
const PASSWORD_STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong'];

function passwordChecks(password) {
    return {
        length: password.length >= 10,
        lower: /[a-z]/.test(password),
        upper: /[A-Z]/.test(password),
        digit: /[0-9]/.test(password),
        special: PASSWORD_SPECIAL_RE.test(password),
    };
}

function passwordAcceptable(password) {
    return Object.values(passwordChecks(password)).every(Boolean);
}

// 1-4. All five rules met is Good; Strong needs fourteen characters on top.
function passwordStrength(password, checks = passwordChecks(password)) {
    const satisfied = Object.values(checks).filter(Boolean).length;
    if (satisfied <= 2) return 1;
    if (satisfied === 3) return 2;
    if (satisfied === 4) return 3;
    return password.length >= 14 ? 4 : 3;
}

// Keeps a meter and checklist in step with an input. The elements are the
// four ids every page's markup already uses; the colors for the four
// levels live in CSS, keyed off data-score. Returns the painter so a page
// can call it again after a reset.
function wirePasswordMeter(input, {
    meter = document.getElementById('pwMeter'),
    fill = document.getElementById('pwMeterFill'),
    label = document.getElementById('pwMeterLabel'),
    checklist = document.getElementById('pwChecklist'),
} = {}) {
    function paint() {
        const password = input.value;
        const hasValue = password.length > 0;
        if (meter) meter.hidden = !hasValue;
        if (checklist) checklist.hidden = !hasValue;
        if (!hasValue) return;

        const checks = passwordChecks(password);
        if (checklist) {
            checklist.querySelectorAll('li[data-rule]').forEach((item) => {
                const met = Boolean(checks[item.dataset.rule]);
                item.classList.toggle('met', met);
                const icon = item.querySelector('i');
                if (icon) icon.className = met ? 'bx bx-check-circle' : 'bx bx-circle';
            });
        }
        const score = passwordStrength(password, checks);
        if (meter) meter.dataset.score = String(score);
        if (fill) fill.style.width = `${(score / 4) * 100}%`;
        if (label) label.textContent = PASSWORD_STRENGTH_LABELS[score - 1];
    }
    input.addEventListener('input', paint);
    return paint;
}

window.passwordChecks = passwordChecks;
window.passwordAcceptable = passwordAcceptable;
window.passwordStrength = passwordStrength;
window.wirePasswordMeter = wirePasswordMeter;

document.addEventListener('DOMContentLoaded', () => wirePasswordToggles());
