# Drafts

Pages that are written but not published. Nothing here is served: Flask
serves `static/` and only `static/`, so a page stays a draft until it is
moved there.

## terms.html

A Terms of use page in the same voice and skeleton as `static/privacy.html`.
Everything in it that describes how the site works is true of the code as of
the draft date. Everything that depends on a fact about the operator rather
than on the software is marked `<mark class="legal-todo">[...]</mark>` and
has to be filled in before publishing:

- the legal entity, its registration and postal address
- a contact email
- the minimum age
- the notice periods for discontinuing the service and for changing the terms
- the liability cap, governing law and venue -- the "Law and liability"
  section is a plain-language placeholder and should be written or approved
  by a lawyer for the jurisdiction chosen
- the effective date

To publish: fill in and remove every `legal-todo`, remove the
`<meta name="robots" content="noindex, nofollow">` line, move the file to
`static/terms.html`, add `terms.html` to `_SITEMAP_PAGES` in `app.py`
beside `privacy.html`, add a Terms link after Privacy in each footer
(`grep -l 'privacy.html' static/*.html` lists the eleven pages), and
mention it in the README's page list.
