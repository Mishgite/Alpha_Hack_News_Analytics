"""Article body extraction and language detection shared by all news adapters.

RSS/API descriptions are usually summaries, not full articles. This module tries
its best to retrieve the original HTML page and extract the article body while
keeping the original summary as a safe fallback when a publisher blocks access.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; AlphaHackNewsAnalytics/1.0; "
    "+https://github.com/Mishgite/Alpha_Hack_News_Analytics)"
)
_MIN_DETECT_CHARS = 80
_LANGDETECT_LOCK = threading.Lock()

try:  # optional fallback remains available for minimal installations/tests
    from langdetect import DetectorFactory, detect_langs

    DetectorFactory.seed = 0
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    detect_langs = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - project requirements install beautifulsoup4
    BeautifulSoup = None


def _clean_space(value: Any) -> str:
    """Normalize whitespace without destroying paragraph boundaries."""
    text = unescape(str(value or "")).replace("\r", "\n")
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in text.split("\n")]
    result: list[str] = []
    previous_blank = False
    for line in lines:
        if line:
            result.append(line)
            previous_blank = False
        elif result and not previous_blank:
            result.append("")
            previous_blank = True
    return "\n".join(result).strip()


def clean_article_text(value: Any) -> str:
    """Convert a snippet or HTML body to readable plain text."""
    raw = str(value or "")
    if BeautifulSoup is not None and "<" in raw and ">" in raw:
        try:
            soup = BeautifulSoup(raw, "html.parser")
            for node in soup.find_all(("script", "style", "noscript")):
                node.decompose()
            raw = soup.get_text("\n", strip=True)
        except Exception:
            raw = re.sub(r"<[^>]+>", " ", raw)
    else:
        raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"<[^>]+>", " ", raw)
    return _clean_space(raw)


def _normalize_language(value: str | None) -> str:
    if not value:
        return "und"
    lang = value.strip().lower().replace("_", "-").split("-")[0]
    aliases = {"zh": "zh", "jp": "ja", "ua": "uk", "iw": "he", "in": "id"}
    lang = aliases.get(lang, lang)
    # Only accept syntactically plausible BCP-47 primary subtags.
    return lang if re.fullmatch(r"[a-z]{2,3}", lang) else "und"


def _fallback_language_detection(text: str) -> str:
    """Reasonable offline fallback; full detection is provided by langdetect."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "und"
    counts = {
        "cyrillic": sum("\u0400" <= c <= "\u052f" for c in letters),
        "latin": sum(("a" <= c.lower() <= "z") or ("\u00c0" <= c.lower() <= "\u024f") for c in letters),
        "arabic": sum("\u0600" <= c <= "\u06ff" for c in letters),
        "greek": sum("\u0370" <= c <= "\u03ff" for c in letters),
        "hebrew": sum("\u0590" <= c <= "\u05ff" for c in letters),
        "hangul": sum("\uac00" <= c <= "\ud7af" for c in letters),
        "hiragana_katakana": sum("\u3040" <= c <= "\u30ff" for c in letters),
        "han": sum("\u4e00" <= c <= "\u9fff" for c in letters),
    }
    script, amount = max(counts.items(), key=lambda pair: pair[1])
    if amount / len(letters) >= 0.55 and script != "latin":
        return {
            "arabic": "ar",
            "greek": "el",
            "hebrew": "he",
            "hangul": "ko",
            "hiragana_katakana": "ja",
            "han": "zh",
        }.get(script, "und") if script != "cyrillic" else _detect_cyrillic_language(text)

    lower = f" {text.lower()} "
    word_markers = {
        "en": (" the ", " and ", " is ", " are ", " was ", " with ", " from ", " that ", " for "),
        "es": (" el ", " la ", " los ", " las ", " que ", " de ", " y ", " para ", " una "),
        "fr": (" le ", " la ", " les ", " des ", " une ", " est ", " avec ", " pour ", " dans "),
        "de": (" der ", " die ", " das ", " und ", " ist ", " mit ", " von ", " für ", " ein "),
        "it": (" il ", " lo ", " gli ", " che ", " della ", " per ", " con ", " una ", " è "),
        "pt": (" o ", " os ", " as ", " que ", " uma ", " um ", " com ", " para ", " não "),
        "nl": (" de ", " het ", " een ", " van ", " en ", " met ", " voor ", " zijn "),
        "pl": (" i ", " oraz ", " jest ", " nie ", " dla ", " się ", " w ", " na "),
        "tr": (" ve ", " bir ", " için ", " ile ", " bu ", " olan ", " olarak "),
    }
    scores = {lang: sum(lower.count(marker) for marker in markers) for lang, markers in word_markers.items()}
    best = max(scores, key=scores.get)
    if scores[best] >= 2 and scores[best] > sorted(scores.values())[-2]:
        return best
    return "und"


def _detect_cyrillic_language(text: str) -> str:
    lower = text.lower()
    # Russian articles often mention Ukraine, so one Ukrainian-specific character
    # in a place name is not enough to label the whole article as Ukrainian.
    if "ґ" in lower or lower.count("ї") >= 2:
        return "uk"
    uk_markers = (" що ", " це ", " які ", " яка ", " також ", " буде ", " від ", " повідомив ", " заявив ", " україни ")
    ru_markers = (" что ", " это ", " который ", " которая ", " также ", " будет ", " от ", " сообщил ", " заявил ", " украины ")
    padded = f" {re.sub(r'\s+', ' ', lower)} "
    uk_score = sum(padded.count(marker) for marker in uk_markers)
    ru_score = sum(padded.count(marker) for marker in ru_markers)
    if uk_score >= 2 and uk_score > ru_score:
        return "uk"
    if any(word in padded for word in (" је ", " шта ", " иако ", " србија ")):
        return "sr"
    return "ru"


def detect_language(text: Any, *, fallback: str = "und", min_chars: int = _MIN_DETECT_CHARS) -> str:
    """Return an ISO language code based on the article body, not its title.

    Short snippets often make language detectors guess incorrectly; for those,
    this function prefers an explicit metadata/fallback value or ``und``.
    """
    normalized = _clean_space(text)
    letters = sum(character.isalpha() for character in normalized)
    if len(normalized) < min_chars or letters < max(35, min_chars // 2):
        return _normalize_language(fallback)

    if detect_langs is not None:
        try:
            with _LANGDETECT_LOCK:
                candidates = detect_langs(normalized[:12000])
            if candidates:
                top = candidates[0]
                code = _normalize_language(top.lang)
                probability = float(top.prob)
                if code != "und" and probability >= 0.65:
                    return code
        except Exception:
            logger.debug("Language detection failed; using offline fallback", exc_info=True)

    guessed = _fallback_language_detection(normalized)
    return guessed if guessed != "und" else _normalize_language(fallback)


def _html_metadata(html: str) -> tuple[str, str]:
    """Return (language hint, canonical URL) without using meta description as body."""
    if BeautifulSoup is None:
        lang_match = re.search(r"<html[^>]+lang=[\"']([^\"']+)", html, flags=re.I)
        canonical_match = re.search(
            r"<link[^>]+rel=[\"'][^\"']*canonical[^\"']*[\"'][^>]+href=[\"']([^\"']+)",
            html,
            flags=re.I,
        )
        return _normalize_language(lang_match.group(1)) if lang_match else "und", canonical_match.group(1) if canonical_match else ""
    soup = BeautifulSoup(html, "html.parser")
    language = soup.html.get("lang", "") if soup.html else ""
    if not language:
        for attrs in (
            {"http-equiv": re.compile("content-language", re.I)},
            {"name": re.compile("language", re.I)},
            {"property": "og:locale"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                language = tag["content"]
                break
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    return _normalize_language(language), str(canonical.get("href", "")) if canonical else ""


def _extract_with_beautifulsoup(html: str) -> str:
    """Extract an article body with semantic tags and common publisher selectors."""
    if BeautifulSoup is None:
        # A conservative no-dependency fallback. It deliberately avoids using
        # meta description/title, because those are commonly just summaries.
        cleaned = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form|noscript)[^>]*>.*?</\1>", " ", html)
        paragraphs = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", cleaned)
        texts = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p)).strip() for p in paragraphs]
        return _clean_space("\n\n".join(unescape(p) for p in texts if len(p) >= 35))

    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(("script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "iframe", "button", "template")):
        node.decompose()
    # Remove common share/recommendation/comment blocks before selecting article text.
    for node in soup.select(
        '[class*="related"], [class*="recommend"], [class*="social"], '
        '[class*="comment"], [class*="newsletter"], [class*="subscribe"], '
        '[id*="related"], [id*="comment"], [aria-label*="navigation" i]'
    ):
        node.decompose()

    selectors = (
        '[itemprop="articleBody"]',
        "article",
        "main",
        '[role="main"]',
        ".article-body",
        ".article__body",
        ".article-content",
        ".entry-content",
        ".post-content",
        ".story-body",
        ".news-article__content",
        "#article-body",
    )
    candidates: list[tuple[int, str]] = []
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            paragraphs = [
                _clean_space(p.get_text(" ", strip=True))
                for p in node.find_all(("p", "h2", "h3", "blockquote"))
            ]
            paragraphs = [p for p in paragraphs if len(p) >= 35]
            text = _clean_space("\n\n".join(dict.fromkeys(paragraphs)))
            if text:
                # Favor substantial text in an article-specific semantic element.
                specificity = 2 if selector in ( '[itemprop="articleBody"]', ".article-body", ".article__body", ".entry-content", ".post-content", "#article-body") else 1
                candidates.append((len(text) + specificity * 80, text))
    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        best = candidates[0][1]
        if len(best) >= 120:
            return best

    # Last resort: paragraph clusters across the page, filtered for short UI text.
    paragraphs = []
    seen_text: set[str] = set()
    for paragraph in soup.find_all("p"):
        text = _clean_space(paragraph.get_text(" ", strip=True))
        if len(text) < 50 or text.lower() in seen_text:
            continue
        seen_text.add(text.lower())
        paragraphs.append(text)
    result = _clean_space("\n\n".join(paragraphs))
    return result if len(result) >= 120 else ""


def extract_article_text(html: str, *, url: str = "") -> tuple[str, str]:
    """Extract article body and an HTML language hint from already-downloaded HTML."""
    if not html or not html.strip():
        return "", "und"
    lang_hint, canonical = _html_metadata(html)
    final_url = canonical or url

    extracted = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            url=final_url or None,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_precision=False,
            deduplicate=True,
            output_format="txt",
        ) or ""
    except ImportError:
        pass
    except Exception:
        logger.debug("trafilatura failed for %s", url, exc_info=True)

    extracted = _clean_space(extracted)
    if len(extracted) < 120:
        fallback = _extract_with_beautifulsoup(html)
        if len(fallback) > len(extracted):
            extracted = fallback
    if len(extracted) < 120:
        return "", lang_hint
    return extracted, lang_hint


def _allowed_article_url(url: str, source: str = "") -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "reddit.com" or host.endswith(".reddit.com"):
        return False  # Reddit's selftext is already provided by its JSON API.
    if host in {"news.ycombinator.com", "offstream.news"} and source in {"hackernews", "offstream"}:
        return False
    return True


def fetch_article_text(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 8.0,
    source: str = "",
) -> tuple[str, str]:
    """Download a publisher page and return (full-ish article body, language hint)."""
    if not _allowed_article_url(url, source):
        return "", "und"

    def _get(using_client: httpx.Client) -> tuple[str, str]:
        response = using_client.get(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        html = response.text
        if content_type and "html" not in content_type and "xhtml" not in content_type:
            # Some sites mislabel HTML, so still permit text containing markup.
            if "<html" not in html[:1000].lower() and "<article" not in html[:5000].lower():
                return "", "und"
        return extract_article_text(html, url=str(response.url or url))

    if client is not None:
        try:
            return _get(client)
        except Exception as exc:
            logger.info("Could not fetch full article %s (%s)", url, type(exc).__name__)
            return "", "und"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as own_client:
            return _get(own_client)
    except Exception as exc:
        logger.info("Could not fetch full article %s (%s)", url, type(exc).__name__)
        return "", "und"


def enrich_news_items(items: Iterable[Any], *, timeout: float = 8.0, max_workers: int = 6) -> list[Any]:
    """Fetch article bodies where possible and set language from the final body.

    The same item can pass through an RSS adapter and an aggregator. An internal
    marker prevents repeating a failed network request without polluting to_dict().
    Network/extraction failure for an individual publisher leaves its original
    text intact and does not stop processing the remaining items.
    """
    result = list(items)
    candidates: list[Any] = []
    for item in result:
        current_text = clean_article_text(getattr(item, "text", ""))
        # API descriptions are sometimes HTML fragments. Clean them even when the
        # original article cannot be downloaded.
        item.text = current_text
        url = str(getattr(item, "url", "") or "")
        already_attempted = getattr(item, "_article_extraction_attempted", False)
        # Long bodies are likely already full article text. Summaries/empty fields
        # trigger a fetch, with URL validation in fetch_article_text.
        if url and not already_attempted and len(current_text) < 1200 and _allowed_article_url(url, getattr(item, "source", "")):
            candidates.append(item)
        else:
            lang = detect_language(current_text or getattr(item, "title", ""), fallback="und")
            if lang != "und":
                item.language = lang

    if not candidates:
        return result

    for item in candidates:
        setattr(item, "_article_extraction_attempted", True)

    worker_count = max(1, int(max_workers))
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
            limits=httpx.Limits(max_connections=worker_count, max_keepalive_connections=worker_count),
        ) as client:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        fetch_article_text,
                        str(item.url),
                        client=client,
                        timeout=timeout,
                        source=str(getattr(item, "source", "")),
                    ): item
                    for item in candidates
                }
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        extracted, html_language = future.result()
                    except Exception as exc:  # one publisher must not break a whole feed
                        logger.warning(
                            "Article extraction task failed for %s: %s",
                            getattr(item, "url", ""),
                            exc,
                        )
                        extracted, html_language = "", "und"

                    fallback_text = clean_article_text(getattr(item, "text", ""))
                    # Prefer publisher article text over a summary. Avoid replacing
                    # a longer API summary with a tiny login/paywall fragment.
                    if extracted and len(extracted) >= max(120, int(len(fallback_text) * 0.60)):
                        item.text = extracted

                    final_text = clean_article_text(getattr(item, "text", ""))
                    item.text = final_text
                    language = detect_language(final_text or getattr(item, "title", ""), fallback=html_language)
                    if language == "und":
                        previous = _normalize_language(getattr(item, "language", "und"))
                        language = previous if previous != "und" else html_language
                    item.language = language
    except Exception as exc:
        # If the shared client itself cannot be initialized, preserve the snippets.
        logger.warning("Could not initialize article-fetch client: %s", exc)
        for item in candidates:
            item.text = clean_article_text(getattr(item, "text", ""))
            language = detect_language(item.text or getattr(item, "title", ""), fallback=getattr(item, "language", "und"))
            if language != "und":
                item.language = language
    return result
