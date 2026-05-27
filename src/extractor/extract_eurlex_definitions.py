#!/usr/bin/env python3
"""Extract definitions from EUR-Lex HTML documents (consolidated acts).

Parses the structured HTML produced by EUR-Lex (docHtml subtree) and emits
three record types: definition, article_metadata, and footnote.

Usage:
    python3 src/extractor/extract_eurlex_definitions.py \\
        --input path/to/ucc_en.html \\
        --celex 02013R0952-20221212 \\
        --lang en \\
        --output data/domain_db/ucc_definitions.jsonl \\
        [--article 5]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import warnings
from pathlib import Path
from typing import Any, Iterator

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("Error: beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

DEFINITION_PATTERN = re.compile(
    r"""
    [""'“”‘’]
    (?P<term>[^""'“”‘’]{2,120})
    [""'“”‘’]
    \s+means\b
    """,
    re.VERBOSE,
)

# French legal drafting: <<term>>, definition... or <<term>>: list...
# Quote variants: ASCII ", curly \u201c/\u201d, French guillemets \u00ab/\u00bb
# Separator: comma (noun-phrase definition) or colon (sub-list)
# Optional "ou ABBREV" between closing quote and separator handles
# the rare "<<term>> ou ABBREV, definition" abbreviation convention.
FRENCH_DEFINITION_PATTERN = re.compile(
    r"""
    ^\s*
    [\u00ab"\u201c\u201d]        # opening: << or ASCII " or curly "/
    (?P<term>[^\u00bb"\u201c\u201d]+?)  # term (non-greedy, no nested quote)
    [\u00bb"\u201c\u201d]        # closing: >> or ASCII " or curly "/
    (?:\s+(?:ou\s+[A-Z\u00c0-\u00dd]{2,10}|\([^)]+\)))?  # optional "ou ABBREV" or "(ABBREV)" (rare)
    \s*[:,](?:\s+|$)             # separator: colon or comma (space optional at EOL)
    """,
    re.VERBOSE | re.UNICODE,
)

# Dispatch table: language code → definition-match pattern.
# Tablelayout (LT) uses its own cell-based parser and never calls _match_definition().
DEFINITION_PATTERN_BY_LANG: dict[str, re.Pattern[str]] = {
    "en": DEFINITION_PATTERN,
    "fr": FRENCH_DEFINITION_PATTERN,
}


def _get_definition_pattern(lang: str) -> re.Pattern[str]:
    return DEFINITION_PATTERN_BY_LANG.get(lang, DEFINITION_PATTERN)


FOOTNOTE_REF_PATTERN = re.compile(r"\s*\(\s*\d+\s*\)")

TRIANGLE_PATTERN = re.compile(r"[▼▲]([A-Z]\d*|[A-Z])")

# Corrigendum markers: ►C2 / ▶M4 (open) and ◄ / ◀ (close)
CORRIGENDUM_RE = re.compile(r"[►▶][A-Z]\d*\s*|\s*[◄◀]")

# Matches the article id attribute, e.g. art_5 or art_5a
ART_ID_PATTERN = re.compile(r"^art_\w+$")

# Matches numbered-item list markers: "1) ", "19) " (no leading parenthesis).
# Used to distinguish divlayout_numbered (LT, FR-like) from standard divlayout (EN).
NUMBERED_ITEM_PATTERN = re.compile(r"^\d+\)\s+")

# Celex date suffix e.g. "02013R0952-20221212" → "2022-12-12"
CELEX_DATE_PATTERN = re.compile(r"-(\d{4})(\d{2})(\d{2})$")

# Per-language keywords that identify a Definitions article by rubric (substring match).
# Lowercased; diacritic-stripped match is applied — see _find_definitions_article().
DEFINITION_RUBRICS: dict[str, list[str]] = {
    "en": ["definition", "definitions"],
    "lt": ["apibrėžt"],          # apibrėžtys / apibrėžimai
    "fr": ["définition", "définitions"],
    "de": ["begriffsbestimmung"],
    "es": ["definicion"],        # also "definición"
    "it": ["definizion"],
    "pl": ["definicj"],
    "nl": ["definitie"],
    "pt": ["definiç"],
    "sv": ["definition"],
}

# Article number from title text: "5 straipsnis", "5 straipsnio", "Article 5"
ART_NUM_TEXT_PATTERN = re.compile(
    r"(\d+)\s*(?:straipsnis|straipsnio|article)?",
    re.IGNORECASE,
)


def _parse_celex_date(celex_id: str) -> str | None:
    """Extract ISO date from celex_id suffix, e.g. '02013R0952-20221212' → '2022-12-12'."""
    m = CELEX_DATE_PATTERN.search(celex_id)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _extract_article_number_from_text(text: str) -> str | None:
    """Extract article number from a localized title string.

    Handles '5 straipsnis', '5 straipsnio' (Lithuanian genitive), 'Article 5'.
    Returns the bare digit string, e.g. '5'.
    """
    m = ART_NUM_TEXT_PATTERN.search(_normalize_nbsp(text))
    return m.group(1) if m else None


class UnknownLayoutError(Exception):
    """Raised when EUR-Lex HTML layout cannot be determined."""


def detect_layout(soup: BeautifulSoup) -> str:
    """Return 'divlayout' or 'tablelayout' for a EUR-Lex HTML document.

    divlayout  — eli-subdivision wrappers present (EN and many languages)
    tablelayout — table rows with dlist-term/dlist-definition cells (LT etc.)
    """
    doc_div = soup.find("div", id="docHtml") or soup
    if doc_div.find("div", class_="eli-subdivision"):
        return "divlayout"
    if doc_div.find(class_="dlist-term") or doc_div.find(class_="dlist-definition"):
        return "tablelayout"
    raise UnknownLayoutError("Cannot determine EUR-Lex HTML layout variant")


def _strip_corrigendum_markers(text: str) -> str:
    """Remove ►Cx / ◄ corrigendum open/close markers, keeping inner content."""
    return CORRIGENDUM_RE.sub("", text)


def _normalize_nbsp(text: str) -> str:
    """Replace non-breaking spaces with regular spaces and strip."""
    return text.replace("\xa0", " ").strip()


def _strip_diacritics(text: str) -> str:
    """Remove combining diacritical marks, leaving base characters."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def _get_text(el: Tag | None) -> str:
    """Get normalized text from a BeautifulSoup element."""
    if el is None:
        return ""
    return _normalize_nbsp(el.get_text(" ", strip=True))


def _strip_definition_text(text: str) -> str:
    """Strip trailing semicolons, nbsp, and footnote references from definition text."""
    text = _normalize_nbsp(text)
    text = FOOTNOTE_REF_PATTERN.sub("", text)
    text = text.rstrip(";").rstrip()
    return text


def _parse_amendment_marker(p_modref: Tag) -> dict[str, Any]:
    """Parse a p.modref element to extract amendment info."""
    a_tag = p_modref.find("a")
    marker = "B"
    celex = ""
    action = None

    if a_tag:
        title = a_tag.get("title", "") or ""
        parts = title.split(":", 1)
        celex = parts[0].strip()
        action = parts[1].strip() if len(parts) > 1 else None
        if not action:
            action = None

        # Extract triangle marker from full text of the modref paragraph
        full_text = p_modref.get_text()
        tm = TRIANGLE_PATTERN.search(full_text)
        if tm:
            marker = tm.group(1)

    return {"marker": marker, "celex": celex, "action": action}


def _normalize_list_marker(raw: str) -> str:
    """Normalize a list column-1 marker: strip whitespace and parentheses."""
    return raw.strip().strip("()")


def _get_article_rubric(art_div: Tag) -> tuple[str | None, str | None]:
    """Return (rubric_text, source) for an article div element.

    source is 'article' when stitle-article-norm is present inside art_div,
    'chapter' when inherited from the closest enclosing cpt_* or tis_* parent's
    title-division-2 element, or None when no rubric is found anywhere.

    Some regulations (e.g. 2021/821 Dual Use) attach rubrics at the chapter level
    (title-division-2) rather than per article (stitle-article-norm).  In those
    cases the chapter rubric is the most specific label available.
    """
    own = art_div.find("p", class_="stitle-article-norm")
    if own:
        text = _get_text(own)
        if text:
            return text, "article"

    for parent in art_div.parents:
        if not isinstance(parent, Tag):
            continue
        pid = parent.get("id", "") or ""
        if pid.startswith("cpt_") or pid.startswith("tis_"):
            rubric_el = parent.find("p", class_="title-division-2", recursive=False)
            if rubric_el:
                text = _get_text(rubric_el)
                if text:
                    return text, "chapter"
    return None, None


def _collect_sub_items(parent: Tag, amendment_cursor: dict[str, Any]) -> list[dict]:
    """Recursively collect sub-items by iterating direct children of parent.

    parent is typically a grid-list-column-2 div whose direct children may include
    p.modref elements (which update the cursor) and grid-container divs (sub-items).
    """
    sub_items: list[dict] = []
    cursor = dict(amendment_cursor)

    for child in parent.children:
        if not isinstance(child, Tag):
            continue
        classes = set(child.get("class") or [])

        if "modref" in classes and child.name == "p":
            cursor = _parse_amendment_marker(child)
            continue

        if "grid-container" not in classes:
            continue

        col1 = child.find("div", class_="grid-list-column-1", recursive=False)
        col2 = child.find("div", class_="grid-list-column-2", recursive=False)

        marker = ""
        if col1:
            span = col1.find("span")
            raw = _get_text(span) if span else _get_text(col1)
            marker = _normalize_list_marker(raw)

        text = ""
        nested_sub: list[dict] = []
        if col2:
            p_norm = col2.find("p", class_="norm")
            if p_norm:
                text = _normalize_nbsp(p_norm.get_text(" ", strip=True))
                text = FOOTNOTE_REF_PATTERN.sub("", text).rstrip(";").rstrip()
            nested_sub = _collect_sub_items(col2, dict(cursor))

        sub_items.append(
            {
                "marker": marker,
                "text": text,
                "amendment": dict(cursor),
                "sub_items": nested_sub,
            }
        )
    return sub_items


def _collect_footnote_refs(p_norm: Tag) -> list[str]:
    """Collect footnote anchor ids from a p.norm element."""
    refs = []
    for a in p_norm.find_all("a"):
        aid = a.get("id", "")
        if aid.startswith("src.E"):
            refs.append(aid[4:])  # strip "src."
    return refs


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------


class EurLexExtractor:
    """Extract definitions from a EUR-Lex consolidated HTML document."""

    def __init__(self, celex_id: str, lang: str) -> None:
        self.celex_id = celex_id
        self.lang = lang
        self._warnings: list[str] = []

    def parse_html(self, path: Path) -> BeautifulSoup:
        """Parse HTML file, returning BeautifulSoup tree scoped to docHtml."""
        raw = path.read_bytes()
        try:
            soup = BeautifulSoup(raw, "lxml")
        except Exception:
            soup = BeautifulSoup(raw, "html.parser")
        return soup

    def _collect_structural_context(self, doc_div: Tag) -> dict[str, dict]:
        """Build a mapping of art_id → context dict by walking structural divs."""
        contexts: dict[str, dict] = {}

        for art_div in doc_div.find_all("div", id=ART_ID_PATTERN):
            art_id = art_div.get("id", "")
            ctx: dict[str, Any] = {
                "title_label": None,
                "title_rubric": None,
                "chapter_label": None,
                "chapter_rubric": None,
                "section_label": None,
                "section_rubric": None,
                "article_number": None,
                "article_rubric": None,
            }

            # Walk parent chain to collect structural labels
            for parent in art_div.parents:
                if not isinstance(parent, Tag):
                    continue
                pid = parent.get("id", "") or ""
                pcls = set(parent.get("class") or [])

                if pid.startswith("tis_") or "eli-title" in pcls:
                    if ctx["title_label"] is None:
                        label_el = parent.find(class_=re.compile(r"^tis_label"))
                        rubric_el = parent.find(class_=re.compile(r"^tis_rubric"))
                        ctx["title_label"] = _get_text(label_el) or None
                        ctx["title_rubric"] = _get_text(rubric_el) or None

                if pid.startswith("cpt_") or "eli-chapter" in pcls:
                    if ctx["chapter_label"] is None:
                        label_el = parent.find(class_=re.compile(r"^cpt_label"))
                        rubric_el = parent.find(class_=re.compile(r"^cpt_rubric"))
                        ctx["chapter_label"] = _get_text(label_el) or None
                        ctx["chapter_rubric"] = _get_text(rubric_el) or None

                if pid.startswith("sct_") or "eli-section" in pcls:
                    if ctx["section_label"] is None:
                        label_el = parent.find(class_=re.compile(r"^sct_label"))
                        rubric_el = parent.find(class_=re.compile(r"^sct_rubric"))
                        ctx["section_label"] = _get_text(label_el) or None
                        ctx["section_rubric"] = _get_text(rubric_el) or None

            # Article number and rubric from within the article div itself
            art_num_el = art_div.find("p", class_="title-article-norm")
            if art_num_el:
                raw = _get_text(art_num_el)
                # Extract just the number
                num_match = re.search(r"\d+\w*", raw)
                ctx["article_number"] = num_match.group(0) if num_match else raw or None

            rubric_text, rubric_source = _get_article_rubric(art_div)
            ctx["article_rubric"] = rubric_text
            ctx["article_rubric_source"] = rubric_source

            contexts[art_id] = ctx

        return contexts

    def _walk_with_amendment_cursor(
        self, article_div: Tag
    ) -> Iterator[tuple[Tag, dict[str, Any]]]:
        """Yield (element, amendment_cursor) for all non-modref elements in article_div."""
        # Reset cursor at start of each article
        cursor: dict[str, Any] = {"marker": "B", "celex": "", "action": None}

        for el in article_div.descendants:
            if not isinstance(el, Tag):
                continue
            classes = set(el.get("class") or [])
            if "modref" in classes and el.name == "p":
                cursor = _parse_amendment_marker(el)
            else:
                yield el, dict(cursor)

    def _build_list_path(self, item_div: Tag, article_root: Tag) -> str:
        """Build dotted list path like '1', '2.a', '40.a.i' by walking parent chain."""
        parts: list[str] = []
        node: Tag | None = item_div
        while node is not None and node != article_root:
            parent = node.parent
            if not isinstance(parent, Tag):
                break
            pcls = set(parent.get("class") or [])
            if "grid-container" in pcls or parent.name == "div" and parent.find(
                "div", class_="grid-list-column-1", recursive=False
            ):
                col1 = parent.find("div", class_="grid-list-column-1", recursive=False)
                if col1:
                    span = col1.find("span")
                    raw = _get_text(span) if span else _get_text(col1)
                    marker = _normalize_list_marker(raw)
                    if marker:
                        parts.append(marker)
            node = parent

        parts.reverse()
        return ".".join(parts) if parts else ""

    def _match_definition(
        self, item_div: Tag, amendment_cursor: dict[str, Any], article_root: Tag
    ) -> dict | None:
        """Try to extract a definition from item_div. Returns record dict or None."""
        col2 = item_div.find("div", class_="grid-list-column-2", recursive=False)
        if col2 is None:
            return None

        p_norm = col2.find("p", class_="norm")
        if p_norm is None:
            return None

        full_text = _normalize_nbsp(p_norm.get_text(" ", strip=True))
        pattern = _get_definition_pattern(self.lang)
        m = pattern.search(full_text)
        if not m:
            return None

        term = m.group("term").strip()

        # Definition is text after the matched separator to end of p.norm
        after_means = full_text[m.end():].strip()
        definition = _strip_definition_text(after_means)

        # Footnote refs
        footnote_refs = _collect_footnote_refs(p_norm)

        # Sub-items from nested grid containers in col2 (modref siblings update cursor)
        sub_items = _collect_sub_items(col2, dict(amendment_cursor))

        # Build list path from item_div's grid-list-column-1
        list_path = self._build_list_path(item_div, article_root)

        return {
            "term": term,
            "definition": definition,
            "amendment": dict(amendment_cursor),
            "footnote_refs": footnote_refs,
            "sub_items": sub_items,
            "list_path": list_path,
        }

    def _article_uses_numbered_items(self, art_div: Tag) -> bool:
        """Return True if art_div uses N) term – definition style (LT and similar).

        Inspects the first top-level grid-container: if its full text starts with
        a digit followed by ')' and whitespace, the article uses the numbered-item
        variant rather than the standard '"term" means definition' style.
        """
        for el in art_div.descendants:
            if not isinstance(el, Tag):
                continue
            if "grid-container" not in set(el.get("class") or []):
                continue
            # Skip nested grid-containers (only inspect top-level ones)
            parent_is_gc = False
            for anc in el.parents:
                if anc is art_div:
                    break
                if isinstance(anc, Tag) and "grid-container" in set(anc.get("class") or []):
                    parent_is_gc = True
                    break
            if parent_is_gc:
                continue
            text = _normalize_nbsp(el.get_text(" ", strip=True))
            return bool(NUMBERED_ITEM_PATTERN.match(text))
        return False

    def _match_definition_numbered(
        self,
        item_div: Tag,
        amendment_cursor: dict[str, Any],
        article_root: Tag,
    ) -> dict | None:
        """Extract a definition from a numbered-item grid-container (LT and similar).

        Handles two sub-cases:
          A) Simple: p.norm text is 'term – definition;' → split on first en/em-dash.
          B) Chapeau: p.norm text ends with ':' → term only; sub-items follow as
             nested grid-containers inside col2.

        list_path is the numeric marker from col1 (e.g. '1', '19'), NOT the
        sequential def_count, so it aligns with EN divlayout's positional numbering.
        """
        col2 = item_div.find("div", class_="grid-list-column-2", recursive=False)
        if col2 is None:
            return None

        p_norm = col2.find("p", class_="norm")
        if p_norm is None:
            return None

        full_text = _normalize_nbsp(p_norm.get_text(" ", strip=True))
        footnote_refs = _collect_footnote_refs(p_norm)
        sub_items = _collect_sub_items(col2, dict(amendment_cursor))

        # list_path from col1 numeric marker ("1) " → "1", "19) " → "19")
        col1 = item_div.find("div", class_="grid-list-column-1", recursive=False)
        if col1:
            span = col1.find("span")
            raw = _get_text(span) if span else _get_text(col1)
            list_path = _normalize_list_marker(raw)
        else:
            list_path = ""

        # Language-dispatched pattern (French and future non-EN numbered layouts).
        # Tried before the LT en-dash logic; tablelayout is a separate code path.
        pattern = _get_definition_pattern(self.lang)
        if pattern is not DEFINITION_PATTERN:
            m = pattern.search(full_text)
            if m:
                term = m.group("term").strip()
                after_sep = full_text[m.end():].strip()
                # Chapeau: remainder ends with colon → definition lives in sub_items
                if after_sep.endswith(":") or (not after_sep and sub_items):
                    definition = ""
                else:
                    definition = _strip_definition_text(after_sep) if after_sep else ""
                return {
                    "term": term,
                    "definition": definition,
                    "amendment": dict(amendment_cursor),
                    "footnote_refs": footnote_refs,
                    "sub_items": sub_items,
                    "list_path": list_path,
                }

        # Sub-case B: chapeau — term ends with ':', actual definition in sub-items
        if full_text.endswith(":"):
            term = full_text.rstrip(":").strip()
            # Strip linking verb phrase (e.g. "– tai", "– yra") and any body text
            # that follows the first en/em-dash so that "eksportas – tai" → "eksportas"
            term = re.sub(r"\s*[–—].*", "", term, flags=re.DOTALL).strip()
            if not term:
                return None
            if len(term.split()) > 5:
                self._warnings.append(f"Long chapeau term ({len(term.split())} words): {term!r}")
                term = " ".join(term.split()[:5])
            return {
                "term": term,
                "definition": "",
                "amendment": dict(amendment_cursor),
                "footnote_refs": footnote_refs,
                "sub_items": sub_items,
                "list_path": list_path,
            }

        # Sub-case A: 'term – definition text;' on a single p.norm line
        idx = full_text.find("–")  # en-dash
        if idx == -1:
            idx = full_text.find("—")  # em-dash
        if idx == -1:
            return None

        term = full_text[:idx].strip()
        if not term:
            return None

        definition = _strip_definition_text(full_text[idx + 1:])

        return {
            "term": term,
            "definition": definition,
            "amendment": dict(amendment_cursor),
            "footnote_refs": footnote_refs,
            "sub_items": sub_items,
            "list_path": list_path,
        }

    def _collect_footnotes(self, soup: BeautifulSoup) -> list[dict]:
        """Collect all footnote records from div[id^='fnp_'] elements."""
        footnotes = []
        doc_div = soup.find("div", id="docHtml") or soup
        for fn_div in doc_div.find_all("div", id=re.compile(r"^fnp_")):
            fn_id = fn_div.get("id", "")[4:]  # strip "fnp_"
            # Marker is typically the number after "fnp_E" or just the number
            marker_match = re.search(r"\d+", fn_id)
            marker = marker_match.group(0) if marker_match else fn_id
            text = _normalize_nbsp(fn_div.get_text(" ", strip=True))
            footnotes.append(
                {
                    "record_type": "footnote",
                    "lang": self.lang,
                    "source_ref": {
                        "celex_id": self.celex_id,
                        "footnote_id": fn_id,
                    },
                    "marker": marker,
                    "text": text,
                }
            )
        return footnotes

    def _article_url(self, art_id: str) -> str:
        base = "https://eur-lex.europa.eu/legal-content"
        return f"{base}/{self.lang.upper()}/TXT/HTML/?uri=CELEX:{self.celex_id}#{art_id}"

    def _structural_path(self, art_div: Tag) -> str:
        """Build structural path like 'enc_1.tis_I.cpt_1.art_5'."""
        parts: list[str] = []
        for parent in reversed(list(art_div.parents)):
            if not isinstance(parent, Tag):
                continue
            pid = parent.get("id", "")
            if pid and re.match(r"^(enc|tis|cpt|sct|art)_", pid):
                parts.append(pid)
        art_id = art_div.get("id", "")
        if art_id not in parts:
            parts.append(art_id)
        return ".".join(parts)

    def _extract_variant_a(
        self,
        doc_div: Tag,
        article_filter: str | None,
        amendments_detected: set[str],
    ) -> list[dict]:
        """Extract definitions from Variant A HTML (eli-subdivision wrappers present)."""
        contexts = self._collect_structural_context(doc_div)
        records: list[dict] = []
        skipped_annexes = 0
        skipped_recitals = 0

        for art_div in doc_div.find_all("div", id=ART_ID_PATTERN):
            art_id = art_div.get("id", "")

            skip = False
            for ancestor in art_div.parents:
                if not isinstance(ancestor, Tag):
                    continue
                anc_id = ancestor.get("id", "") or ""
                if anc_id.startswith("anx_"):
                    skipped_annexes += 1
                    skip = True
                    break
                if anc_id.startswith("rct_"):
                    skipped_recitals += 1
                    skip = True
                    break
            if skip:
                continue

            ctx = contexts.get(art_id, {})
            art_num = ctx.get("article_number")

            if article_filter is not None and art_num != article_filter:
                continue

            structural_path = self._structural_path(art_div)
            def_count = 0
            seen_grid_containers: set[int] = set()
            cursor: dict[str, Any] = {"marker": "B", "celex": "", "action": None}
            use_numbered = self._article_uses_numbered_items(art_div)

            for el in art_div.descendants:
                if not isinstance(el, Tag):
                    continue
                classes = set(el.get("class") or [])

                if "modref" in classes and el.name == "p":
                    cursor = _parse_amendment_marker(el)
                    mk = cursor.get("marker", "B")
                    if mk:
                        amendments_detected.add(mk)
                    continue

                if "grid-container" not in classes:
                    continue

                eid = id(el)
                if eid in seen_grid_containers:
                    continue

                parent_is_grid = False
                for anc in el.parents:
                    if anc == art_div:
                        break
                    if isinstance(anc, Tag) and "grid-container" in set(anc.get("class") or []):
                        parent_is_grid = True
                        break
                if parent_is_grid:
                    continue

                seen_grid_containers.add(eid)
                if use_numbered:
                    result = self._match_definition_numbered(el, cursor, art_div)
                else:
                    result = self._match_definition(el, cursor, art_div)
                if result is None:
                    continue

                def_count += 1
                list_path = result["list_path"] or str(def_count)
                records.append({
                    "record_type": "definition",
                    "term": result["term"],
                    "term_normalized": result["term"].lower(),
                    "definition": result["definition"],
                    "lang": self.lang,
                    "approved": False,
                    "source_ref": {
                        "celex_id": self.celex_id,
                        "structural_path": structural_path,
                        "list_path": list_path,
                        "url": self._article_url(art_id),
                        "layout": "divlayout",
                    },
                    "amendment": result["amendment"],
                    "context": {
                        "article_number": ctx.get("article_number"),
                        "article_rubric": ctx.get("article_rubric"),
                        "title_label": ctx.get("title_label"),
                        "title_rubric": ctx.get("title_rubric"),
                        "chapter_label": ctx.get("chapter_label"),
                        "chapter_rubric": ctx.get("chapter_rubric"),
                        "section_label": ctx.get("section_label"),
                        "section_rubric": ctx.get("section_rubric"),
                    },
                    "sub_items": result["sub_items"],
                    "footnote_refs": result["footnote_refs"],
                })

            records.append({
                "record_type": "article_metadata",
                "lang": self.lang,
                "source_ref": {
                    "celex_id": self.celex_id,
                    "structural_path": structural_path,
                    "layout": "divlayout",
                },
                "article_number": ctx.get("article_number"),
                "article_rubric": ctx.get("article_rubric"),
                "article_rubric_source": ctx.get("article_rubric_source"),
                "context": {
                    "article_number": ctx.get("article_number"),
                    "article_rubric": ctx.get("article_rubric"),
                    "title_label": ctx.get("title_label"),
                    "title_rubric": ctx.get("title_rubric"),
                    "chapter_label": ctx.get("chapter_label"),
                    "chapter_rubric": ctx.get("chapter_rubric"),
                    "section_label": ctx.get("section_label"),
                    "section_rubric": ctx.get("section_rubric"),
                },
                "definition_count": def_count,
            })

        if skipped_annexes:
            self._warnings.append(f"Skipped {skipped_annexes} annex article(s)")
        if skipped_recitals:
            self._warnings.append(f"Skipped {skipped_recitals} recital article(s)")

        return records

    def _extract_variant_b(
        self,
        doc_div: Tag,
        article_filter: str | None,
        amendments_detected: set[str],
    ) -> list[dict]:
        """Extract definitions from Variant B HTML (flat structure, no eli-subdivision).

        Articles are delimited by p.title-article-norm elements in the flat child
        stream of docHtml.  Structural context comes from title-division-1/2 elements
        that appear before their articles.  The amendment cursor resets at each
        article boundary.
        """
        records: list[dict] = []

        # Running structural context, updated as flat elements are encountered
        ctx_state: dict[str, Any] = {
            "title_label": None,
            "title_rubric": None,
            "chapter_label": None,
            "chapter_rubric": None,
            "section_label": None,
            "section_rubric": None,
        }

        art_num: str | None = None
        art_rubric: str | None = None
        art_ctx: dict[str, Any] = {}
        cursor: dict[str, Any] = {"marker": "B", "celex": "", "action": None}
        # (grid-container element, cursor state at time of encounter)
        pending: list[tuple[Tag, dict[str, Any]]] = []

        def _flush() -> None:
            if art_num is None:
                return

            structural_path = f"art_{art_num}"
            art_id = f"art_{art_num}"
            full_ctx = {
                **art_ctx,
                "article_number": art_num,
                "article_rubric": art_rubric,
            }

            if article_filter is not None and art_num != article_filter:
                return

            def_count = 0
            for el, el_cursor in pending:
                result = self._match_definition(el, el_cursor, doc_div)
                if result is None:
                    continue

                def_count += 1
                list_path = result["list_path"] or str(def_count)
                records.append({
                    "record_type": "definition",
                    "term": result["term"],
                    "term_normalized": result["term"].lower(),
                    "definition": result["definition"],
                    "lang": self.lang,
                    "approved": False,
                    "source_ref": {
                        "celex_id": self.celex_id,
                        "structural_path": structural_path,
                        "list_path": list_path,
                        "url": self._article_url(art_id),
                        "layout": "flatgrid",
                    },
                    "amendment": result["amendment"],
                    "context": full_ctx,
                    "sub_items": result["sub_items"],
                    "footnote_refs": result["footnote_refs"],
                })

            records.append({
                "record_type": "article_metadata",
                "lang": self.lang,
                "source_ref": {
                    "celex_id": self.celex_id,
                    "structural_path": structural_path,
                    "layout": "flatgrid",
                },
                "article_number": art_num,
                "article_rubric": art_rubric,
                "article_rubric_source": "article" if art_rubric else None,
                "context": full_ctx,
                "definition_count": def_count,
            })

        for child in doc_div.children:
            if not isinstance(child, Tag):
                continue
            classes = set(child.get("class") or [])

            if "title-division-1" in classes:
                ctx_state["title_label"] = _get_text(child) or None
                ctx_state["title_rubric"] = None
            elif "stitle-division-1" in classes:
                ctx_state["title_rubric"] = _get_text(child) or None
            elif "title-division-2" in classes:
                ctx_state["chapter_label"] = _get_text(child) or None
                ctx_state["chapter_rubric"] = None
            elif "stitle-division-2" in classes:
                ctx_state["chapter_rubric"] = _get_text(child) or None
            elif "title-article-norm" in classes and child.name == "p":
                _flush()
                new_num = _extract_article_number_from_text(_get_text(child))
                if new_num is not None:
                    art_num = new_num
                    art_rubric = None
                    art_ctx = dict(ctx_state)
                    cursor = {"marker": "B", "celex": "", "action": None}
                    pending = []
            elif "stitle-article-norm" in classes and child.name == "p":
                art_rubric = _get_text(child) or None
            elif "modref" in classes and child.name == "p":
                cursor = _parse_amendment_marker(child)
                mk = cursor.get("marker", "B")
                if mk:
                    amendments_detected.add(mk)
            elif "grid-container" in classes and art_num is not None:
                pending.append((child, dict(cursor)))

        _flush()
        return records

    def _parse_table_row(
        self,
        table: Tag,
        cursor: dict[str, Any],
        amendments_detected: set[str],
    ) -> dict | None:
        """Parse one tablelayout <table> element into a definition result dict."""
        # Real EUR-Lex LT HTML wraps rows in <tbody> and puts dlist-term/definition
        # classes on <p> elements inside <td>, not on <td> itself.  Descend through
        # an optional <tbody> and use positional td access so both the real structure
        # and simplified fixtures work.
        row_container = table.find("tbody") or table
        row = row_container.find("tr")
        if not row:
            return None
        tds = row.find_all("td", recursive=False)
        if len(tds) < 2:
            return None
        term_td, def_td = tds[0], tds[1]

        list_path = _normalize_list_marker(_get_text(term_td))

        # Consume modrefs that appear as direct children of the definition cell
        for ch in list(def_td.children):
            if isinstance(ch, Tag) and ch.name == "p" and "modref" in (ch.get("class") or []):
                cursor = _parse_amendment_marker(ch)
                mk = cursor.get("marker", "B")
                if mk:
                    amendments_detected.add(mk)

        # Shape B: p.normal holds the term (with trailing dash)
        p_normal = def_td.find("p", class_="normal")
        if p_normal:
            term_text = _get_text(p_normal)
            term_text = re.sub(r"\s*[–—].*", "", term_text, flags=re.DOTALL).strip()
            term_text = term_text.strip("„“”‘’\"'")
            p_norm = def_td.find("p", class_="norm")
            chapeau = _strip_definition_text(_get_text(p_norm)) if p_norm else ""
            sub_items = _collect_sub_items(def_td, dict(cursor))
            return {
                "term": term_text,
                "definition": chapeau,
                "amendment": dict(cursor),
                "sub_items": sub_items,
                "list_path": list_path,
            }

        # Shape A / C: split on en-dash (C strips corrigendum markers first)
        raw = _normalize_nbsp(def_td.get_text(" ", strip=True))
        raw = _strip_corrigendum_markers(raw)
        idx = raw.find("–")
        if idx == -1:
            idx = raw.find("—")
        if idx == -1:
            return None
        term = raw[:idx].strip().strip("„“”‘’\"'")
        definition = _strip_definition_text(raw[idx + 1:])
        if not term:
            return None
        return {
            "term": term,
            "definition": definition,
            "amendment": dict(cursor),
            "sub_items": [],
            "list_path": list_path,
        }

    def _extract_tablelayout(
        self,
        doc_div: Tag,
        article_filter: str | None,
        amendments_detected: set[str],
    ) -> list[dict]:
        """Extract definitions from tablelayout HTML (LT and similar translations).

        Phase 1: single forward pass over doc_div.children to collect structural
        context (division headers) and build an ordered list of article scopes —
        each scope is (title_el, art_num, art_ctx_snapshot, next_title_el).

        Phase 2: for each article scope, walk title_el.next_siblings up to
        next_title_el.  Direct p.modref siblings update the amendment cursor.
        Tables are collected both at the direct-sibling level AND by searching
        inside any non-table sibling containers (handles cases where tables are
        wrapped in an intermediate div in the real LT HTML).
        """
        records: list[dict] = []

        # ── Phase 1: enumerate article scopes ──────────────────────────────
        ctx_state: dict[str, Any] = {
            "title_label": None,
            "title_rubric": None,
            "chapter_label": None,
            "chapter_rubric": None,
            "section_label": None,
            "section_rubric": None,
        }

        # (title_el, art_num_or_None, ctx_snapshot_at_title)
        title_entries: list[tuple[Tag, str | None, dict[str, Any]]] = []

        for child in doc_div.children:
            if not isinstance(child, Tag):
                continue
            classes = set(child.get("class") or [])

            if "title-division-1" in classes:
                ctx_state["title_label"] = _get_text(child) or None
                ctx_state["title_rubric"] = None
            elif "stitle-division-1" in classes:
                ctx_state["title_rubric"] = _get_text(child) or None
            elif "title-division-2" in classes:
                ctx_state["chapter_label"] = _get_text(child) or None
                ctx_state["chapter_rubric"] = None
            elif "stitle-division-2" in classes:
                ctx_state["chapter_rubric"] = _get_text(child) or None
            elif "title-article-norm" in classes and child.name == "p":
                raw = _get_text(child)
                if "PRIEDAS" in raw.upper():
                    title_entries.append((child, None, {}))
                else:
                    num = _extract_article_number_from_text(raw)
                    title_entries.append((child, num, dict(ctx_state)))

        # ── Phase 2: process each article scope ────────────────────────────
        for entry_idx, (title_el, art_num, art_ctx) in enumerate(title_entries):
            if art_num is None:
                continue

            # Sentinel: stop at the next article title element
            next_title: Tag | None = None
            for future_el, _, _ in title_entries[entry_idx + 1:]:
                next_title = future_el
                break

            art_rubric: str | None = None
            cursor: dict[str, Any] = {"marker": "B", "celex": "", "action": None}
            pending: list[tuple[Tag, dict[str, Any]]] = []

            for sib in title_el.next_siblings:
                if not isinstance(sib, Tag):
                    continue
                if next_title is not None and sib is next_title:
                    break
                classes = set(sib.get("class") or [])

                if "stitle-article-norm" in classes and sib.name == "p":
                    art_rubric = _get_text(sib) or None
                elif "modref" in classes and sib.name == "p":
                    cursor = _parse_amendment_marker(sib)
                    mk = cursor.get("marker", "B")
                    if mk:
                        amendments_detected.add(mk)
                elif sib.name == "table":
                    pending.append((sib, dict(cursor)))
                else:
                    # Tables may be nested inside an intermediate container in
                    # some EUR-Lex language versions (the direct-child check
                    # above would miss them).
                    for nested in sib.find_all("table"):
                        pending.append((nested, dict(cursor)))

            # Apply article filter (after sibling walk so amendments are detected)
            if article_filter is not None and art_num != article_filter:
                continue

            structural_path = f"art_{art_num}"
            art_id = f"art_{art_num}"
            full_ctx = {
                **art_ctx,
                "article_number": art_num,
                "article_rubric": art_rubric,
            }

            def_count = 0
            for table, tbl_cursor in pending:
                result = self._parse_table_row(table, dict(tbl_cursor), amendments_detected)
                if result is None:
                    continue
                def_count += 1
                lp = result["list_path"] or str(def_count)
                records.append({
                    "record_type": "definition",
                    "term": result["term"],
                    "term_normalized": result["term"].lower(),
                    "definition": result["definition"],
                    "lang": self.lang,
                    "approved": False,
                    "source_ref": {
                        "celex_id": self.celex_id,
                        "structural_path": structural_path,
                        "list_path": lp,
                        "url": self._article_url(art_id),
                        "layout": "tablelayout",
                    },
                    "amendment": result["amendment"],
                    "context": full_ctx,
                    "sub_items": result["sub_items"],
                    "footnote_refs": [],
                })

            records.append({
                "record_type": "article_metadata",
                "lang": self.lang,
                "source_ref": {
                    "celex_id": self.celex_id,
                    "structural_path": structural_path,
                    "layout": "tablelayout",
                },
                "article_number": art_num,
                "article_rubric": art_rubric,
                "article_rubric_source": "article" if art_rubric else None,
                "context": full_ctx,
                "definition_count": def_count,
            })

        return records

    def extract(
        self, soup: BeautifulSoup, article_filter: str | None = None
    ) -> list[dict]:
        """Run the full extraction pipeline.

        Layout is detected automatically via detect_layout():
          divlayout   — eli-subdivision wrappers present (EN and many languages)
          tablelayout — table rows with dlist-term/dlist-definition cells (LT etc.)

        Returns list of record dicts (definition, article_metadata, footnote).
        """
        doc_div = soup.find("div", id="docHtml")
        if doc_div is None:
            self._warnings.append("docHtml div not found; scanning full document")
            doc_div = soup

        amendments_detected: set[str] = set()

        try:
            layout = detect_layout(soup)
        except UnknownLayoutError:
            layout = "divlayout"
            self._warnings.append("Layout not detected; falling back to divlayout")

        if layout == "tablelayout":
            records = self._extract_tablelayout(doc_div, article_filter, amendments_detected)
        else:
            records = self._extract_variant_a(doc_div, article_filter, amendments_detected)

        footnotes = self._collect_footnotes(soup)
        records.extend(footnotes)

        self._amendments_detected = amendments_detected
        return records

    def list_articles(self, soup: BeautifulSoup) -> list[tuple[str, str | None, str | None]]:
        """Return [(art_id, rubric, rubric_source), ...] for non-annex, non-recital articles.

        Result is in document order.  Annexes (id^='anx_') and recitals
        (id^='rct_') are excluded.  rubric is None when absent; rubric_source is
        'article', 'chapter', or None.  Used by --list-articles and --auto-article.
        """
        doc_div = soup.find("div", id="docHtml") or soup
        try:
            layout = detect_layout(soup)
        except UnknownLayoutError:
            layout = "divlayout"

        result: list[tuple[str, str | None]] = []

        if layout == "divlayout":
            contexts = self._collect_structural_context(doc_div)
            for art_div in doc_div.find_all("div", id=ART_ID_PATTERN):
                art_id = art_div.get("id", "")
                skip = False
                for anc in art_div.parents:
                    if not isinstance(anc, Tag):
                        continue
                    anc_id = anc.get("id", "") or ""
                    if anc_id.startswith("anx_") or anc_id.startswith("rct_"):
                        skip = True
                        break
                if skip:
                    continue
                ctx = contexts.get(art_id, {})
                result.append((art_id, ctx.get("article_rubric"), ctx.get("article_rubric_source")))

        else:  # tablelayout
            for child in doc_div.children:
                if not isinstance(child, Tag):
                    continue
                classes = set(child.get("class") or [])
                if "title-article-norm" not in classes or child.name != "p":
                    continue
                raw = _get_text(child)
                if "PRIEDAS" in raw.upper():
                    continue
                num = _extract_article_number_from_text(raw)
                if num is None:
                    continue
                art_id = f"art_{num}"
                rubric: str | None = None
                for sib in child.next_siblings:
                    if not isinstance(sib, Tag):
                        continue
                    sib_classes = set(sib.get("class") or [])
                    if "stitle-article-norm" in sib_classes and sib.name == "p":
                        rubric = _get_text(sib) or None
                        break
                    if "title-article-norm" in sib_classes:
                        break
                source = "article" if rubric else None
                result.append((art_id, rubric, source))

        return result

    @property
    def warnings(self) -> list[str]:
        return self._warnings


# ---------------------------------------------------------------------------
# Article discovery helpers
# ---------------------------------------------------------------------------


def _find_definitions_article(
    articles: list[tuple[str, str | None, str | None]],
    lang: str,
    keyword_set: str = "definitions",
) -> str | None:
    """Return the art_id of the first article whose rubric matches keyword_set.

    Matching is case-insensitive and diacritic-insensitive (substring match).
    For keyword_set='definitions', uses DEFINITION_RUBRICS[lang] as the keyword
    list; otherwise treats keyword_set itself as the single keyword.

    Article-level rubrics (source='article') take priority.  If no article-level
    match is found, chapter-level rubrics (source='chapter') are checked.  When
    multiple articles share a matching chapter rubric, a warning is printed to
    stderr and the first matching article is returned.

    Returns None if no article matches.
    """
    if keyword_set == "definitions":
        keywords = DEFINITION_RUBRICS.get(lang, ["definition", "definitions"])
    else:
        keywords = [keyword_set]

    chapter_matches: list[tuple[str, str]] = []  # (art_id, rubric_text)

    for art_id, rubric, source in articles:
        if rubric is None:
            continue
        rubric_norm = _strip_diacritics(rubric.lower())
        if not any(_strip_diacritics(kw.lower()) in rubric_norm for kw in keywords):
            continue
        if source != "chapter":
            return art_id  # article-level match wins immediately
        chapter_matches.append((art_id, rubric))

    if not chapter_matches:
        return None

    if len(chapter_matches) > 1:
        rubric_text = chapter_matches[0][1]
        matched_ids = [m[0] for m in chapter_matches]
        print(
            f"Warning: --auto-article={keyword_set} matched {len(chapter_matches)} articles via "
            f'chapter rubric "{rubric_text}": {", ".join(matched_ids)}. '
            f"Selecting {matched_ids[0]}. Use --article N to pick a different one.",
            file=sys.stderr,
        )

    return chapter_matches[0][0]


# ---------------------------------------------------------------------------
# EUR-Lex record helpers (used by domain_db_writer and review_cli)
# ---------------------------------------------------------------------------


def is_eurlex_definition(rec: dict) -> bool:
    """Return True if rec is an EUR-Lex definition record."""
    return rec.get("record_type") == "definition" and "source_ref" in rec and "celex_id" in rec.get("source_ref", {})


def map_eurlex_to_writer_fields(rec: dict) -> dict:
    """Map an EUR-Lex definition record to domain_db_writer-compatible fields."""
    src = rec["source_ref"]
    celex_id = src["celex_id"]
    structural_path = src.get("structural_path", "")
    list_path = src.get("list_path", "")

    first_seen_source = f"{celex_id}#{structural_path}.{list_path}"
    first_seen_date = _parse_celex_date(celex_id) or ""

    return {
        "term_raw": rec["term"],
        "term_normalized": rec["term_normalized"],
        "definition_raw": rec["definition"],
        "lang": rec["lang"],
        "source_file": celex_id,
        "clause_ref": list_path,
        "first_seen_source": first_seen_source,
        "first_seen_date": first_seen_date,
        "approved": rec.get("approved", False),
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _record_key(rec: dict) -> tuple[str, str, str, str]:
    """Return a deduplication key for any EUR-Lex record type."""
    rt = rec.get("record_type", "")
    lang = rec.get("lang", "")
    src = rec.get("source_ref", {})
    celex_id = src.get("celex_id", "")

    if rt == "definition":
        return (celex_id, src.get("structural_path", ""), src.get("list_path", ""), lang)
    if rt == "article_metadata":
        return (celex_id, src.get("structural_path", ""), "article_metadata", lang)
    if rt == "footnote":
        return (celex_id, src.get("footnote_id", ""), "footnote", lang)
    return (rt, lang, "", celex_id)


def _load_existing_keys(output_path: Path) -> set[tuple[str, str, str, str]]:
    """Load deduplication keys from an existing EUR-Lex JSONL output file."""
    keys: set[tuple[str, str, str, str]] = set()
    if not output_path.exists():
        return keys
    with output_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(_record_key(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


def write_records(
    records: list[dict],
    output_path: Path,
    *,
    append: bool = False,
) -> int:
    """Write EUR-Lex records to output_path as JSONL, optionally deduplicating.

    In append mode, records whose (celex_id, structural_path, list_path, lang) key
    already exists in the file are skipped.  Returns the number of records written.
    """
    existing_keys = _load_existing_keys(output_path) if append else set()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written = 0
    with output_path.open(mode, encoding="utf-8") as fh:
        for rec in records:
            if _record_key(rec) in existing_keys:
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for extract_eurlex_definitions."""
    parser = argparse.ArgumentParser(
        description="Extract definitions from a EUR-Lex consolidated HTML file."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to HTML file")
    parser.add_argument("--celex", required=True, help="CELEX identifier (e.g. 02013R0952-20221212)")
    parser.add_argument("--lang", required=True, help="Language code (e.g. en)")
    parser.add_argument(
        "--output", required=False, default=None, type=Path,
        help="Path to output .jsonl file (not required with --list-articles)",
    )
    parser.add_argument("--article", default=None, help="Extract only from this article number")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing output file instead of overwriting; "
             "duplicate records (same celex_id + structural_path + list_path + lang) are skipped",
    )
    parser.add_argument(
        "--list-articles",
        dest="list_articles",
        action="store_true",
        help="List article IDs and rubrics in document order then exit (dry-run; --output not required)",
    )
    parser.add_argument(
        "--auto-article",
        dest="auto_article",
        default=None,
        metavar="KEYWORD_SET",
        help=(
            "Auto-select the article whose rubric matches KEYWORD_SET. "
            "Use 'definitions' to pick the Definitions article for --lang."
        ),
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    extractor = EurLexExtractor(celex_id=args.celex, lang=args.lang)
    soup = extractor.parse_html(args.input)

    # --list-articles: dry-run — print article IDs + rubrics and exit
    if args.list_articles:
        for art_id, rubric, source in extractor.list_articles(soup):
            if source == "chapter":
                print(f"{art_id}\t← {rubric} (chapter)")
            else:
                print(f"{art_id}\t{rubric or '(no rubric)'}")
        return

    # --auto-article: resolve the article filter from the document's rubrics
    article_filter = args.article
    if args.auto_article is not None:
        articles = extractor.list_articles(soup)
        matched = _find_definitions_article(articles, args.lang, args.auto_article)
        if matched is None:
            print(
                f"No '{args.auto_article}' article found. Articles present:",
                file=sys.stderr,
            )
            for aid, rub, src in articles:
                if src == "chapter":
                    print(f"  {aid}\t← {rub} (chapter)", file=sys.stderr)
                else:
                    print(f"  {aid}\t{rub or '(no rubric)'}", file=sys.stderr)
            sys.exit(1)
        article_filter = matched[4:]  # "art_3" → "3"
        rub = next((r for a, r, s in articles if a == matched), None)
        print(f"Auto-selected: {matched}  {rub or ''}")

    if args.output is None:
        print(
            "Error: --output is required for extraction. "
            "Use --list-articles for a dry-run with no output.",
            file=sys.stderr,
        )
        sys.exit(1)

    records = extractor.extract(soup, article_filter=article_filter)

    n_definitions = sum(1 for r in records if r["record_type"] == "definition")
    n_footnotes = sum(1 for r in records if r["record_type"] == "footnote")
    n_metadata = sum(1 for r in records if r["record_type"] == "article_metadata")
    n_amendments = len(getattr(extractor, "_amendments_detected", set()))

    written = write_records(records, args.output, append=args.append)
    skipped = len(records) - written

    print(f"Articles scanned    : {n_metadata}")
    print(f"Definitions found   : {n_definitions}")
    print(f"Footnotes collected : {n_footnotes}")
    print(f"Amendments detected : {n_amendments}")
    print(f"Warnings            : {len(extractor.warnings)}")
    for w in extractor.warnings:
        print(f"  WARNING: {w}")
    print(f"Records written     : {written}")
    if args.append:
        print(f"Duplicates skipped  : {skipped}")
    print(f"Output written to   : {args.output}")

    # Sanity warning: 0 definitions with no article filter is a strong signal
    # that the wrong document was supplied (e.g. an amending act instead of
    # the consolidated text).
    if n_definitions == 0 and article_filter is None:
        print(
            "\nNote: 0 definitions extracted. This may indicate:",
            file=sys.stderr,
        )
        print(
            "  - The document is an amending or implementing act with no\n"
            "    Definitions article.",
            file=sys.stderr,
        )
        print(
            "  - The Definitions article uses an unrecognised layout.",
            file=sys.stderr,
        )
        print(
            "  - --article filtered out the article that contains definitions.",
            file=sys.stderr,
        )
        print("\nArticles present in this document:", file=sys.stderr)
        for aid, rub, src in extractor.list_articles(soup):
            if src == "chapter":
                print(f"  {aid}\t← {rub} (chapter)", file=sys.stderr)
            else:
                print(f"  {aid}\t{rub or '(no rubric)'}", file=sys.stderr)
        print(
            "\nUse --list-articles to inspect the document, or "
            "--auto-article=definitions to auto-select.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
