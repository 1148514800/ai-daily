"""Deterministic judgement of whether an extracted body is really an article.

Cleaning removes chrome it can recognise, but a page can still hand back
something that is not prose: a cookie wall, a login gate, a listing page, or a
navigation tree. Storing that as the article's body is worse than storing the
feed's own summary, because the reader then gets paragraphs of menu text and
blames the app.

This module answers one question — *is this text an article?* — with five
measurements and fixed thresholds:

* ``chars``: how much text there is at all;
* ``paragraphs`` and ``avg_paragraph_chars``: prose comes in sentences, chrome in
  fragments;
* ``noise_ratio``: the share of paragraphs that are navigation / cookie / share
  / footer wording;
* ``duplicate_ratio``: the share of repeated paragraphs, which is what a
  template repeating itself looks like;
* ``link_text_ratio``: the share of paragraphs that are short and label-like,
  which is what a menu looks like once the tags are gone.

No model is involved, so a verdict is reproducible and a wrong one can be traced
to a single number. The three verdicts are:

* ``GOOD`` — usable as the article body;
* ``LOW`` — some text, but not trustworthy; fall back to the feed summary;
* ``FALLBACK`` — nothing usable at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A CJK character carries roughly the information of a short English word. Used
# only for the length thresholds, so the same rule reads the same way in every
# language the sources publish in.
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")

GOOD = "good"
LOW = "low"
FALLBACK = "fallback"

QUALITY_VALUES = (GOOD, LOW, FALLBACK)

# Below this there is simply not enough text to be an article. Measured in
# "effective" characters: a CJK character carries roughly the information of a
# short English word, so a 250-character Chinese paragraph is a real article
# while a 250-character English one is not. Without this a legitimate Chinese
# body would be rejected for being "too short" by a Latin-oriented threshold.
MIN_CHARS = 400
CJK_CHAR_WEIGHT = 2.5
# Paragraphs shorter than this are labels ("Share", "Subscribe", "Sign in")
# rather than sentences.
SHORT_PARAGRAPH_CHARS = 45
# A menu is mostly short labels; an article with a few short lines is not.
MAX_LINK_TEXT_RATIO = 0.6
# A body that is more than half chrome is a page template, not a story.
MAX_NOISE_RATIO = 0.35
MAX_DUPLICATE_RATIO = 0.35

# Menu and footer text is labels joined by separators; prose is sentences. Both
# signals are used only when a body came back as a single block, which is the one
# shape where neither the paragraph count nor the short-paragraph ratio can tell
# the two apart.
SEPARATOR_RE = re.compile(r"[|•·»«‣▸▶]")
SENTENCE_END_RE = re.compile(r"[.!?。！？；;:…]")

# Wording that only appears in navigation, consent, sharing and footer chrome.
# Matched case-insensitively against a whole paragraph, so a sentence *about*
# cookies is not treated as a cookie banner: the paragraph must be short and
# consist of the wording, which real prose never does.
NOISE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^(accept|reject)( all)?( cookies?)?$",
        r"^manage (cookies|preferences|consent)$",
        r"^cookie (policy|preferences|settings|notice|banner)$",
        r"^(we|this site|our site) uses? cookies?.*$",
        r"^by (clicking|continuing|using).{0,80}cookies?.*$",
        r"^(sign|log) ?(in|up|out)( to .{0,30})?$",
        r"^subscribe( to .{0,40})?$",
        r"^(share|sharing|tweet|post|email|copy link|copy url)( this)?( (article|post|page|link))?$",
        r"^(related|recommended|popular|more) (articles|posts|stories|reading|news|content)$",
        r"^read (more|next|also)$",
        r"^(advertisement|sponsored content|sponsored|ad)$",
        r"^(newsletter|newsletters)$",
        r"^(menu|main menu|navigation|skip to (main )?content|back to top)$",
        r"^(previous|next)( (page|article|post))?$",
        r"^(page|pages) \d+( of \d+)?$",
        r"^\d+ (min|minute|minutes) read$",
        r"^(all rights reserved|©|copyright).*$",
        r"^(privacy|terms|terms of (use|service)|cookie policy|legal|contact|about)( .{0,20})?$",
        r"^(follow us|connect with us|stay in touch)( on .{0,40})?$",
        r"^(share on|follow on) (twitter|x|facebook|linkedin|reddit|whatsapp|mastodon)$",
        r"^tags?[:：].*$",
        r"^(authors?|written by|by) [A-Z][\w.\-']*( [A-Z][\w.\-']*){0,3}$",
    )
)


@dataclass(frozen=True)
class ArticleContentQuality:
    """The measurements behind one verdict, so a decision can be explained."""

    verdict: str
    chars: int
    paragraphs: int
    avg_paragraph_chars: float
    noise_ratio: float
    duplicate_ratio: float
    link_text_ratio: float
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict == GOOD

    def describe(self) -> str:
        return (
            f"{self.verdict} chars={self.chars} paragraphs={self.paragraphs} "
            f"avg={self.avg_paragraph_chars:.0f} noise={self.noise_ratio:.2f} "
            f"dup={self.duplicate_ratio:.2f} links={self.link_text_ratio:.2f}"
            + (f" reason={self.reason}" if self.reason else "")
        )


def paragraphs_of(text: str) -> list[str]:
    """The non-empty paragraphs of a stored body, in order."""
    return [
        block.strip()
        for block in re.split(r"\n\s*\n+", str(text or ""))
        if block.strip()
    ]


def effective_length(text: str) -> int:
    """Text length with CJK characters counted as the words they stand in for."""
    value = str(text or "")
    cjk = len(CJK_RE.findall(value))
    latin = len(value) - cjk
    return int(latin + cjk * CJK_CHAR_WEIGHT)


def is_noise_paragraph(paragraph: str) -> bool:
    """True for a paragraph that is only chrome wording.

    Length is part of the test: a real sentence about cookie consent is long and
    is therefore never matched, while the banner's own "Accept all cookies" is.
    """
    text = " ".join(paragraph.split()).strip().lower()
    if not text or len(text) > 120:
        return False
    # Markdown markers are decoration here, not content.
    text = text.lstrip("#->* ").strip()
    return any(pattern.match(text) for pattern in NOISE_PATTERNS)


def assess_quality(text: str, *, method: str = "") -> ArticleContentQuality:
    """Judge one extracted body. Pure: the same text always gets one verdict."""
    blocks = paragraphs_of(text)
    chars = len(str(text or "").strip())
    count = len(blocks)

    if count == 0 or chars == 0:
        return ArticleContentQuality(FALLBACK, chars, 0, 0.0, 0.0, 0.0, 0.0, "empty")

    lengths = [len(block) for block in blocks]
    avg = sum(lengths) / count
    noise = sum(1 for block in blocks if is_noise_paragraph(block)) / count
    short = sum(1 for length in lengths if length <= SHORT_PARAGRAPH_CHARS) / count
    seen: dict[str, int] = {}
    for block in blocks:
        key = " ".join(block.split()).lower()
        seen[key] = seen.get(key, 0) + 1
    duplicates = sum(count_ - 1 for count_ in seen.values() if count_ > 1)
    duplicate_ratio = duplicates / count

    measurements = (chars, count, avg, noise, duplicate_ratio, short)

    if effective_length(text) < MIN_CHARS:
        if method == "rss_summary":
            # A feed's own teaser is short by design; the caller decides whether
            # to use it, so it is labelled LOW rather than FALLBACK.
            return ArticleContentQuality(LOW, *measurements, reason="short_summary")
        return ArticleContentQuality(FALLBACK, *measurements, reason="too_short")

    if count == 1 and _looks_like_a_menu(text):
        # One long block can be a real article (a page that only uses <br>) or a
        # menu flattened into a single run of labels. No paragraph count can tell
        # them apart, so the text itself has to: labels are joined by separators
        # and end without punctuation, sentences do neither.
        return ArticleContentQuality(LOW, *measurements, reason="menu_like")
    if noise > MAX_NOISE_RATIO:
        return ArticleContentQuality(LOW, *measurements, reason="noisy")
    if duplicate_ratio > MAX_DUPLICATE_RATIO:
        return ArticleContentQuality(LOW, *measurements, reason="repetitive")
    if short > MAX_LINK_TEXT_RATIO:
        return ArticleContentQuality(LOW, *measurements, reason="label_like")
    return ArticleContentQuality(GOOD, *measurements)


def _looks_like_a_menu(text: str) -> bool:
    """Whether a single block of text is a run of navigation labels."""
    block = " ".join(str(text or "").split())
    if SEPARATOR_RE.search(block):
        return True
    head = block[:200]
    return SENTENCE_END_RE.search(head) is None
