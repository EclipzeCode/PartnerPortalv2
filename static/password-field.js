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

document.addEventListener('DOMContentLoaded', () => wirePasswordToggles());
