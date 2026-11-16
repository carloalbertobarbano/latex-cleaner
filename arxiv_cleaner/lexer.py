"""Minimal LaTeX lexer.

It finds the regions of a file that matter for cleaning and scanning:

* ``%`` comments (to the end of the line),
* ``comment`` environments and ``\\iffalse ... \\fi`` blocks,
* verbatim-like content (verbatim environments, ``\\verb``, ``\\url``),
* the position of ``\\end{document}``.

From these regions two views of the text are derived:

* :func:`mask` returns a text of the same length where everything that is
  not compiled (or is verbatim) is replaced by spaces, so that offsets
  found in the masked text are valid in the original text;
* :func:`strip_comments` returns the text without comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VERBATIM_ENVS = {
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "BVerbatim", "LVerbatim",
    "lstlisting", "minted", "filecontents", "filecontents*",
    "spverbatim", "comment",
}
# environments whose content is dropped from the output
DROP_ENVS = {"comment"}

# '@' is left out so that \verb@x%y@ is read as \verb with delimiter '@'
_letters = re.compile(r"[A-Za-z]+")
INLINE_VERB = {"verb", "Verb", "lstinline", "mintinline"}
_env_name = re.compile(r"\s*\{([^{}]*)\}")


@dataclass
class Regions:
    comments: list[tuple[int, int]] = field(default_factory=list)   # (pos of '%', eol)
    dropped: list[tuple[int, int]] = field(default_factory=list)    # comment envs, \iffalse blocks
    verbatim: list[tuple[int, int]] = field(default_factory=list)   # content kept as is
    end_document: int | None = None                                  # offset right after \end{document}


def _find_matching_brace(text: str, i: int) -> int:
    """``text[i]`` is ``{``. Return index of the matching ``}`` (or -1)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_NOT_CONDITIONALS = {"iff", "ifthenelse"}  # \iff is the math arrow


def _find_fi(text: str, i: int) -> int:
    """Find the ``\\fi`` closing an ``\\iffalse`` whose body starts at ``i``.

    Nested ``\\if...`` conditionals are counted. Returns the offset right
    after the closing ``\\fi``, or -1 if there is none or if the block has
    an ``\\else`` branch (whose content is compiled).
    """
    depth = 1
    for m in re.finditer(r"%[^\n]*|\\([A-Za-z@]+)|\\.", text[i:]):
        name = m.group(1)
        if not name:
            continue
        if name == "fi":
            depth -= 1
            if depth == 0:
                return i + m.end()
        elif name in ("else", "or") and depth == 1:
            return -1
        elif name.startswith("if") and name not in _NOT_CONDITIONALS:
            depth += 1
    return -1


def _alone_on_line(text: str, a: int, b: int, after_only: bool = False) -> bool:
    """True if only whitespace precedes ``a`` on its line (or, with
    ``after_only``, if only whitespace or a comment follows ``b``).

    ``\\iffalse`` is only treated as a commented-out block when used on its
    own line; inline uses such as ``{\\iffalse}\\fi`` are brace tricks.
    """
    if after_only:
        rest = text[b:text.find("\n", b) if text.find("\n", b) >= 0 else len(text)]
        return rest.strip() == "" or rest.lstrip().startswith("%")
    start = text.rfind("\n", 0, a) + 1
    return text[start:a].strip() == ""


def lex(text: str, drop_iffalse: bool = True) -> Regions:
    reg = Regions()
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == "%":
            j = text.find("\n", i)
            j = n if j < 0 else j
            reg.comments.append((i, j))
            i = j
            continue
        if c != "\\":
            i += 1
            continue
        # control sequence
        if i + 1 >= n:
            break
        m = _letters.match(text, i + 1)
        if not m:
            i += 2  # control symbol such as \% \\ \{
            continue
        name = m.group(0)
        j = m.end()
        if name in INLINE_VERB:
            k = j
            if k < n and text[k] == "*":
                k += 1
            if k < n and text[k] == "[" and name != "verb":
                e = _find_matching_bracket(text, k)
                k = e + 1 if e > 0 else k
            if name == "mintinline" and k < n and text[k] == "{":
                e = _find_matching_brace(text, k)
                k = e + 1 if e > 0 else k
            if k < n and not text[k].isspace() and not text[k].isalpha():
                delim = text[k]
                if delim == "{" and name != "verb":
                    e = _find_matching_brace(text, k)
                else:
                    e = text.find(delim, k + 1)
                nl = text.find("\n", k + 1)
                if e >= 0 and (nl < 0 or e < nl):
                    reg.verbatim.append((k + 1, e))
                    i = e + 1
                    continue
            i = j
            continue
        if name in ("url", "path", "href", "nolinkurl"):
            k = j
            while k < n and text[k] in " \t":
                k += 1
            if k < n and text[k] == "{":
                e = _find_matching_brace(text, k)
                if e > 0:
                    reg.verbatim.append((k + 1, e))
                    i = e + 1
                    continue
            i = j
            continue
        if name == "begin":
            em = _env_name.match(text, j)
            if em and em.group(1).strip() in VERBATIM_ENVS:
                env = em.group(1).strip()
                end_pat = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}")
                e = end_pat.search(text, em.end())
                if e:
                    if env in DROP_ENVS:
                        reg.dropped.append((i, e.end()))
                    else:
                        reg.verbatim.append((em.end(), e.start()))
                    i = e.end()
                    continue
            i = j
            continue
        if name == "end":
            em = _env_name.match(text, j)
            if em and em.group(1).strip() == "document" and reg.end_document is None:
                reg.end_document = em.end()
            i = j
            continue
        if name == "iffalse" and drop_iffalse and _alone_on_line(text, i, i):
            e = _find_fi(text, j)
            if e > 0 and _alone_on_line(text, e, e, after_only=True):
                reg.dropped.append((i, e))
                i = e
                continue
        i = j
    return reg


def mask(text: str, reg: Regions | None = None, cut_end_document: bool = True) -> str:
    """Same-length copy of ``text`` where non-compiled and verbatim parts are blanked.

    Newlines are preserved so that line numbers stay valid.
    """
    if reg is None:
        reg = lex(text)
    chars = list(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if chars[k] != "\n":
                chars[k] = " "

    for a, b in reg.comments + reg.dropped + reg.verbatim:
        blank(a, b)
    if cut_end_document and reg.end_document is not None:
        blank(reg.end_document, len(text))
    return "".join(chars)


_C = "\x00"  # placeholder for a removed % comment
_D = "\x01"  # placeholder for a removed block


def strip_comments(text: str, drop_after_end_document: bool = True,
                   drop_iffalse: bool = True) -> str:
    """Remove comments from LaTeX source.

    * A line containing only a comment is removed.
    * A trailing comment is removed but the ``%`` is kept, so that the
      end-of-line behaviour (no space inserted) is unchanged.
    * ``comment`` environments and ``\\iffalse ... \\fi`` blocks are removed.
    * Text after ``\\end{document}`` is removed.
    * Verbatim content is left untouched.
    """
    reg = lex(text, drop_iffalse=drop_iffalse)
    cuts: list[tuple[int, int, str]] = []
    for a, b in reg.comments:
        cuts.append((a, b, _C))
    for a, b in reg.dropped:
        cuts.append((a, b, _D))
    end = len(text)
    if drop_after_end_document and reg.end_document is not None:
        end = reg.end_document
    cuts.sort()
    out = []
    pos = 0
    for a, b, ph in cuts:
        if a >= end:
            break
        if a < pos:  # overlapping (should not happen)
            continue
        out.append(text[pos:a])
        out.append(ph)
        pos = min(b, end)
    out.append(text[pos:end])
    if end < len(text):
        out.append("\n")
    joined = "".join(out)

    lines = joined.split("\n")
    result = []
    for line in lines:
        if _C in line or _D in line:
            rest = line.replace(_C, "").replace(_D, "")
            if not rest.strip():
                continue  # line held only removed material
            line = line.replace(_D, "")
            line = line.replace(_C, "%")
        result.append(line)
    return "\n".join(result)


def remove_commands(text: str, names: list[str]) -> str:
    r"""Remove ``\name[opt]{arg}`` occurrences (e.g. ``\todo{...}``) with balanced braces."""
    if not names:
        return text
    reg = lex(text)
    masked = mask(text, reg)
    pat = re.compile(r"\\(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z@])")
    cuts = []
    for m in pat.finditer(masked):
        j = m.end()
        n = len(masked)
        if j < n and masked[j] == "*":
            j += 1
        while j < n and masked[j] in " \t":
            j += 1
        while j < n and masked[j] == "[":
            e = _find_matching_bracket(masked, j)
            if e < 0:
                break
            j = e + 1
        while j < n and masked[j] in " \t":
            j += 1
        if j < n and masked[j] == "{":
            e = _find_matching_brace(masked, j)
            if e > 0:
                cuts.append((m.start(), e + 1))
    out, pos = [], 0
    for a, b in cuts:
        if a < pos:
            continue
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    return "".join(out)


def _find_matching_bracket(text: str, i: int) -> int:
    depth = 0
    brace = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            brace += 1
        elif c == "}":
            brace -= 1
        elif brace == 0 and c == "[":
            depth += 1
        elif brace == 0 and c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1
