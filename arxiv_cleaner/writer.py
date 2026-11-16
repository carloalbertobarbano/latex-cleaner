"""Write the cleaned project to the output directory."""

from __future__ import annotations

import posixpath
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import lexer
from .scanner import Plan, read_text

# files whose comments are removed
CLEAN_EXTS = {".tex", ".tikz", ".ltx"}


@dataclass
class Options:
    flatten: bool = False
    keep_comments: bool = False
    keep_iffalse: bool = False
    remove_commands: tuple[str, ...] = ()
    drop_bib: bool = False


def flat_names(plan: Plan) -> dict[str, str]:
    """Map each kept file to a name in a single directory.

    Files keep their base name when it is unique (ignoring case). Otherwise
    the directory components are joined with ``_`` (``figs/a.pdf`` becomes
    ``figs_a.pdf``). A root document keeps its base name whenever possible,
    and companion files (``.bbl``, ...) follow their root.
    """
    files = sorted(f for f in plan.keep if f not in plan.companions)
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(posixpath.basename(f).lower(), []).append(f)

    mapping: dict[str, str] = {}
    used: set[str] = set()

    def claim(f: str, name: str) -> None:
        stem, ext = posixpath.splitext(name)
        cand, k = name, 1
        while cand.lower() in used:
            cand = f"{stem}_{k}{ext}"
            k += 1
        used.add(cand.lower())
        mapping[f] = cand

    # unique names and roots first, so they keep their base name
    order = sorted(files, key=lambda f: (f not in plan.roots, len(groups[posixpath.basename(f).lower()]) > 1,
                                         f.count("/"), f))
    for f in order:
        base = posixpath.basename(f)
        if base.lower() not in used:
            claim(f, base)
        else:
            claim(f, f.replace("/", "_"))
    for comp, root in plan.companions.items():
        stem = posixpath.splitext(mapping[root])[0]
        claim(comp, stem + posixpath.splitext(comp)[1])
    return mapping


def _render(ref_text: str, target: str, new: str, mode: str = "original") -> str:
    """New path text for a reference.

    ``mode`` is "always" (write the extension, so that the lookup cannot
    pick another file of the flattened directory), "never" (LaTeX adds the
    extension itself) or "original" (keep the extension only if the
    original text had one)."""
    ext = posixpath.splitext(target)[1]
    if not ext or mode == "always":
        return new
    if mode == "original" and ref_text.lower().endswith(ext.lower()):
        return new
    return posixpath.splitext(new)[0]


def build_outputs(plan: Plan, opts: Options) -> dict[str, str]:
    """Map source file -> output path (relative)."""
    keep = set(plan.keep)
    if opts.drop_bib:
        has_bbl = any(c.lower().endswith(".bbl") for c in plan.companions)
        if has_bbl:
            keep = {f for f in keep if not f.lower().endswith(".bib")}
    if opts.flatten:
        mapping = flat_names(plan)
        return {f: mapping[f] for f in keep}
    return {f: f for f in keep}


def transform(plan: Plan, rel: str, outputs: dict[str, str], opts: Options) -> str | None:
    """Return the new content of a text file, or None if it is copied as is."""
    ext = Path(rel).suffix.lower()
    needs_clean = ext in CLEAN_EXTS and (not opts.keep_comments or opts.remove_commands)
    replacements: list[tuple[int, int, str]] = []
    if opts.flatten:
        for r in plan.refs:
            if r.src != rel or not r.rewrite or r.target not in outputs:
                continue
            new = _render(r.text, r.target, outputs[r.target], r.ext)
            if new != r.text:
                replacements.append((r.start, r.end, new))
        for e in plan.edits:
            if e.src == rel:
                replacements.append((e.start, e.end, e.replacement))
        for mp in plan.macro_paths:
            if mp.src == rel:
                replacements.append((mp.start, mp.end, ""))
    if not replacements and not needs_clean:
        return None
    text = read_text(plan.root_dir / rel)
    # apply back to front; skip duplicates and overlaps
    replacements = sorted(set(replacements), key=lambda x: (x[0], -x[1]))
    out = []
    pos = len(text)
    for a, b, new in reversed(replacements):
        if b > pos:
            continue
        out.append(text[b:pos])
        out.append(new)
        pos = a
    out.append(text[:pos])
    text = "".join(reversed(out))
    if ext in CLEAN_EXTS:
        if opts.remove_commands:
            text = lexer.remove_commands(text, list(opts.remove_commands))
        if not opts.keep_comments:
            text = lexer.strip_comments(text, drop_iffalse=not opts.keep_iffalse)
    return text


def macro_path_conflicts(plan: Plan, outputs: dict[str, str]) -> list[str]:
    """Macro-built paths (``figs/#1``) lose their directory when flattening;
    this only works if the files of that directory keep their base name."""
    msgs = []
    for mp in plan.macro_paths:
        bad = [f for f in outputs
               if f.startswith(mp.directory + "/") and outputs[f] != posixpath.basename(f)]
        if bad:
            msgs.append(f"{mp.src}:{mp.line}: the directory '{mp.directory}/' was removed from a "
                        f"macro-built path, but these files were renamed: {', '.join(sorted(bad))}")
    return msgs


def write(plan: Plan, out_dir: Path, opts: Options) -> dict[str, str]:
    outputs = build_outputs(plan, opts)
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, new_rel in sorted(outputs.items()):
        dst = out_dir / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = transform(plan, rel, outputs, opts)
        if content is None:
            shutil.copy2(plan.root_dir / rel, dst)
        else:
            dst.write_bytes(content.encode("utf-8", errors="surrogateescape"))
            shutil.copystat(plan.root_dir / rel, dst)
    return outputs
