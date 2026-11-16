"""Conservative evidence from *fully visible* ingredient names in package OCR.

The CRF entity tagger is trained on a limited lexicon. Its guessed spans must not
overrule a complete, unambiguous generic ingredient printed on the package.
The broader Indian brand index is used only to build a vocabulary of *exact*
ingredient terms; it does not turn a local record into online verification.

This module never guesses missing letters or predicts medicine identities.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import re

from .data import LEXICON
from .model_ner import is_insufficient_salt


# Do not discard the actual ingredient part of a salt when comparing names.
_COUNTERIONS = {
    "hydrochloride", "hcl", "sodium", "potassium", "maleate",
    "succinate", "besylate", "mesylate", "tartrate", "phosphate",
    "sulfate", "sulphate", "fumarate", "bromide", "nitrate",
    "acetate", "monohydrate", "dihydrate", "trihydrate",
}
_ALIASES = {"acetaminophen": "paracetamol", "albuterol": "salbutamol"}
_SPLIT = re.compile(r"\s*(?:\+|/|&|,|\band\b)\s*", re.I)


def _clean(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").casefold()))


def ingredient_roots(composition: str | None) -> frozenset[str]:
    """Compare complete active-ingredient sets, not loose substring matches."""
    if not composition:
        return frozenset()
    roots: set[str] = set()
    for part in _SPLIT.split(composition):
        words = _clean(part).split()
        while len(words) > 1 and words[-1] in _COUNTERIONS:
            words.pop()
        value = " ".join(words)
        if value and not is_insufficient_salt(value):
            roots.add(_ALIASES.get(value, value))
    return frozenset(roots)


@lru_cache(maxsize=1)
def _ingredient_index() -> dict[str, tuple[tuple[str, str], ...]]:
    """Index distinct full generic names by their first token (not 323k regexes)."""
    names: set[str] = set(LEXICON)
    # Preserve the canonical capitalization of curated generic names. The
    # large brand index commonly stores identical ingredient names lowercased.
    canonical_names = {_clean(name): name for name in LEXICON}
    # The index is optional on Render; no dependency on downloaded files.
    try:
        from .integrations import brand_salt_lookup
        if brand_salt_lookup.available() and brand_salt_lookup._ensure_loaded():
            names.update(brand_salt_lookup._cache.values())
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    index: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for composition in names:
        if not isinstance(composition, str):
            continue
        for item in _SPLIT.split(composition):
            item = item.strip()
            key = _clean(item)
            # Eliminate dosage text, tiny fragments and other unreliable values.
            if not (5 <= len(key) <= 65) or re.search(r"\d", key):
                continue
            if is_insufficient_salt(item):
                continue
            index[key.split()[0]].add((key, canonical_names.get(key, item)))
    return {word: tuple(sorted(items, key=lambda x: -len(x[0]))) for word, items in index.items()}


def visible_ingredients(ocr_text: str) -> list[str]:
    """Return only full names literally appearing in OCR, longest spans first."""
    visible = " " + _clean(ocr_text) + " "
    if not visible.strip():
        return []
    results: list[tuple[int, int, str]] = []
    for first in sorted(set(visible.split())):
        for key, name in _ingredient_index().get(first, ()):
            needle = " " + key + " "
            start = visible.find(needle)
            if start < 0:
                continue
            end = start + len(needle)
            results.append((start, end, name))
    # Prefer longer overlaps in all cases, independent of hash iteration order.
    results.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    accepted: list[tuple[int, int, str]] = []
    for start, end, name in results:
        if not any(start < old_end and end > old_start for old_start, old_end, _ in accepted):
            accepted.append((start, end, name))
    accepted.sort(key=lambda x: x[0])
    return [name for _, _, name in accepted]
