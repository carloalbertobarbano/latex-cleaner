"""Command line interface."""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .scanner import Plan, find_roots, scan
from .writer import Options, build_outputs, macro_path_conflicts, write


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arxiv-cleaner",
        description="Copy a LaTeX project to a new directory keeping only the files "
                    "needed to compile it, with comments removed. The source "
                    "directory is never modified.")
    p.add_argument("source", type=Path, help="project directory")
    p.add_argument("-o", "--output", type=Path,
                   help="output directory (default: <source>_arxiv)")
    p.add_argument("-r", "--root", action="append", default=[], metavar="FILE",
                   help="root document to include (repeatable). Default: every .tex "
                        "file that contains \\begin{document}")
    p.add_argument("-f", "--flatten", action="store_true",
                   help="put all files in a single directory and rewrite the paths "
                        "in the sources accordingly")
    p.add_argument("--keep-comments", action="store_true",
                   help="do not remove comments")
    p.add_argument("--keep-iffalse", action="store_true",
                   help="do not remove \\iffalse ... \\fi blocks")
    p.add_argument("--remove-command", action="append", default=[], metavar="NAME",
                   help="remove every \\NAME{...} (e.g. todo); repeatable")
    p.add_argument("-k", "--keep", action="append", default=[], metavar="GLOB",
                   help="also keep files matching this pattern (relative to the "
                        "source directory, e.g. 'figures/*.pdf'); repeatable")
    p.add_argument("--drop-bib", action="store_true",
                   help="do not ship .bib files when the .bbl is available")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="only print what would be kept and removed")
    p.add_argument("--force", action="store_true",
                   help="overwrite the output directory if it exists")
    p.add_argument("--zip", action="store_true",
                   help="also create <output>.zip")
    p.add_argument("--check", action="store_true",
                   help="compile the output with latexmk (in a temporary copy) "
                        "to verify that nothing is missing")
    p.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex"], default="pdflatex",
                   help="engine used by --check (default: pdflatex)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="list every kept and removed file")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _all_files(root: Path) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or fn == ".DS_Store":
                continue
            files.append((Path(dirpath) / fn).relative_to(root).as_posix())
    return sorted(files)


def _resolve_root_arg(src: Path, r: str) -> str:
    cand = src / r
    if cand.is_file():
        return cand.resolve().relative_to(src).as_posix()
    cand = Path(r).resolve()
    if cand.is_file():
        try:
            return cand.relative_to(src).as_posix()
        except ValueError:
            pass
    if not r.endswith(".tex") and (src / (r + ".tex")).is_file():
        return (src / (r + ".tex")).resolve().relative_to(src).as_posix()
    raise SystemExit(f"error: root document '{r}' not found in {src}")


def _check_paths(src: Path, out: Path) -> None:
    if out == src:
        raise SystemExit("error: output directory is the source directory")
    if src in out.parents:
        raise SystemExit("error: output directory must not be inside the source directory")
    if out in src.parents:
        raise SystemExit("error: output directory must not contain the source directory")


ENGINE_FLAGS = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def _compile_check(out: Path, roots: list[str], outputs: dict[str, str],
                   engine: str = "pdflatex") -> bool:
    exe = shutil.which("latexmk")
    if not exe:
        print("check: latexmk not found, skipping", file=sys.stderr)
        return True
    ok = True
    with tempfile.TemporaryDirectory(prefix="arxiv-cleaner-") as tmp:
        work = Path(tmp) / "build"
        shutil.copytree(out, work)
        for root in roots:
            if root not in outputs:
                continue
            target = work / outputs[root]
            has_bbl = target.with_suffix(".bbl").exists()
            cmd = [exe, ENGINE_FLAGS[engine], "-interaction=nonstopmode", "-halt-on-error", "-cd"]
            if has_bbl:
                cmd.append("-bibtex-")  # arXiv does not run bibtex/biber
            cmd.append(str(target))
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            if res.returncode == 0:
                print(f"check: {outputs[root]} compiles")
            else:
                ok = False
                print(f"check: {outputs[root]} FAILED", file=sys.stderr)
                log = target.with_suffix(".log")
                lines = log.read_text(errors="replace").splitlines() if log.exists() else res.stdout.splitlines()
                errs = [i for i, l in enumerate(lines) if l.startswith("!")]
                start = errs[0] if errs else max(0, len(lines) - 20)
                for l in lines[start:start + 12]:
                    print(f"    {l}", file=sys.stderr)
    return ok


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    src = args.source.resolve()
    if not src.is_dir():
        raise SystemExit(f"error: {args.source} is not a directory")
    out = (args.output or src.with_name(src.name + "_arxiv")).resolve()
    _check_paths(src, out)

    if args.root:
        roots = [_resolve_root_arg(src, r) for r in args.root]
    else:
        roots = find_roots(src)
        if not roots:
            raise SystemExit("error: no .tex file with \\begin{document} found; use --root")
    print("root documents:")
    for r in roots:
        print(f"  {r}")

    plan: Plan = scan(src, roots)
    all_files = _all_files(src)
    for pattern in args.keep:
        matched = [f for f in all_files if fnmatch.fnmatch(f, pattern)]
        if not matched:
            plan.warn(f"--keep '{pattern}' matches no file")
        plan.keep.update(matched)

    opts = Options(flatten=args.flatten, keep_comments=args.keep_comments,
                   keep_iffalse=args.keep_iffalse,
                   remove_commands=tuple(args.remove_command), drop_bib=args.drop_bib)
    outputs = build_outputs(plan, opts)
    removed = [f for f in all_files if f not in outputs]

    print(f"\nkeeping {len(outputs)} files, removing {len(removed)} of {len(all_files)}")
    if args.verbose or args.dry_run:
        print("\nkept:")
        for f in sorted(outputs):
            arrow = f" -> {outputs[f]}" if outputs[f] != f else ""
            print(f"  {f}{arrow}")
        print("\nremoved:")
        for f in removed:
            print(f"  {f}")

    if args.flatten:
        for msg in macro_path_conflicts(plan, outputs):
            plan.warn(msg)
    if args.flatten and plan.unresolved_flatten:
        plan.warn("path-like arguments that could not be resolved and were left unchanged "
                  "(they may be built by macros; check the flattened output):\n    "
                  + "\n    ".join(plan.unresolved_flatten))
    if plan.warnings:
        sys.stdout.flush()
        print("\nwarnings:", file=sys.stderr)
        for w in plan.warnings:
            print(f"  - {w}", file=sys.stderr)

    if args.dry_run:
        return 0

    if out.exists():
        if any(out.iterdir()):
            if not args.force:
                raise SystemExit(f"error: {out} exists and is not empty (use --force to overwrite)")
            shutil.rmtree(out)
    write(plan, out, opts)
    print(f"\nwritten to {out}")

    if args.zip:
        archive = shutil.make_archive(str(out), "zip", root_dir=out)
        print(f"archive: {archive}")

    if args.check:
        if not _compile_check(out, plan.roots, outputs, args.engine):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
