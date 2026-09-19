// Lint for the browser scripts. Deliberately one rule.
//
// There is no build step here and no package.json, and this is not the start
// of one: CI runs it with `npx eslint` and nothing is installed locally. It
// exists because a `const` read six lines above its own declaration shipped
// in ppdashboard.js and took the dashboard down for six days -- a
// ReferenceError that is not a syntax error, so `node --check` passes it,
// and that nothing but loading the page would have caught. This rule catches
// exactly that, at commit time.
//
// `functions: false` because the scripts lean on hoisted function
// declarations throughout (a handler defined below the call that wires it),
// which is safe and is not what this is for.
module.exports = [
    {
        files: ["static/*.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script",
        },
        rules: {
            "no-use-before-define": ["error", {
                functions: false,
                classes: true,
                variables: false,
            }],
        },
    },
];
