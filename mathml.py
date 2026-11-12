"""Build-time mathematics for schema-2 public text (Python standard library plus the pinned latex2mathml).

Source convention, used only in schema-2 fields that allow mathematics:

    \\( ... \\)     inline mathematics
    \\[ ... \\]     display mathematics

Any other text is plain: it is escaped, and it may not contain a math delimiter or a bare dollar sign.
Conversion to MathML is delegated to the pinned latex2mathml package. This module does not parse TeX. It checks
the delimiters, then checks the converter's output: it must be well-formed XML, use only MathML Core elements and
attributes, and contain no backslash (the converter passes unknown commands through as text). The original TeX is
kept in a TeX annotation. Schema-1 text never passes through this module.
"""
import html
import re
import xml.etree.ElementTree as ET

from latex2mathml import converter

PINNED_LATEX2MATHML = "3.80.0"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"

# MathML Core elements the converter can produce. The wrapper (semantics, annotation) is added after validation.
ALLOWED_TAGS = frozenset({
    "math", "mrow", "mi", "mn", "mo", "mtext", "mspace", "ms", "mfrac", "msqrt", "mroot",
    "msub", "msup", "msubsup", "munder", "mover", "munderover", "mtable", "mtr", "mtd",
    "mstyle", "mpadded", "mphantom",
})
# Token elements carry text only. A converter that nests markup inside them is refused.
TOKEN_TAGS = frozenset({"mi", "mn", "mo", "mtext", "ms", "mspace"})
# Attributes the converter emits for these elements. Anything else (href, style, class, mathcolor, id, on*) is refused.
ALLOWED_ATTRS = frozenset({
    "display", "stretchy", "fence", "form", "movablelimits", "accent", "largeop", "lspace", "rspace",
    "width", "columnalign", "minsize", "maxsize", "mathvariant", "rowspacing", "columnspacing", "linethickness",
})
# Constructs that latex2mathml converts silently into something other than what was written (a line break becomes
# a no-break space; an unknown environment is dropped) or that carry markup, colour or links. Refused in the source.
_REFUSED = [
    (re.compile(r"\\\\"), "a line break '\\\\' (use separate formulas)"),
    (re.compile(r"\\begin\{(?!cases\})"), "an environment other than cases"),
    (re.compile(r"\\operatorname\*"), "\\operatorname*"),
    (re.compile(r"\\(href|url|input|include|write|def|newcommand|renewcommand|providecommand|let|catcode)\b"),
     "a link, file or definition command"),
    (re.compile(r"\\(style|class|color|textcolor|colorbox|fbox|unicode)\b"), "a styling or markup command"),
]
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Unescaped % starts a TeX comment, which the converter silently drops (the rest of the formula vanishes).
_COMMENT = re.compile(r"(?<!\\)%")
_EMPTY_GROUP = re.compile(r"(?<!\\)\{\s*\}")
# Groups that hold only spacing are empty too (\frac{\,}{b}); so is an empty optional argument (\sqrt[]{x}).
_SPACING_GROUP = re.compile(r"(?<!\\)\{(?:\s|\\[,;:! ]|\\quad|\\qquad)*\}")
_EMPTY_OPTIONAL = re.compile(r"\[\s*\]")
# Two scripts in a row (x__y, x^^y) and a script with nothing in its base or argument (x^{_}, {^}).
_DOUBLE_SCRIPT = re.compile(r"(?<!\\)[_^]\s*[_^]")
_EMPTY_SCRIPT = re.compile(r"(?<!\\)(?:\{\s*[_^]|[_^]\s*\}|(?:^|[=+\-*/,(\[&])\s*[_^])")
# Number of arguments each construct needs. The converter emits a construct with too few arguments without complaint
# (\frac{a} becomes a fraction with one part), so the output is checked.
ARITY = {"mfrac": 2, "mroot": 2, "msub": 2, "msup": 2, "msubsup": 3, "mover": 2, "munder": 2, "munderover": 3}

_DELIM = re.compile(r"\\\(|\\\)|\\\[|\\\]|\$")
_CLOSE = {"\\(": "\\)", "\\[": "\\]"}


class MathError(ValueError):
    """Malformed or unsupported mathematics in a public record. The message names the record and field."""


def _tag(el):
    return el.tag.split("}", 1)[-1]


def _segments(text, where):
    """Split text into ('text', s) and ('math', src, display) pieces. Delimiters must balance and not nest."""
    out, pos, open_tok, start = [], 0, None, 0
    for m in _DELIM.finditer(text):
        tok = m.group()
        if tok == "$":
            raise MathError(f"{where}: bare '$'. Write mathematics as \\( ... \\) or \\[ ... \\]; write money in words.")
        if open_tok is None:
            if tok not in _CLOSE:
                raise MathError(f"{where}: '{tok}' has no matching opening delimiter")
            out.append(("text", text[pos:m.start()]))
            open_tok, start = tok, m.end()
        else:
            if tok != _CLOSE[open_tok]:
                raise MathError(f"{where}: '{tok}' inside a '{open_tok}' formula (delimiters cannot nest or mismatch)")
            src = text[start:m.start()]
            if not src.strip():
                raise MathError(f"{where}: empty formula")
            out.append(("math", src.strip(), open_tok == "\\["))
            open_tok, pos = None, m.end()
    if open_tok is not None:
        raise MathError(f"{where}: '{open_tok}' is never closed")
    out.append(("text", text[pos:]))
    return out


def _source_ok(src, where):
    """Refuse constructs the converter gets wrong silently, and unbalanced braces (it accepts 'x_{' and '\\frac{a}{b')."""
    for pattern, label in _REFUSED:
        if pattern.search(src):
            raise MathError(f"{where}: formula {src!r} uses {label}, which cannot be rendered faithfully")
    if _COMMENT.search(src):
        raise MathError(f"{where}: formula {src!r} has an unescaped % (a TeX comment); write \\% for a percent sign")
    if _EMPTY_GROUP.search(src) or _SPACING_GROUP.search(src):
        raise MathError(f"{where}: formula {src!r} has an empty group {{}}; leave out the empty argument")
    if _EMPTY_OPTIONAL.search(src):
        raise MathError(f"{where}: formula {src!r} has an empty optional argument []")
    if _DOUBLE_SCRIPT.search(src):
        raise MathError(f"{where}: formula {src!r} has two scripts in a row; group one with braces")
    if _EMPTY_SCRIPT.search(src):
        raise MathError(f"{where}: formula {src!r} has a script with nothing to attach to")
    depth = 0
    for i, ch in enumerate(src):
        if ch in "{}" and (i == 0 or src[i - 1] != "\\"):
            depth += 1 if ch == "{" else -1
            if depth < 0:
                break
    if depth != 0:
        raise MathError(f"{where}: formula {src!r} has unbalanced braces")


def _formula(src, display, where):
    """Convert one formula with the pinned converter and validate the result. Returns a MathML fragment."""
    _source_ok(src, where)
    try:
        out = converter.convert(src, display="block" if display else "inline")
    except Exception as exc:  # the converter raises on some malformed input
        raise MathError(f"{where}: cannot convert formula {src!r} ({type(exc).__name__})") from None
    try:
        root = ET.fromstring(out)
    except ET.ParseError:
        raise MathError(f"{where}: formula {src!r} is not well-formed after conversion; "
                        "inside \\text{} write 'and' rather than '&' or '<'") from None
    if _tag(root) != "math":
        raise MathError(f"{where}: formula {src!r} did not convert to a math element")
    for el in root.iter():
        name = _tag(el)
        if name not in ALLOWED_TAGS:
            raise MathError(f"{where}: formula {src!r} uses unsupported element <{name}>")
        if name in TOKEN_TAGS and len(el):
            raise MathError(f"{where}: formula {src!r} nests markup inside <{name}>")
        if name in ARITY and len(el) != ARITY[name]:
            raise MathError(f"{where}: formula {src!r} has an incomplete <{name}> ({len(el)} of {ARITY[name]} parts)")
        for attr in el.attrib:
            if attr not in ALLOWED_ATTRS:
                raise MathError(f"{where}: formula {src!r} uses unsupported attribute '{attr}' on <{name}>")
        for text in (el.text, el.tail):
            if text and "\\" in text:
                raise MathError(f"{where}: formula {src!r} contains an unknown command")
    inner = out[out.index(">") + 1: out.rindex("</math>")]
    kind = "block" if display else "inline"
    tex = html.escape(src, quote=False)
    return (f'<math display="{kind}"><semantics>{inner}'
            f'<annotation encoding="application/x-tex">{tex}</annotation></semantics></math>')


def render(text, where, *, math=True):
    """HTML for one text field. With math=False the field is plain: any delimiter or dollar sign is refused."""
    if not isinstance(text, str):
        raise MathError(f"{where}: expected text")
    if _CTRL.search(text):
        raise MathError(f"{where}: control character in text (check JSON escapes such as \\f or \\b)")
    if not math:
        if _DELIM.search(text):
            raise MathError(f"{where}: math delimiters are allowed only in mathematical fields")
        return html.escape(text)
    parts = []
    for seg in _segments(text, where):
        if seg[0] == "text":
            parts.append(html.escape(seg[1]))
        else:
            _, src, display = seg
            body = _formula(src, display, where)
            # A span, not a div: display formulas sit inside paragraphs, and div is not allowed there.
            parts.append(f'<span class="math-display" tabindex="0">{body}</span>' if display else body)
    return "".join(parts)


def plain(text):
    """Searchable plain text: the TeX source with delimiters removed."""
    return re.sub(r"\\[()\[\]]", " ", text)


def check(text, where, *, math=True):
    """Validate one field without keeping the output."""
    render(text, where, math=math)
