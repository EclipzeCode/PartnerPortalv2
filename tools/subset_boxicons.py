"""Cut boxicons down to the glyphs this site actually uses.

Upstream ships about 1,634 icons in a 113 KB font and a 68 KB stylesheet.
This site uses under eighty of them, so almost all of both was being sent to
every visitor on every cold cache.

Run after adding an icon to a page:

    venv/bin/python tools/subset_boxicons.py

It reads the full upstream files from tools/vendor/, works out which classes
appear anywhere in static/, and writes the trimmed font and stylesheet. The
upstream copies stay in tools/vendor/ precisely so this can be re-run: a
subset cannot be subsetted again to add an icon back.

Not part of the request path and not a build step -- nothing here runs on
deploy. It is a thing you run when the answer changes, and the answer only
changes when somebody adds an icon. If you forget, the icon renders as a
blank box, which is the failure this script's own check exists to catch: it
refuses to write anything if a class used in static/ has no glyph upstream.
That check is what found bx-handshake, which boxicons has never defined and
which had been rendering as an empty square on the propose button.
"""

import pathlib
import re
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
STATIC = ROOT / "static"
VENDOR = HERE / "vendor"

# Classes that carry no glyph. boxicons ships a few animation helpers
# alongside the icons, and they are styled here like any other class.
UTILITIES = {"bx-spin", "bx-spin-hover", "bx-burst", "bx-burst-hover",
             "bx-tada", "bx-tada-hover", "bx-flashing", "bx-flashing-hover",
             "bx-fade-left", "bx-fade-right", "bx-fade-up", "bx-fade-down"}

CLASS_RE = re.compile(r"\b(bx[sl]?-[a-z0-9-]+)\b")
RULE_RE = re.compile(r"\.(bx[sl]?-[a-z0-9-]+):before\{content:\"\\([0-9a-f]+)\"\}")

# Comments are stripped before the search, because a comment that names an
# icon is not a use of it. This file's own history is the argument: the note
# in ppsearch.html explaining why the propose button no longer asks for
# bx-handshake mentions bx-handshake, and the check below then refused to run
# over a name nothing renders.
#
# Only the two unambiguous forms, and stripping is the direction that costs
# nothing when it is wrong: a comment missed here keeps an icon in the font
# that nothing draws, which is a slightly larger file. Removing a real use
# would be the expensive mistake, and neither pattern can match code.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _without_comments(text, suffix):
    if suffix == ".html":
        return HTML_COMMENT_RE.sub(" ", text)
    return BLOCK_COMMENT_RE.sub(" ", text)


def used_classes():
    """Every boxicons class named anywhere in the frontend.

    A plain text search is enough because every icon in this codebase is a
    literal: they are passed around as values (`icon: 'bx-envelope'`) but
    never assembled from pieces, so there is no `'bx-' + name` for a search
    to miss. If that ever changes, this script is what will be wrong, and it
    will be wrong silently -- so keep them literal.
    """
    found = set()
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in {".html", ".js", ".css"}:
            continue
        if path.name == "boxicons.css":
            continue          # the definitions, not a use
        text = _without_comments(path.read_text(encoding="utf-8"), path.suffix)
        found |= set(CLASS_RE.findall(text))
    return found


def main():
    src_css = (VENDOR / "boxicons.css").read_text(encoding="utf-8")
    defined = dict(RULE_RE.findall(src_css))

    used = used_classes()
    glyph_classes = {c for c in used if c not in UTILITIES}
    missing = sorted(c for c in glyph_classes if c not in defined)
    if missing:
        print("These classes are used in static/ but boxicons defines no "
              "glyph for them:", file=sys.stderr)
        for name in missing:
            print(f"  {name}", file=sys.stderr)
        print("\nNothing written. Either the name is a typo, or the icon "
              "does not exist and the markup needs a different one.",
              file=sys.stderr)
        return 1

    keep = {c: defined[c] for c in sorted(glyph_classes)}
    codepoints = sorted({int(cp, 16) for cp in keep.values()})

    # --- The font ---------------------------------------------------------
    font = TTFont(VENDOR / "boxicons.woff2")
    options = subset.Options()
    options.flavor = "woff2"
    # Layout tables buy nothing for an icon font: there is no shaping, no
    # kerning and no ligature between two picture glyphs.
    options.layout_features = []
    options.name_IDs = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)
    out_font = STATIC / "fonts" / "boxicons.woff2"
    font.flavor = "woff2"
    font.save(out_font)

    # --- The stylesheet ---------------------------------------------------
    # Everything before the first icon rule is the @font-face and the base
    # .bx class, which every icon needs. The utilities are kept whole: they
    # are keyframes and animation rules, not content declarations.
    head_end = src_css.index(RULE_RE.search(src_css).group(0))
    preamble = src_css[:head_end]

    # Point @font-face at the one file that is actually shipped, and at the
    # path it is served from. Upstream lists eot, ttf, svg and woff beside the
    # woff2 and reaches them as ../fonts/, which is right for its own package
    # layout and wrong for this one. Every browser needing a format other than
    # woff2 predates the custom properties this design system is built on, so
    # the alternatives would be four files nothing here can use.
    #
    # Done in the script rather than by hand afterward: this file is
    # regenerated from tools/vendor/ every time an icon is added, so a manual
    # edit is one that quietly disappears the next time somebody runs it.
    # It disappeared exactly once before this comment was written.
    # Every src declaration goes, then one is put back. There are two
    # upstream -- a bare eot for IE, then the real comma-separated list --
    # and replacing "the" src leaves whichever one the pattern did not match,
    # which is how this shipped once already: a first line naming the local
    # woff2 and a second still asking for ../fonts/boxicons.eot.
    preamble, removed = re.subn(r"src:url\([^)]*\)[^;}]*;?", "", preamble)
    if removed < 1 or "@font-face{" not in preamble:
        print("Could not find the @font-face src to rewrite -- upstream's "
              "shape has changed and this script needs a look.",
              file=sys.stderr)
        return 1
    preamble = preamble.replace(
        "@font-face{",
        "@font-face{src:url(fonts/boxicons.woff2) format('woff2');", 1)
    utilities = "".join(
        m.group(0) for m in re.finditer(
            r"\.bx-(?:spin|burst|tada|flashing|fade-[a-z]+)(?:-hover)?"
            r"(?::hover)?\{[^}]*\}", src_css))
    keyframes = "".join(
        m.group(0) for m in re.finditer(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}",
                                        src_css))
    rules = "".join(f'.{name}:before{{content:"\\{cp}"}}'
                    for name, cp in keep.items())

    header = f"""/* Boxicons 2.1.4, subsetted to the {len(keep)} icons this site uses.

 * Upstream is 1,634 icons in a 113 KB font and a 68 KB stylesheet, and this
 * site uses under eighty of them -- so almost all of both was being sent to
 * every visitor with a cold cache, to draw a bell and some chevrons.
 *
 * Generated by tools/subset_boxicons.py from the full copies in
 * tools/vendor/. Do not hand-edit: adding an icon to a page means adding the
 * class to the markup and re-running that script, which refuses to write
 * anything if a class in static/ has no glyph upstream.
 *
 * MIT licensed -- see fonts/boxicons-LICENSE.txt.
 */

"""
    (STATIC / "boxicons.css").write_text(
        header + preamble + rules + utilities + keyframes, encoding="utf-8")

    print(f"kept {len(keep)} icons ({len(codepoints)} codepoints)")
    print(f"  font       {out_font.stat().st_size / 1024:6.1f} KB  "
          f"(was {(VENDOR / 'boxicons.woff2').stat().st_size / 1024:.1f} KB)")
    print(f"  stylesheet {(STATIC / 'boxicons.css').stat().st_size / 1024:6.1f} KB  "
          f"(was {len(src_css) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
