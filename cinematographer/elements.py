"""Cinematographer — the Element registry: a reference asset, named once and tagged thereafter.

This is Stage 1.3 (ATTACH) of the rebuilt Cinema Studio flow. Stage 1 *builds*
the cast and the sets as images; this module is what turns each finished image
into a named, categorised, reusable **Element**, and what resolves an
``@Element`` tag in a prompt back to the asset it names.

The load-bearing idea of the whole product is **reuse**: an Element is created
once and tagged thereafter. Everything else in the pipeline is a control surface
over that one idea, so this module is deliberately small and deliberately
boring — a record, a registry, a tag parser, and a bridge into the identity
layer.

What is sourced and what is invented
------------------------------------

* The three categories are **confirmed**: the walkthrough records Higgsfield's own
  taxonomy as Characters / Locations / Props, and the tutorial uses exactly three
  (``location``, ``character``, ``prop``). See ``ELEMENT_CATEGORIES``. The *set* is
  sourced; the order in that constant is ours (the source lists them in a table,
  not in a normative order), so do not read the tuple order as a citation.
* The ``@Name`` tagging syntax is the **app's** surface, not the API's. The API's
  own reference tokens are ``<<<image_1>>>``-style. We implement the app's
  surface and say so rather than implying it is the wire format.
* The name grammar (which characters a multi-word name may contain) is
  **invented — no published source**: the app documents the syntax by example,
  not by grammar. See ``_NAME_EXTRA_CHARS``.
* The audit weights in ``ELEMENT_RULE_WEIGHTS`` are **invented — no published
  source**. They exist so a graph can ask "is this Element usable, and can the
  continuity layer measure it?" and get a stable, testable answer.

Two honesty rules, carried over from the rest of the pack:

* Every threshold is a named module constant, and the comment says where the
  number came from. Where it is a judgement call rather than a published figure,
  the comment says **invented — no published source**.
* When something cannot be measured, it is **reported**, not silently passed and
  not thrown away. An unresolved ``@Name`` is a value on the result, not an
  exception, because a graph should be able to show the user what is unresolved.

Nothing here touches the network, an image, a tensor, or ComfyUI. Persistence is
a plain JSON sidecar at a path the caller chooses; the engine never reads the
clock and never invents a default directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .character import CharacterAppearance
from .geometry import OVERALL_PASS_WEIGHT

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: The confirmed Element taxonomy. Higgsfield's own categories are Characters /
#: Locations / Props, and the tutorial's Element panel uses exactly these three
#: (``location``, ``character``, ``prop``). Lowercase, singular, as tagged.
ELEMENT_CATEGORIES = ("character", "location", "prop")

#: The character that introduces an Element tag in a prompt. The app's surface,
#: not the API's — see the module docstring.
ELEMENT_TAG_PREFIX = "@"

#: Characters allowed *inside* an Element name beyond letters and digits: space
#: (multi-word names such as "Mirror Dunes"), underscore, apostrophe and hyphen.
#: The same set is trimmed from the *end* of a captured name, so ``@Tamsin -``
#: yields ``Tamsin`` rather than ``Tamsin -``.
#: invented — no published source: the app documents the syntax by example
#: (``@Mirror Dunes``, ``@bell barge``, ``@helmet``), not by grammar.
_NAME_EXTRA_CHARS = " _'-"

#: Characters that end a sentence rather than a name. A tag capture stops at any
#: of these, and a space left in front of one is removed when tags are stripped
#: from the prompt, so ``a @Tamsin, wide shot`` cleans to ``a, wide shot``.
#: invented — no published source; a punctuation-tidying choice, not a rule the
#: app documents.
_SENTENCE_PUNCTUATION = ",.;:!?"

#: Characters that, immediately before an ``@``, mean it is NOT a tag. A word
#: character before ``@`` makes it an email address (``nathaniel@example.com``);
#: a second ``@`` makes it a typo (``@@Tamsin``), not a tag.
#: invented — no published source; it is the reading that makes the documented
#: email case behave.
_TAG_BLOCKING_PREVIOUS_CHARS = "@_"

#: Suffix of the JSON sidecar written next to an asset. ``sidecar_path`` is the
#: only place this convention lives.
#: invented — no published source: the walkthrough says a sidecar JSON is written
#: next to the asset, and says nothing about its name.
ELEMENT_SIDECAR_SUFFIX = ".element.json"

#: The Element audit rules, in evaluation order. These are not framing rules:
#: they ask whether an Element is *usable* (does it have a name, a category, an
#: asset) and whether the identity layer can *measure* it (does it carry a
#: palette and a bounding box).
ELEMENT_RULES = (
    "named",
    "categorised",
    "asset_present",
    "palette_present",
    "bbox_present",
    "described",
)

#: Rule weights. At or above ``OVERALL_PASS_WEIGHT`` (0.8) a rule gates the
#: audit; below it the rule is reported but cannot fail an Element.
#:
#: named / categorised / asset_present — an Element with no name, no legal
#: category, or no asset cannot be tagged, listed, or loaded. 1.0, gating.
#: ``named`` and ``categorised`` are guaranteed by ``Element.__post_init__``;
#: they are kept because a registry can also be rebuilt from a sidecar, and the
#: audit should not depend on every future path having validated.
#:
#: palette_present / bbox_present — 0.5, non-gating. A location clean plate has
#: no character palette and a prop may have no bounding box, so neither may fail
#: an Element. They are reported because ``character_record_from_element`` needs
#: both, and a graph should be able to warn before it gets there.
#: invented — no published source; chosen below the 0.8 gate.
#:
#: described — 0.3, non-gating. A description is a convenience for a human
#: reading the cast list, never a requirement.
#: invented — no published source.
ELEMENT_RULE_WEIGHTS: dict[str, float] = {
    "named": 1.0,
    "categorised": 1.0,
    "asset_present": 1.0,
    "palette_present": 0.5,
    "bbox_present": 0.5,
    "described": 0.3,
}


def _gates(weight: float) -> bool:
    """Whether a rule at ``weight`` gates the Element audit.

    Split out so the boundary itself is testable: with the current weights
    (1.0, 1.0, 1.0, 0.5, 0.5, 0.3) no rule sits at exactly 0.8, so ``>=`` and
    ``>`` are indistinguishable from the rule set alone. This predicate is where
    the inclusive comparison lives, and it is pinned directly.
    """
    return weight >= OVERALL_PASS_WEIGHT


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


@dataclass
class Element:
    """A named, categorised, reusable reference asset.

    ``palette`` is the asset's dominant colours, each 0..1 RGB, ordered by
    coverage; it may be empty (a location clean plate usually is). ``bbox`` is
    normalised NDC bounds ``(min_x, min_y, max_x, max_y)`` in the same convention
    as :mod:`~cinematographer.geometry` — x, y in [-1, 1], y up — and may be
    ``None``.

    ``created_utc`` is an ISO-8601 timestamp supplied by the **caller**. The
    engine does not read the clock: a record built from the same inputs is
    byte-identical, which is what makes the sidecar diffable and the tests
    deterministic.
    """

    name: str
    category: str
    asset_path: str
    description: str = ""
    seed: int = 0
    palette: tuple[tuple[float, float, float], ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    created_utc: str = ""

    def __post_init__(self) -> None:
        if self.category not in ELEMENT_CATEGORIES:
            raise ValueError(
                f"unknown Element category {self.category!r}; "
                f"legal categories are {ELEMENT_CATEGORIES}"
            )

        self.name = str(self.name).strip()
        if not self.name:
            raise ValueError("Element name must be a non-empty string")
        self.asset_path = str(self.asset_path)
        self.description = str(self.description)
        self.created_utc = str(self.created_utc)
        self.seed = int(self.seed)

        colours: list[tuple[float, float, float]] = []
        for colour in self.palette or ():
            channels = tuple(float(c) for c in colour)
            if len(channels) != 3:
                raise ValueError(
                    f"Element {self.name!r}: a palette colour must have 3 channels "
                    f"(r, g, b), got {len(channels)}"
                )
            for channel in channels:
                if not (0.0 <= channel <= 1.0):
                    raise ValueError(
                        f"Element {self.name!r}: palette channel {channel!r} is "
                        "outside 0..1 (colours are normalised RGB)"
                    )
            colours.append(channels)  # type: ignore[arg-type]
        self.palette = tuple(colours)

        if self.bbox is not None:
            bounds = tuple(float(v) for v in self.bbox)
            if len(bounds) != 4:
                raise ValueError(
                    f"Element {self.name!r}: bbox must be 4 NDC values "
                    f"(min_x, min_y, max_x, max_y), got {len(bounds)}"
                )
            if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
                raise ValueError(
                    f"Element {self.name!r}: bbox {bounds} is inverted "
                    "(min must not exceed max on either axis)"
                )
            self.bbox = bounds  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "asset_path": self.asset_path,
            "description": self.description,
            "seed": self.seed,
            "palette": [list(colour) for colour in self.palette],
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "created_utc": self.created_utc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Element":
        bbox = d.get("bbox")
        return cls(
            name=str(d.get("name", "")),
            category=str(d.get("category", "")),
            asset_path=str(d.get("asset_path", "")),
            description=str(d.get("description", "")),
            seed=int(d.get("seed", 0)),
            palette=tuple(
                tuple(float(c) for c in colour) for colour in d.get("palette") or ()
            ),
            bbox=None if bbox is None else tuple(float(v) for v in bbox),
            created_utc=str(d.get("created_utc", "")),
        )


# --------------------------------------------------------------------------
# Name handling
# --------------------------------------------------------------------------


def _normalise_name(name: str) -> str:
    """Strip whitespace and one leading ``@``.

    The ``@`` is stripped because that is how an Element is tagged in a prompt,
    and a caller that has just parsed a tag should not have to remember to take
    the sigil off before looking it up.
    """
    text = str(name).strip()
    if text.startswith(ELEMENT_TAG_PREFIX):
        text = text[len(ELEMENT_TAG_PREFIX):].strip()
    return text


def sidecar_path(asset_path: str) -> str:
    """The JSON sidecar path for an asset: its suffix replaced by the sidecar suffix.

    ``sidecar_path("out/tamsin.png") == "out/tamsin.element.json"``. The engine
    does not create the file here — ``ElementRegistry.save`` does — and it does
    not choose the directory, because a default location would be an invented
    convention with no published source.
    """
    path = Path(str(asset_path))
    return str(path.with_suffix(ELEMENT_SIDECAR_SUFFIX))


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


class ElementRegistry:
    """The project's Elements: in memory, with a JSON sidecar for persistence.

    Lookup is **case-insensitive** and strips one leading ``@``. A duplicate name
    in the *same* category is an error; the same name in *different* categories
    is legal, and ``get(name)`` then raises an ambiguity error rather than
    guessing which one the caller meant.
    """

    def __init__(self, elements: Iterable[Element] | None = None) -> None:
        self._by_key: dict[tuple[str, str], Element] = {}
        for element in elements or ():
            self.add(element)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _key(name: str, category: str) -> tuple[str, str]:
        return (category, _normalise_name(name).casefold())

    @staticmethod
    def _require_category(category: str) -> str:
        if category not in ELEMENT_CATEGORIES:
            raise ValueError(
                f"unknown Element category {category!r}; "
                f"legal categories are {ELEMENT_CATEGORIES}"
            )
        return category

    # -- mutation ----------------------------------------------------------

    def add(self, element: Element) -> Element:
        """Register ``element``. Returns it, so ``add`` can be chained."""
        if not isinstance(element, Element):
            raise TypeError(f"add() expects an Element, got {type(element).__name__}")
        key = self._key(element.name, element.category)
        if key in self._by_key:
            raise ValueError(
                f"duplicate Element {element.name!r} in category "
                f"{element.category!r}; remove the existing Element first, or use "
                "a different name"
            )
        self._by_key[key] = element
        return element

    def remove(self, name: str, category: str | None = None) -> Element:
        """Remove and return an Element. Raises if it is absent or ambiguous."""
        element = self.get(name, category)
        del self._by_key[self._key(element.name, element.category)]
        return element

    # -- lookup ------------------------------------------------------------

    def find(self, name: str, category: str | None = None) -> Element | None:
        """Return the matching Element, or ``None`` when there is none.

        Raises ``ValueError`` when the name exists in more than one category and
        no ``category`` was given — an ambiguity is a caller error, not a
        missing Element, and the two must not be conflated.
        """
        wanted = _normalise_name(name)
        if category is not None:
            self._require_category(category)
            return self._by_key.get((category, wanted.casefold()))
        hits = [
            element
            for element in self._by_key.values()
            if element.name.casefold() == wanted.casefold()
        ]
        if len(hits) > 1:
            categories = ", ".join(sorted(element.category for element in hits))
            raise ValueError(
                f"Element name {wanted!r} is ambiguous: it exists in categories "
                f"{categories}; pass the category to choose one"
            )
        return hits[0] if hits else None

    def get(self, name: str, category: str | None = None) -> Element:
        """Return the matching Element. Raises ``KeyError`` when there is none."""
        element = self.find(name, category)
        if element is None:
            where = f" in category {category!r}" if category is not None else ""
            raise KeyError(f"no Element named {_normalise_name(name)!r}{where}")
        return element

    def by_category(self, category: str) -> list[Element]:
        """Every Element in ``category``, ordered by name (case-insensitive)."""
        self._require_category(category)
        return sorted(
            (e for e in self._by_key.values() if e.category == category),
            key=lambda e: e.name.casefold(),
        )

    def names(self) -> list[str]:
        """Every stored name, ordered case-insensitively.

        One entry per Element, so a name that exists in two categories appears
        twice — the registry stores Elements, not names. Use ``by_category`` to
        see which is which.
        """
        return [
            element.name
            for element in sorted(
                self._by_key.values(), key=lambda e: e.name.casefold()
            )
        ]

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> dict:
        ordered = sorted(
            self._by_key.values(), key=lambda e: (e.category, e.name.casefold())
        )
        return {
            "categories": list(ELEMENT_CATEGORIES),
            "elements": [element.to_dict() for element in ordered],
        }

    @classmethod
    def from_dict(cls, d: dict | list) -> "ElementRegistry":
        """Rebuild a registry from ``to_dict()`` output, or from a bare list."""
        if isinstance(d, list):
            records = d
        elif isinstance(d, dict):
            records = d.get("elements") or ()
        else:
            raise ValueError(
                f"cannot read an Element registry from {type(d).__name__}; "
                "expected a dict with an 'elements' list, or a bare list"
            )
        return cls(Element.from_dict(record) for record in records)

    def save(self, path: str) -> str:
        """Write the registry to ``path`` as JSON, creating parent dirs.

        Returns the path written, so a node can report where the sidecar landed.
        """
        target = Path(str(path))
        if not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return str(target)

    @classmethod
    def load(cls, path: str) -> "ElementRegistry":
        """Read a registry written by :meth:`save`."""
        return cls.from_dict(json.loads(Path(str(path)).read_text(encoding="utf-8")))

    # -- dunder ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self) -> Iterator[Element]:
        return iter(
            sorted(self._by_key.values(), key=lambda e: (e.category, e.name.casefold()))
        )


# --------------------------------------------------------------------------
# Tag parsing
# --------------------------------------------------------------------------


def _tag_start_ok(text: str, index: int) -> bool:
    """Whether the ``@`` at ``index`` can start a tag.

    False when the previous character is a word character (an email address) or
    another ``@``. Split out so the email negative case is testable on its own.
    """
    if index == 0:
        return True
    previous = text[index - 1]
    return not (previous.isalnum() or previous in _TAG_BLOCKING_PREVIOUS_CHARS)


def _is_name_char(char: str) -> bool:
    """Whether ``char`` may appear inside an Element name."""
    return char.isalnum() or char in _NAME_EXTRA_CHARS


def _tidy(text: str) -> str:
    """Collapse whitespace, drop a space before sentence punctuation, trim edges.

    Only applied when at least one tag was actually removed, so a tag-free prompt
    is never rewritten.
    """
    collapsed = " ".join(text.split())
    kept: list[str] = []
    for char in collapsed:
        if char in _SENTENCE_PUNCTUATION and kept and kept[-1] == " ":
            kept.pop()
        kept.append(char)
    # ``collapsed`` holds only single spaces, so a tab cannot reach this strip.
    return "".join(kept).strip(" " + _SENTENCE_PUNCTUATION)


def parse_element_tags(prompt: str) -> tuple[str, list[str]]:
    """Split ``prompt`` into ``(clean_prompt, names)``.

    A tag is an ``@`` that is not glued to a word character, followed by a name
    that starts with a letter or digit and runs to the next ``@``, ``#``, or
    punctuation. Names come back in **first-appearance order**, with duplicates
    collapsed case-insensitively (the first spelling wins).

    Two consequences worth stating out loud:

    * ``nathaniel@example.com`` yields **no** tag — the ``@`` is preceded by a
      word character, so it is an email address.
    * A name is greedy to the next delimiter, so ``@Mirror Dunes and @Oscar``
      yields ``Mirror Dunes and``. That is the documented syntax ("up to the next
      ``@``, ``#``, or punctuation"), not a bug; put the delimiter in.

    ``clean_prompt`` is the prompt with the tag spans removed, whitespace
    collapsed, and leftover edge punctuation trimmed. When the prompt contains no
    tags it is returned **verbatim**, so a tag-free prompt is never rewritten.
    """
    text = "" if prompt is None else str(prompt)
    names: list[str] = []
    seen: set[str] = set()
    kept: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char == ELEMENT_TAG_PREFIX and _tag_start_ok(text, index):
            start = index + 1
            if start < length and text[start].isalnum():
                end = start
                while end < length and _is_name_char(text[end]):
                    end += 1
                # Trim separators from the end, then collapse any run of
                # whitespace *inside* the name, so "@Mirror   Dunes" and
                # "@Mirror Dunes" are the same Element. The scan still advances
                # past the trimmed span, so trailing separators stay in the
                # prompt rather than being swallowed.
                trimmed = text[start:end].rstrip(_NAME_EXTRA_CHARS)
                raw = " ".join(trimmed.split())
                if raw:
                    key = raw.casefold()
                    if key not in seen:
                        seen.add(key)
                        names.append(raw)
                    index = start + len(trimmed)
                    continue
        kept.append(char)
        index += 1

    if not names:
        return text, []
    return _tidy("".join(kept)), names


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


@dataclass
class ElementResolution:
    """The result of resolving every ``@Name`` in a prompt against a registry.

    ``missing`` is a **value, not an exception**: a graph should be able to show
    the user which tags did not resolve. ``ambiguous`` is the same idea for a
    name that exists in more than one category — it is reported separately
    because the fix is different (pass a category, not create an Element).
    """

    clean_prompt: str
    resolved: list[Element] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ok: bool = True
    ambiguous: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        """The names of the resolved Elements, in prompt order."""
        return [element.name for element in self.resolved]

    def to_dict(self) -> dict:
        return {
            "clean_prompt": self.clean_prompt,
            "resolved": [element.to_dict() for element in self.resolved],
            "missing": list(self.missing),
            "ambiguous": list(self.ambiguous),
            "ok": self.ok,
        }


def resolve_elements(prompt: str, registry: ElementRegistry) -> ElementResolution:
    """Resolve every ``@Name`` in ``prompt`` against ``registry``.

    Never raises for an unknown or ambiguous name: both are reported on the
    result and ``ok`` is False. That is deliberate — a graph should be able to
    render "3 of 4 Elements resolved, missing: helmet" rather than fail.
    """
    clean_prompt, names = parse_element_tags(prompt)
    resolution = ElementResolution(clean_prompt=clean_prompt)
    for name in names:
        try:
            element = registry.find(name)
        except ValueError:
            resolution.ambiguous.append(name)
            continue
        if element is None:
            resolution.missing.append(name)
        else:
            resolution.resolved.append(element)
    resolution.ok = not resolution.missing and not resolution.ambiguous
    return resolution


def element_summary(resolution: ElementResolution) -> str:
    """A one-line, ASCII-only human summary of a resolution."""
    total = (
        len(resolution.resolved) + len(resolution.missing) + len(resolution.ambiguous)
    )
    if total == 0:
        return "OK - no @Element tags in prompt"
    if resolution.ok:
        return (
            f"OK - resolved {len(resolution.resolved)} element(s): "
            + ", ".join(resolution.names)
        )
    parts: list[str] = []
    if resolution.missing:
        parts.append("missing: " + ", ".join(resolution.missing))
    if resolution.ambiguous:
        parts.append("ambiguous: " + ", ".join(resolution.ambiguous))
    return (
        f"UNRESOLVED - {len(resolution.resolved)} of {total} element(s) resolved; "
        + "; ".join(parts)
    )


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------


@dataclass
class ElementCheck:
    """One audit rule's verdict on one Element."""

    rule: str
    passed: bool
    weight: float
    detail: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "pass": self.passed,
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass
class ElementAudit:
    """The audit verdict on one Element, rule by rule."""

    name: str
    category: str
    checks: list[ElementCheck] = field(default_factory=list)
    overall_pass: bool = True

    def check(self, rule: str) -> ElementCheck | None:
        for check in self.checks:
            if check.rule == rule:
                return check
        return None

    def failures(self) -> list[ElementCheck]:
        """Every failing check, gating or not."""
        return [check for check in self.checks if not check.passed]

    @property
    def continuity_ready(self) -> bool:
        """Whether ``character_record_from_element`` can build a record from this.

        True only when both the palette and the bounding box are present. This is
        the question the identity layer actually cares about, and it is separate
        from ``overall_pass``: a location clean plate can pass the audit and still
        not be measurable.
        """
        return all(
            check.passed
            for check in self.checks
            if check.rule in ("palette_present", "bbox_present")
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "checks": [check.to_dict() for check in self.checks],
            "overall_pass": self.overall_pass,
            "continuity_ready": self.continuity_ready,
        }


def audit_element(element: Element) -> ElementAudit:
    """Audit one Element against ``ELEMENT_RULES``.

    ``overall_pass`` is True only when every rule weighted at or above
    ``geometry.OVERALL_PASS_WEIGHT`` passes. ``palette_present``, ``bbox_present``
    and ``described`` are weighted below the gate, so they are reported but
    cannot fail an Element.
    """
    verdicts: dict[str, tuple[bool, str]] = {
        "named": (
            bool(element.name.strip()),
            f"name {element.name!r}",
        ),
        "categorised": (
            element.category in ELEMENT_CATEGORIES,
            f"category {element.category!r}",
        ),
        "asset_present": (
            bool(element.asset_path.strip()),
            f"asset_path {element.asset_path!r}",
        ),
        "palette_present": (
            len(element.palette) > 0,
            f"{len(element.palette)} palette colour(s)",
        ),
        "bbox_present": (
            element.bbox is not None,
            f"bbox {element.bbox}",
        ),
        "described": (
            bool(element.description.strip()),
            f"description {element.description!r}",
        ),
    }
    checks = [
        ElementCheck(
            rule=rule,
            passed=verdicts[rule][0],
            weight=ELEMENT_RULE_WEIGHTS[rule],
            detail=verdicts[rule][1],
        )
        for rule in ELEMENT_RULES
    ]
    audit = ElementAudit(
        name=element.name, category=element.category, checks=checks
    )
    audit.overall_pass = all(check.passed for check in checks if _gates(check.weight))
    return audit


def audit_summary(audit: ElementAudit) -> str:
    """A one-line, ASCII-only human summary of an Element audit."""
    failed = audit.failures()
    if not failed:
        return (
            f"OK - Element {audit.name!r} ({audit.category}) passes all "
            f"{len(audit.checks)} checks"
        )
    parts = [f"{check.rule} ({check.detail})" for check in failed]
    if audit.overall_pass:
        return (
            f"OK - Element {audit.name!r} ({audit.category}) passes "
            f"{len(audit.checks)} checks with {len(failed)} non-gating flag(s): "
            + ", ".join(parts)
        )
    return (
        f"FAIL - Element {audit.name!r} ({audit.category}): " + ", ".join(parts)
    )


# --------------------------------------------------------------------------
# The bridge into the identity layer
# --------------------------------------------------------------------------


def character_record_from_element(element: Element) -> CharacterAppearance:
    """Build a :class:`~cinematographer.character.CharacterAppearance` from an Element.

    This is how the identity-continuity layer measures a generated shot against
    the Element it was built from: the Element supplies the reference palette and
    bounding box, and ``character.evaluate_character_continuity`` measures drift
    from there.

    Raises ``ValueError`` when the Element carries no palette or no bounding box.
    It does **not** substitute a default: an invented palette would make a drift
    measurement look like a pass, which is exactly the failure mode this pack
    exists to avoid. ``audit_element(element).continuity_ready`` answers the same
    question without raising.
    """
    if not element.palette:
        raise ValueError(
            f"Element {element.name!r} has no palette, so it cannot be measured "
            "for appearance drift; supply at least one dominant 0..1 RGB colour"
        )
    if element.bbox is None:
        raise ValueError(
            f"Element {element.name!r} has no bbox, so it cannot be measured for "
            "appearance drift; supply NDC bounds (min_x, min_y, max_x, max_y)"
        )
    return CharacterAppearance(
        name=element.name,
        bbox=element.bbox,
        palette=element.palette,
    )
