# latex-cleaner

Prepares the LaTeX sources of a paper for submission (arXiv or similar).
The project is copied to a new directory that contains only the files needed
to compile the root documents, with comments removed. The source directory
is only read.

## Install

With [uv](https://docs.astral.sh/uv/), as a tool available on the `PATH`:

```sh
uv tool install git+https://github.com/carloalbertobarbano/latex-cleaner.git
uv tool upgrade latex-cleaner        # get the latest version
uv tool uninstall latex-cleaner
```

or run it once without installing:

```sh
uvx --from git+https://github.com/carloalbertobarbano/latex-cleaner.git latex-cleaner paper/
```

From a local checkout: `uv tool install .` (add `--editable` to pick up code
changes without reinstalling), `pip install .`, or `python -m latex_cleaner ...`.

Python 3.9 or later. No dependencies. `latexmk` is used only by `--check`.

## Usage

```sh
latex-cleaner paper/                          # writes paper_clean/
latex-cleaner paper/ -o submission/ -r main.tex -r appendix.tex
latex-cleaner paper/ --flatten --zip --check
latex-cleaner paper/ -n                       # dry run: list kept and removed files
```

| option | effect |
|---|---|
| `-o DIR` | output directory (default `<source>_clean`). It must be outside the source directory. |
| `-r FILE` | root document, repeatable. Without it, every `.tex` file containing `\begin{document}` is a root. The roots in use are printed. |
| `-f, --flatten` | put every file in the output directory itself and rewrite the paths in the sources |
| `-k GLOB` | also keep files matching the pattern, e.g. `-k 'figures/*.pdf'` |
| `--keep-comments` | do not remove comments |
| `--keep-iffalse` | do not remove `\iffalse ... \fi` blocks |
| `--remove-command NAME` | remove every `\NAME{...}`, e.g. `--remove-command todo` |
| `--drop-bib` | do not ship `.bib` files when the `.bbl` is present |
| `-n, --dry-run` | print the plan and write nothing |
| `--force` | replace a non-empty output directory |
| `--zip` | also write `<output>.zip` |
| `--check` | compile each root of the output with `latexmk` in a temporary copy. When a `.bbl` is present, BibTeX is not run, as on arXiv. |
| `--engine` | engine used by `--check`: `pdflatex` (default), `xelatex` or `lualatex` |
| `-v` | list every kept and removed file |

## What is kept

Starting from the roots, the tool follows the references that are not
commented out:

* `\input`, `\include`, `\subfile` (including the `\documentclass[../main.tex]{subfiles}`
  line of the subfile), `\import`/`\subimport` (and the `*from` variants),
  `\includestandalone`
* `\includegraphics` (with `\graphicspath` and the pdfLaTeX extension order),
  `\includesvg`, `\includepdf`, `\pgfimage`
* `\bibliography`, `\addbibresource`, `\bibliographystyle`
* local packages, classes and beamer themes (`\usepackage`, `\documentclass`, ...),
  which are themselves scanned
* `\lstinputlisting`, `\verbatiminput`, `\inputminted`
* any brace argument that names an existing file of the project, such as the
  data files of `\addplot table {data/results.csv}`

`<root>.bbl` (and `.ind`, `.gls`, `.nls`) next to each root is kept, as is
`00README` / `00README.XXX`. Paths are resolved as TeX does: relative to the
directory of the root, with `\import` and `\graphicspath` changing the search
path. A warning is printed when a root uses a bibliography and its `.bbl` is
missing, and when a reference matches a file only if case is ignored. Such
references compile on macOS and fail on case-sensitive systems such as the
arXiv build servers.

Paths assembled by macros, for example
`\newcommand{\fig}[1]{\includegraphics{figs/#1}}`, cannot be followed. The
tool reports them; add the files with `-k 'figs/*'` and use `--check`.

## Cleaning

In `.tex` files:

* full-line comments are removed; trailing comments are removed but the `%`
  stays, so that line endings are interpreted as before
* `comment` environments and `\iffalse ... \fi` blocks written on their own
  lines are removed
* text after `\end{document}` is removed
* `\iffalse` blocks with an `\else` branch are kept
* `\%`, `\verb`, `\lstinline`, `\mintinline`, `\url`, `\href` and
  verbatim-like environments (`verbatim`, `lstlisting`, `minted`, ...) are
  left as they are

Packages, classes, images and other files are copied byte for byte.

## Flattening

With `--flatten` every file is placed in the output directory itself.
Files keep their name when it is unique (ignoring case). When two files share
a name, the shallowest one keeps it and the others get their directory
prepended (`sections/sub/plot.pdf` becomes `sections_sub_plot.pdf`). Each
root keeps its name and its `.bbl` follows it.

References are rewritten accordingly. Graphics and `\input` paths are written
with their extension so that LaTeX cannot pick another file of the same name;
`\include`, `\usepackage`, `\bibliography` and similar commands are written
without it. `\graphicspath` is removed, `\import{dir/}{file}` becomes
`\import{./}{file}`, and the directory of macro-built paths (`figs/#1` →
`#1`) is dropped; a warning is printed if files of that directory had to be
renamed.

## Tests

```sh
python -m unittest discover tests
```

The tests build a small project, check the kept files against the list of
files that `pdflatex -recorder` reads, compile the normal and the flattened
output, and check that the source directory is unchanged.
