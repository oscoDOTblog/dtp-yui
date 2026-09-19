"""Convert job-description HTML into readable markdown (stdlib only)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

_HTML_HINT_RE = re.compile(
    r"</?(?:p|div|ul|ol|li|h[1-6]|a|br|strong|em|b|i|span|section|article)\b",
    flags=re.I,
)

_BLOCK_CLOSE = frozenset({"p", "div", "section", "article", "tr"})
_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


def looks_like_html(text: str | None) -> bool:
    """True when text appears to contain HTML markup worth converting."""
    if not text or "<" not in text:
        return False
    return bool(_HTML_HINT_RE.search(text))


class _HTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._list_stack: list[str] = []  # "ul" | "ol"
        self._ol_counters: list[int] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._in_link = False
        self._pending_li_prefix: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag == "br":
            self._emit("\n")
            return

        if tag in _HEADINGS:
            self._ensure_blank_line()
            self._emit(f"{_HEADINGS[tag]} ")
            return

        if tag == "p":
            self._ensure_blank_line()
            return

        if tag in ("div", "section", "article"):
            self._ensure_newline()
            return

        if tag in ("ul", "ol"):
            self._ensure_blank_line()
            self._list_stack.append(tag)
            self._ol_counters.append(0 if tag == "ol" else -1)
            return

        if tag == "li":
            self._ensure_newline()
            depth = max(len(self._list_stack) - 1, 0)
            indent = "  " * depth
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ol_counters[-1] = max(self._ol_counters[-1], 0) + 1
                self._pending_li_prefix = f"{indent}{self._ol_counters[-1]}. "
            else:
                self._pending_li_prefix = f"{indent}- "
            return

        if tag in ("strong", "b"):
            self._emit("**")
            return

        if tag in ("em", "i"):
            self._emit("*")
            return

        if tag == "a":
            href = (attr_map.get("href") or "").strip()
            self._in_link = True
            self._link_href = href
            self._link_text = []
            return

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return

        if tag in _HEADINGS:
            self._emit("\n\n")
            return

        if tag in _BLOCK_CLOSE:
            self._emit("\n\n")
            return

        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if self._ol_counters:
                self._ol_counters.pop()
            self._emit("\n\n")
            return

        if tag == "li":
            self._emit("\n")
            return

        if tag in ("strong", "b"):
            self._emit("**")
            return

        if tag in ("em", "i"):
            self._emit("*")
            return

        if tag == "a" and self._in_link:
            text = "".join(self._link_text).strip()
            href = (self._link_href or "").strip()
            self._in_link = False
            self._link_href = None
            self._link_text = []
            if text and href:
                self._emit(f"[{text}]({href})")
            elif text:
                self._emit(text)
            elif href:
                self._emit(href)
            return

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        if self._in_link:
            self._link_text.append(data)
            return
        # Ignore inter-tag whitespace (e.g. newlines between </li><li>)
        if not data.strip():
            return
        if self._pending_li_prefix is not None:
            stripped = data.lstrip()
            if stripped:
                self._emit(self._pending_li_prefix)
                self._pending_li_prefix = None
                self._emit(stripped)
            return
        self._emit(data)

    def _emit(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)

    def _ensure_newline(self) -> None:
        joined = "".join(self._chunks)
        if not joined:
            return
        if not joined.endswith("\n"):
            self._chunks.append("\n")

    def _ensure_blank_line(self) -> None:
        joined = "".join(self._chunks)
        if not joined:
            return
        if joined.endswith("\n\n"):
            return
        if joined.endswith("\n"):
            self._chunks.append("\n")
        else:
            self._chunks.append("\n\n")

    def markdown(self) -> str:
        # Flush unfinished link
        if self._in_link:
            text = "".join(self._link_text).strip()
            href = (self._link_href or "").strip()
            self._in_link = False
            if text and href:
                self._chunks.append(f"[{text}]({href})")
            elif text:
                self._chunks.append(text)

        joined = "".join(self._chunks)
        joined = html.unescape(joined)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        joined = re.sub(r"[ \t]{2,}", " ", joined)
        # Trim trailing space on each line
        joined = "\n".join(line.rstrip() for line in joined.splitlines())
        return joined.strip()


def html_to_markdown(raw_html: str | None) -> str:
    """Convert HTML job description to markdown. Empty input -> empty string."""
    if not raw_html:
        return ""
    if not looks_like_html(raw_html):
        return raw_html.strip()

    parser = _HTMLToMarkdown()
    try:
        parser.feed(raw_html)
        parser.close()
        return parser.markdown()
    except Exception:
        # Fallback: crude tag strip preserving some newlines
        text = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)
        text = re.sub(r"(?i)</(?:p|div|h[1-6]|li|tr)>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _plain_text_fallback(raw_html: str) -> str:
    """Lightweight HTML → plain text (avoids importing greenhouse_source)."""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|h[1-6]|li|tr)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def description_fields_from_html_or_text(body: str) -> dict[str, Any]:
    """
    Split an intake body into plain descriptionRaw + optional descriptionMarkdown.

    When body looks like HTML: markdown for display, plain text for matching.
    Otherwise: plain text only (descriptionMarkdown is None).
    """
    body = (body or "").strip()
    if not body:
        return {"descriptionRaw": "", "descriptionMarkdown": None}

    if looks_like_html(body):
        # Prefer greenhouse HTMLParser strip when available (same process).
        try:
            from .greenhouse_source import html_to_text as _gh_html_to_text

            plain = _gh_html_to_text(body)
        except Exception:
            plain = _plain_text_fallback(body)
        return {
            "descriptionRaw": plain,
            "descriptionMarkdown": html_to_markdown(body) or None,
        }

    return {"descriptionRaw": body, "descriptionMarkdown": None}
