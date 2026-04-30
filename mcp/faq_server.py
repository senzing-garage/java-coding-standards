# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==1.27.0"]
# ///
"""FAQ MCP server for Java projects adopting the Senzing Java coding standards.

Serves project FAQs as searchable documents using BM25 (Okapi BM25) ranking.
Reads from one or more FAQ directories (shared standards FAQs + project-local
FAQs) and merges them into a single index. Self-contained; no dependencies
beyond the `mcp` package (auto-installed by `uv`).

Typical invocation from a consumer project's `.mcp.json`:

    {
      "mcpServers": {
        "<project>-faq": {
          "command": "uv",
          "args": [
            "run", "--script",
            ".java-coding-standards/mcp/faq_server.py",
            "--server-name=<project>-faq",
            "--faqs-dir=.claude/faqs",
            "--shared-faqs-dir=.java-coding-standards/docs/faqs"
          ]
        }
      }
    }

When the same `(category, title)` exists in both `--shared-faqs-dir` and
`--faqs-dir`, the project-local version shadows the shared one. This lets a
project override a shared FAQ when its needs diverge from the standard.
"""

import argparse
import math
import re
import sys
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "ERROR: The 'mcp' package is not installed.\n"
        "\n"
        "This script is designed to be run via uv with PEP 723 inline metadata:\n"
        "    uv run --script .java-coding-standards/mcp/faq_server.py\n"
        "\n"
        "If you don't have uv installed:\n"
        "    pip install uv   # or: brew install uv\n"
        "\n"
        "Alternatively, install the dependency manually:\n"
        "    pip install mcp==1.27.0\n"
        "    python .java-coding-standards/mcp/faq_server.py",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="faq_server",
        description=(
            "FAQ MCP server. Indexes one or more FAQ directories with BM25 "
            "ranking and exposes search_faqs / get_faq / get_faq_categories."
        ),
    )
    parser.add_argument(
        "--server-name",
        default="project-faq",
        help=(
            "Name registered with the MCP host (default: %(default)s). "
            "Convention: '<project>-faq' (e.g. 'senzing-commons-faq')."
        ),
    )
    parser.add_argument(
        "--faqs-dir",
        action="append",
        default=[],
        type=Path,
        help=(
            "Project-local FAQ directory; relative paths resolve from the "
            "current working directory. Repeatable. Project-local FAQs "
            "shadow shared FAQs with the same (category, title)."
        ),
    )
    parser.add_argument(
        "--shared-faqs-dir",
        type=Path,
        default=None,
        help=(
            "Shared FAQ directory bundled with the standards repo. If "
            "omitted, defaults to the script's sibling docs/faqs/ "
            "directory if present."
        ),
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# BM25 index
# ---------------------------------------------------------------------------

_K1 = 1.2
_B = 0.75
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization — keeps alphanumerics and underscores."""
    return _TOKEN_RE.findall(text.lower())


class _Document:
    """A single FAQ document with precomputed token frequencies."""

    __slots__ = ("category", "title", "content", "source", "tokens", "tf", "length")

    def __init__(
        self, category: str, title: str, content: str, source: str
    ) -> None:
        self.category = category
        self.title = title
        self.content = content
        self.source = source  # "shared" or "project"
        self.tokens = _tokenize(title + " " + content)
        self.length = len(self.tokens)
        self.tf: dict[str, int] = {}
        for tok in self.tokens:
            self.tf[tok] = self.tf.get(tok, 0) + 1


class _BM25Index:
    """Okapi BM25 index over a collection of FAQ documents."""

    def __init__(self) -> None:
        self.docs: list[_Document] = []
        self.df: dict[str, int] = {}
        self.avgdl: float = 0.0

    def add(self, doc: _Document) -> None:
        self.docs.append(doc)
        for term in set(doc.tf):
            self.df[term] = self.df.get(term, 0) + 1

    def finalize(self) -> None:
        if self.docs:
            self.avgdl = sum(d.length for d in self.docs) / len(self.docs)

    def search(
        self,
        query: str,
        category: str | None = None,
        max_results: int = 5,
    ) -> list[tuple[_Document, float]]:
        terms = _tokenize(query)
        if not terms:
            return []
        n = len(self.docs)
        scores: list[tuple[_Document, float]] = []
        for doc in self.docs:
            if category and doc.category != category:
                continue
            score = 0.0
            for t in terms:
                df = self.df.get(t, 0)
                if df == 0:
                    continue
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                tf = doc.tf.get(t, 0)
                if tf == 0:
                    continue
                numerator = tf * (_K1 + 1.0)
                denominator = tf + _K1 * (
                    1.0 - _B + _B * doc.length / max(self.avgdl, 1.0)
                )
                score += idf * numerator / denominator
            if score > 0:
                scores.append((doc, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:max_results]


# ---------------------------------------------------------------------------
# FAQ loading
# ---------------------------------------------------------------------------


def _load_dir(
    faq_dir: Path,
    source: str,
    raw: dict[tuple[str, str], tuple[str, str]],
) -> None:
    """Walk faq_dir/<category>/*.md and populate `raw` keyed by (cat, title).

    `source` is "shared" or "project" — used by the search API to indicate
    where each result came from. Later calls overwrite earlier entries with
    the same (category, title), which is how project-local files shadow
    shared ones (call order: shared first, then project).
    """
    if not faq_dir.is_dir():
        return
    for cat_dir in sorted(faq_dir.iterdir()):
        if not cat_dir.is_dir():
            continue
        category = cat_dir.name
        for md in sorted(cat_dir.glob("*.md")):
            title = md.stem.replace("-", " ")
            content = md.read_text(encoding="utf-8")
            raw[(category, title)] = (content, source)


def _build_index(
    shared_dir: Path | None,
    project_dirs: list[Path],
) -> tuple[dict[str, dict[str, str]], _BM25Index]:
    raw: dict[tuple[str, str], tuple[str, str]] = {}
    if shared_dir is not None:
        _load_dir(shared_dir, "shared", raw)
    for d in project_dirs:
        _load_dir(d, "project", raw)

    faqs: dict[str, dict[str, str]] = {}
    index = _BM25Index()
    for (category, title), (content, source) in sorted(raw.items()):
        faqs.setdefault(category, {})[title] = content
        index.add(_Document(category, title, content, source))
    index.finalize()
    return faqs, index


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------


def _default_shared_dir() -> Path | None:
    """Location of the bundled shared FAQs relative to this script."""
    candidate = Path(__file__).resolve().parent.parent / "docs" / "faqs"
    return candidate if candidate.is_dir() else None


def _server_instructions(shared_count: int, project_count: int) -> str:
    return (
        "Java project FAQ server. Consult these tools BEFORE: "
        "(a) generating or modifying Java code in this repo — search "
        "for 'java formatting' or read the standards document at "
        "`.java-coding-standards/docs/java-coding-standards.md` so new "
        "code follows the brace style, 80-char line limit, javadoc "
        "reflow, and parameter-alignment rules from the start rather "
        "than being reformatted afterward; "
        "(b) making design decisions, modifying public APIs, or "
        "changing build/release configuration; "
        "(c) troubleshooting any build, test, dependency, library, "
        "or release issue. The FAQ corpus merges shared standards "
        "FAQs with project-local FAQs (currently "
        f"{shared_count} shared + {project_count} project-local). "
        "If FAQ search returns no useful results, TELL THE USER and "
        "recommend adding a FAQ after the issue is resolved."
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    shared_dir = args.shared_faqs_dir
    if shared_dir is None:
        shared_dir = _default_shared_dir()

    faqs, index = _build_index(shared_dir, args.faqs_dir)
    shared_count = sum(
        1 for d in index.docs if d.source == "shared"
    )
    project_count = sum(
        1 for d in index.docs if d.source == "project"
    )

    mcp = FastMCP(
        args.server_name,
        instructions=_server_instructions(shared_count, project_count),
    )

    @mcp.tool()
    def get_faq_categories() -> str:
        """List all FAQ categories with the number of articles in each."""
        if not faqs:
            return (
                "No FAQ categories found. Pass --shared-faqs-dir and/or "
                "--faqs-dir pointing at directories containing "
                "<category>/<topic>.md files."
            )
        lines = []
        for cat in sorted(faqs):
            count = len(faqs[cat])
            titles = ", ".join(sorted(faqs[cat]))
            lines.append(f"**{cat}** ({count}): {titles}")
        return "\n".join(lines)

    @mcp.tool()
    def search_faqs(
        query: str, category: str | None = None, max_results: int = 5
    ) -> str:
        """Search FAQs using BM25 ranking. Returns titles + matching excerpts.

        Args:
            query: keyword(s) to search for
            category: optional category filter
            max_results: max results to return (default 5)
        """
        results = index.search(query, category=category, max_results=max_results)
        if not results:
            return f"No results for '{query}'."

        lines = []
        for doc, score in results:
            query_lower = query.lower()
            content_lower = doc.content.lower()
            idx = content_lower.find(query_lower)
            matched_len = len(query)
            if idx < 0:
                for term in _tokenize(query):
                    idx = content_lower.find(term)
                    if idx >= 0:
                        matched_len = len(term)
                        break
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(doc.content), idx + matched_len + 120)
                excerpt = (
                    ("..." if start > 0 else "")
                    + doc.content[start:end].strip()
                    + ("..." if end < len(doc.content) else "")
                )
            else:
                excerpt = doc.content[:200].strip() + (
                    "..." if len(doc.content) > 200 else ""
                )
            lines.append(
                f"### [{doc.category}/{doc.source}] {doc.title} "
                f"(score: {score:.2f})\n{excerpt}\n"
            )
        return "\n".join(lines)

    @mcp.tool()
    def get_faq(title: str, category: str | None = None) -> str:
        """Get full content of a specific FAQ by title.

        Args:
            title: FAQ title (use dashes or spaces, case-insensitive)
            category: optional category to narrow the search
        """
        title_normalized = title.lower().replace("-", " ")

        cats = [category] if category and category in faqs else sorted(faqs)
        for cat in cats:
            for faq_title, content in faqs.get(cat, {}).items():
                if faq_title.lower() == title_normalized:
                    return f"# [{cat}] {faq_title}\n\n{content}"

        for cat in cats:
            for faq_title, content in faqs.get(cat, {}).items():
                if (
                    title_normalized in faq_title.lower()
                    or faq_title.lower() in title_normalized
                ):
                    return f"# [{cat}] {faq_title}\n\n{content}"

        return (
            f"FAQ '{title}' not found. "
            "Use get_faq_categories() to see available FAQs."
        )

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
