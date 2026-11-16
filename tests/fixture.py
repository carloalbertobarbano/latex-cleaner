"""Build a small LaTeX project used by the tests."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png_bytes(w: int = 4, h: int = 4) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def pdf_bytes() -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 20 20] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length 23 >>\nstream\n0 0 1 rg 0 0 20 20 re f\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


MAIN = r"""\documentclass{article}
\usepackage{graphicx}
\usepackage{listings}
\usepackage{styles/mystyle}
\usepackage{import}
\usepackage{url}
\graphicspath{{figures/}{extra/}}
% \usepackage{styles/unused}
\newcommand{\fig}[1]{\includegraphics[width=1cm]{figs2/#1}}
\begin{document}
Hello world. % a trailing comment
Percent sign \% kept. \verb|50% verbatim| and \url{https://x.org/a%20b}.
% a full-line comment
\input{sections/intro}
%\input{sections/old}
\import{sections/sub/}{part}
\includegraphics[width=1cm]{plot}
\includegraphics[width=1cm]{extra/plot.png}
\fig{teaser}
\lstinputlisting{code/snippet.py}
\begin{comment}
\includegraphics{unused}
\end{comment}
\iffalse
secret text
\fi
\begin{verbatim}
% this is verbatim and stays
\end{verbatim}
\mystylemacro
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
notes after the end that must not be shipped
"""

APPENDIX = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\input{sections/appendix_body}
\end{document}
"""

INTRO = r"""\section{Intro}
Intro text~\cite{knuth}.% no space
\includegraphics[width=1cm]{figures/plot.pdf}
"""

PART = r"""\section{Part}
\includegraphics[width=1cm]{img}
\includegraphics[width=1cm]{plot}
"""

STY = r"""\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{styles/mystyle}
\RequirePackage{verbatim}
\newcommand{\mystylemacro}{From the style.}
"""

BIB = r"""@book{knuth, author={Donald Knuth}, title={The TeXbook}, year={1984}, publisher={AW}}
"""

BBL = r"""\begin{thebibliography}{1}
\bibitem{knuth} D.~Knuth. \newblock {\em The TeXbook}. 1984.
\end{thebibliography}
"""


def build(root: Path) -> Path:
    files = {
        "main.tex": MAIN,
        "main.bbl": BBL,
        "main.log": "log",
        "main.aux": "\\relax\n",
        "appendix.tex": APPENDIX,
        "sections/intro.tex": INTRO,
        "sections/old.tex": "old content\n",
        "sections/appendix_body.tex": "Appendix body.\n",
        "sections/sub/part.tex": PART,
        "styles/mystyle.sty": STY,
        "styles/unused.sty": "% unused\n",
        "refs.bib": BIB,
        "code/snippet.py": "print('hi')  # 100%\n",
        "notes.txt": "private notes\n",
    }
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    binaries = {
        "figures/plot.pdf": pdf_bytes(),
        "figures/old.pdf": pdf_bytes(),
        "sections/sub/plot.pdf": pdf_bytes(),
        "figures/unused.png": png_bytes(),
        "extra/plot.png": png_bytes(),
        "sections/sub/img.png": png_bytes(),
        "figs2/teaser.png": png_bytes(),
        "figs2/other.png": png_bytes(),
    }
    for rel, content in binaries.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return root


if __name__ == "__main__":
    import sys
    build(Path(sys.argv[1]))
