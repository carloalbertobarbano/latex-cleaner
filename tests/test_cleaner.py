import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture  # noqa: E402
from latex_cleaner import lexer  # noqa: E402
from latex_cleaner.cli import main  # noqa: E402
from latex_cleaner.scanner import find_roots, scan  # noqa: E402

HAVE_TEX = shutil.which("pdflatex") is not None and shutil.which("latexmk") is not None


def tree_hash(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def run_cli(*args) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main([str(a) for a in args])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            err.write(str(e.code))
    return code, out.getvalue(), err.getvalue()


class LexerTests(unittest.TestCase):
    def test_strip_comments(self):
        src = ("a % c\n"
               "% full line\n"
               "b \\% c\n"
               "\\\\% after a line break\n"
               "\\verb|x%y| \\url{a%20b}\n"
               "\\begin{verbatim}\n% keep\n\\end{verbatim}\n"
               "\\begin{comment}\nhidden\n\\end{comment}\n"
               "\\iffalse\nhidden \\ifx a b \\fi\n\\fi\n"
               "{\\iffalse}\\fi\n"
               "\\end{document}\ntrailing\n")
        out = lexer.strip_comments(src)
        self.assertEqual(out, ("a %\n"
                               "b \\% c\n"
                               "\\\\%\n"
                               "\\verb|x%y| \\url{a%20b}\n"
                               "\\begin{verbatim}\n% keep\n\\end{verbatim}\n"
                               "{\\iffalse}\\fi\n"
                               "\\end{document}\n"))

    def test_iffalse_with_else_is_kept(self):
        src = "\\iffalse\nold\n\\else\nnew \\input{x}\n\\fi\n"
        self.assertEqual(lexer.strip_comments(src), src)
        self.assertIn("\\input{x}", lexer.mask(src))

    def test_iffalse_with_iff_inside(self):
        src = "a\n\\iffalse\n$p \\iff q$ hidden\n\\fi\nb\n"
        self.assertEqual(lexer.strip_comments(src), "a\nb\n")

    def test_inline_verbatim(self):
        src = "\\verb@a%b@ \\lstinline|x % 2| \\lstinline[language=C]{y % 3} \\mintinline{c}{z % 4} % c\n"
        self.assertEqual(lexer.strip_comments(src),
                         "\\verb@a%b@ \\lstinline|x % 2| \\lstinline[language=C]{y % 3} \\mintinline{c}{z % 4} %\n")

    def test_mask_keeps_length(self):
        src = "x % \\input{a}\n\\input{b}\n"
        m = lexer.mask(src)
        self.assertEqual(len(m), len(src))
        self.assertNotIn("{a}", m)
        self.assertIn("\\input{b}", m)

    def test_remove_commands(self):
        self.assertEqual(lexer.remove_commands("a\\todo[inline]{fix {this}} b", ["todo"]), "a b")


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = fixture.build(self.tmp / "paper")
        self.before = tree_hash(self.src)

    def tearDown(self):
        self.assertEqual(tree_hash(self.src), self.before, "source directory was modified")
        shutil.rmtree(self.tmp)

    def test_roots(self):
        self.assertEqual(find_roots(self.src), ["appendix.tex", "main.tex"])

    def test_kept_files(self):
        plan = scan(self.src, ["main.tex", "appendix.tex"])
        self.assertEqual(plan.keep, {
            "main.tex", "appendix.tex", "main.bbl", "refs.bib", "styles/mystyle.sty",
            "sections/intro.tex", "sections/appendix_body.tex", "sections/sub/part.tex",
            "sections/sub/img.png", "sections/sub/plot.pdf", "figures/plot.pdf",
            "extra/plot.png", "code/snippet.py"})
        self.assertTrue(any("figs2/#1" in w for w in plan.warnings))

    def test_single_root(self):
        plan = scan(self.src, ["appendix.tex"])
        self.assertEqual(plan.keep, {"appendix.tex", "sections/appendix_body.tex"})

    def test_output_inside_source_is_refused(self):
        code, _, err = run_cli(self.src, "-o", self.src / "out")
        self.assertNotEqual(code, 0)
        self.assertFalse((self.src / "out").exists())

    def test_existing_output_needs_force(self):
        out = self.tmp / "out"
        out.mkdir()
        (out / "x").write_text("x")
        code, _, _ = run_cli(self.src, "-o", out)
        self.assertNotEqual(code, 0)
        self.assertTrue((out / "x").exists())
        code, _, _ = run_cli(self.src, "-o", out, "--force")
        self.assertEqual(code, 0)
        self.assertFalse((out / "x").exists())

    def test_flatten_names(self):
        out = self.tmp / "flat"
        code, _, _ = run_cli(self.src, "-o", out, "--flatten", "-k", "figs2/teaser.png")
        self.assertEqual(code, 0)
        self.assertTrue(all(p.parent == out for p in out.rglob("*")))
        names = sorted(p.name for p in out.iterdir())
        # on a name clash the shallowest file keeps its name
        self.assertIn("plot.pdf", names)
        self.assertIn("sections_sub_plot.pdf", names)
        main_tex = (out / "main.tex").read_text()
        self.assertIn("\\usepackage{mystyle}", main_tex)
        self.assertIn("\\includegraphics[width=1cm]{plot.pdf}", main_tex)
        self.assertIn("\\includegraphics[width=1cm]{#1}", main_tex)
        self.assertNotIn("graphicspath", main_tex)
        self.assertNotIn("secret", main_tex)
        self.assertNotIn("notes after the end", main_tex)
        part = (out / "part.tex").read_text()
        self.assertIn("{sections_sub_plot.pdf}", part)

    def test_case_mismatch_warning(self):
        (self.src / "sections" / "appendix_body.tex").write_text("\\includegraphics{figures/Plot.pdf}\n")
        self.before = tree_hash(self.src)
        plan = scan(self.src, ["appendix.tex"])
        self.assertIn("figures/plot.pdf", plan.keep)
        self.assertTrue(any("ignoring case" in w for w in plan.warnings), plan.warnings)

    @unittest.skipUnless(HAVE_TEX, "pdflatex/latexmk not available")
    def test_subdirectory_root_with_subfiles(self):
        proj = self.tmp / "sub"
        files = {
            "paper/main.tex": "\\documentclass{article}\n\\usepackage{graphicx}\n\\usepackage{subfiles}\n"
                              "\\begin{document}\n\\subfile{chapters/one}\n\\end{document}\n",
            "paper/chapters/one.tex": "\\documentclass[../main.tex]{subfiles}\n\\begin{document}\n"
                                      "One \\includegraphics[width=1cm]{../figs/a}\n\\end{document}\n",
            "figs/a.png": fixture.png_bytes(),
            "figs/b.png": fixture.png_bytes(),
        }
        for rel, content in files.items():
            p = proj / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            (p.write_bytes if isinstance(content, bytes) else p.write_text)(content)
        before = tree_hash(proj)
        plan = scan(proj, ["paper/main.tex"])
        self.assertEqual(plan.keep, {"paper/main.tex", "paper/chapters/one.tex", "figs/a.png"})
        for flat in (False, True):
            out = self.tmp / f"subout{int(flat)}"
            args = [proj, "-o", out, "-r", "paper/main.tex", "--check"] + (["--flatten"] if flat else [])
            code, stdout, stderr = run_cli(*args)
            self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(sorted(p.name for p in (self.tmp / "subout1").iterdir()), ["a.png", "main.tex", "one.tex"])
        one = (self.tmp / "subout1" / "one.tex").read_text()
        self.assertIn("\\documentclass[main.tex]{subfiles}", one)
        self.assertIn("{a.png}", one)
        self.assertEqual(tree_hash(proj), before)

    @unittest.skipUnless(HAVE_TEX, "pdflatex/latexmk not available")
    def test_kept_set_matches_tex_recorder(self):
        """Every project file read by pdflatex must be kept."""
        build = self.tmp / "build"
        shutil.copytree(self.src, build)
        used = set()
        for root in ("main.tex", "appendix.tex"):
            subprocess.run(["pdflatex", "-recorder", "-interaction=nonstopmode", root],
                           cwd=build, capture_output=True, stdin=subprocess.DEVNULL)
            for line in (build / root).with_suffix(".fls").read_text().splitlines():
                if line.startswith("INPUT ") and not line[6:].startswith("/"):
                    used.add(line[6:].removeprefix("./"))
        used = {u for u in used if not u.endswith(".aux")}
        plan = scan(self.src, ["main.tex", "appendix.tex"])
        missing = used - plan.keep
        # files referenced only through a macro are reported as warnings
        self.assertEqual(missing, {"figs2/teaser.png"})

    @unittest.skipUnless(HAVE_TEX, "pdflatex/latexmk not available")
    def test_outputs_compile(self):
        for flat in (False, True):
            out = self.tmp / f"out{int(flat)}"
            args = [self.src, "-o", out, "-k", "figs2/*.png", "--check"]
            if flat:
                args.append("--flatten")
            code, stdout, stderr = run_cli(*args)
            self.assertEqual(code, 0, stdout + stderr)
            self.assertIn("main.tex compiles", stdout)
            self.assertIn("appendix.tex compiles", stdout)


if __name__ == "__main__":
    unittest.main()
