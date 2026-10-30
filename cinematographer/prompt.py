"""Stage 4 SHOOT -- the prompt does exactly two jobs, and this module enforces it.

The two jobs
------------

1. **Describe the action.** "the prompt only has to describe what happens".
2. **Carry the tags** -- ``@`` for Elements, ``#`` for camera moves.

That is the whole contract. :func:`compose_prompt` therefore concatenates the
action, the panel's own fragment, and the tags, and adds **no descriptive prose
of its own**. It will not insert "cinematic", "beautiful", "8k", or any other
magic word, because the product's claim is that the panels do that work and a
prompt that pads itself would hide whether they do.

The syntax gap -- read this before porting anything
---------------------------------------------------

**``@``/``#`` is the app's surface, not the API's.** The API uses one-based
``<<<image_1>>>``, ``<<<video_1>>>`` and ``<<<audio_1>>>`` reference tokens, each
of which must match an attached item of the same type. A workflow built in the UI
does **not** port to the API unchanged: the tags have to be rewritten. We
implement the app's surface because that is what the evidence documents and what
the director's panel produces, and :func:`compose_prompt` emits the rewritten
``<<<image_N>>>`` tokens alongside it so the gap is visible rather than
discovered later.

One parser for ``@``, not two
-----------------------------

:func:`cinematographer.elements.parse_element_tags` already parses ``@`` tags and
already handles the email negative case (``nathaniel@example.com`` yields no
tag). This module **imports it** rather than reimplementing it. The ``#`` scanner
below is not a second copy of that parser: it has a different prefix, a different
name charset (move names are lowercase slugs, Element names may contain spaces
and apostrophes) and a different validator. Sharing the ``@`` scanner and
duplicating the ``#`` one would be the bug; sharing neither would also be the
bug. This shares the one that exists.

Camera moves
------------

The API enum holds **33** named moves and all 33 are implemented here. The list
is a verbatim transcription of the ``camera_movement`` enum in the first-party
API schema capture (see :data:`CAMERA_MOVES` for the citation).

Stdlib only. No numpy, no torch, no ComfyUI.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from .elements import (
    Element,
    ElementRegistry,
    parse_element_tags,
    resolve_elements,
)

__all__ = [
    "MOVE_TAG_PREFIX",
    "CAMERA_MOVES",
    "CAMERA_MOVES_TOTAL",
    "API_REFERENCE_TOKEN",
    "parse_move_tags",
    "MoveResolution",
    "resolve_move_tags",
    "MoveStack",
    "ComposedPrompt",
    "compose_prompt",
    "move_summary",
]

#: The app's camera-move tag prefix.
MOVE_TAG_PREFIX = "#"

#: How many moves the API enum actually holds.
CAMERA_MOVES_TOTAL = 33

#: **COMPLETE -- 33 of 33.** Every value of the API's ``camera_movement`` enum,
#: transcribed verbatim and in source order from the first-party schema capture
#: ``research/cinema-studio-4.0-api-schema.txt`` (shipped in this repository),
#: prose field ``camera_movement``
#: (line 173, ``Allowed values:`` list). The capture's trailing JSON block is
#: truncated mid-object, so the prose list is the authoritative source; the two
#: agree on every field that appears in both.
#:
#: An earlier revision of this module shipped only nine of these and claimed the
#: other 24 were "not published in any source we hold". That claim was false --
#: it came from reading the truncated JSON block and never checking the prose
#: section above it. The full list was on disk the whole time. Recorded here
#: because the failure mode (a plausible sentence that only fails against the
#: source) is the one this project keeps hitting.
CAMERA_MOVES = (
    "snorricam",
    "robot-arm",
    "tilt-up",
    "rack-focus",
    "tilt-down",
    "pov",
    "pan-left",
    "crane-up",
    "pan-right",
    "crane-down",
    "side-tracking",
    "pedestal-up",
    "pedestal-down",
    "handheld",
    "tracking",
    "drone-orbit",
    "dolly-zoom",
    "aerial-pullback",
    "static-shot",
    "bullet-time",
    "whip-pan",
    "slow-zoom-in",
    "arc-left",
    "slow-zoom-out",
    "arc-right",
    "truck-right",
    "dolly-in",
    "truck-left",
    "dolly-out",
    "slider-right",
    "crush-zoom",
    "slider-left",
    "helicopter-shot",
)

#: The API's reference-token form. ``<<<image_1>>>`` is one-based and must match
#: an attached item of the same type.
API_REFERENCE_TOKEN = "<<<image_{n}>>>"

#: Characters legal inside a move name. Lowercase slugs only -- the API enum is
#: hyphenated lowercase, and requiring lowercase is also what stops a hex colour
#: like ``#E36332`` from being read as a move.
_MOVE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _ascii(text: str) -> str:
    """Fold to ASCII, transliterating accents rather than dropping them."""
    folded = unicodedata.normalize("NFKD", str(text))
    return folded.encode("ascii", "ignore").decode("ascii")


def _move_start_ok(text: str, index: int) -> bool:
    """True when the ``#`` at ``index`` opens a tag rather than sitting inside a word.

    ``C#`` and ``shot#1`` are not tags: the ``#`` is glued to a word character.
    """
    if index == 0:
        return True
    previous = text[index - 1]
    return not (previous.isalnum() or previous in "_-")


def parse_move_tags(prompt: str) -> tuple[str, list[str]]:
    """Split ``prompt`` into ``(clean_prompt, moves)``.

    Moves come back in **first-appearance order** -- order is load-bearing,
    because stacked moves run in order -- with duplicates collapsed
    case-insensitively (the first spelling wins).

    Unknown moves are **not** filtered here. This function reports what was
    written; :func:`resolve_move_tags` says which of them the engine recognises.
    Splitting those two jobs is what lets an unknown move be *reported* rather
    than silently dropped.

    When the prompt contains no move tags it is returned **verbatim**, so a
    tag-free prompt is never rewritten.
    """
    text = "" if prompt is None else str(prompt)
    moves: list[str] = []
    seen: set[str] = set()
    kept: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char == MOVE_TAG_PREFIX and _move_start_ok(text, index):
            start = index + 1
            if start < length and text[start] in _MOVE_CHARS and text[start].isalpha():
                end = start
                while end < length and text[end] in _MOVE_CHARS:
                    end += 1
                name = text[start:end].rstrip("-")
                if name:
                    key = name.casefold()
                    if key not in seen:
                        seen.add(key)
                        moves.append(name)
                    index = end
                    continue
        kept.append(char)
        index += 1

    if not moves:
        return (text, [])

    clean = " ".join("".join(kept).split())
    return (clean, moves)


@dataclass
class MoveResolution:
    """The result of checking every ``#move`` in a prompt against the enum.

    ``unknown`` is a **value, not an exception**, for the same reason
    ``ElementResolution.missing`` is: a graph should be able to show the user
    which tags the engine will not honour.
    """

    clean_prompt: str
    moves: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict:
        return {
            "clean_prompt": self.clean_prompt,
            "moves": list(self.moves),
            "unknown": list(self.unknown),
            "ok": self.ok,
        }

    def tag_string(self) -> str:
        """The recognised moves rendered back as ``#a #b``, in order."""
        return " ".join(f"{MOVE_TAG_PREFIX}{move}" for move in self.moves)


def resolve_move_tags(prompt: str) -> MoveResolution:
    """Parse ``#move`` tags and split them into recognised and unknown.

    Never raises for an unknown move: it is reported on the result and ``ok`` is
    False.
    """
    clean, names = parse_move_tags(prompt)
    resolution = MoveResolution(clean_prompt=clean)
    for name in names:
        if name in CAMERA_MOVES:
            resolution.moves.append(name)
        else:
            resolution.unknown.append(name)
    resolution.ok = not resolution.unknown
    return resolution


def move_summary(resolution: MoveResolution) -> str:
    """A one-line, ASCII-only summary of a move resolution."""
    if not resolution.moves and not resolution.unknown:
        return "OK - no #camera-move tags in prompt"
    if resolution.ok:
        return (
            f"OK - {len(resolution.moves)} move(s) in order: "
            + " then ".join(resolution.moves)
        )
    parts: list[str] = []
    if resolution.moves:
        parts.append("recognised: " + ", ".join(resolution.moves))
    if resolution.unknown:
        parts.append("unknown: " + ", ".join(resolution.unknown))
    return "moves - " + "; ".join(parts)


@dataclass
class MoveStack:
    """An ordered stack of recognised moves.

    Strict by construction: every member must be in :data:`CAMERA_MOVES`. Unknown
    moves belong to :class:`MoveResolution`, which is the type that exists to
    carry them. Duplicates are collapsed, first spelling wins, order preserved --
    stacking two of the same move is a no-op, not a double move.
    """

    moves: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for move in self.moves:
            text = str(move)
            if text not in CAMERA_MOVES:
                raise ValueError(
                    f"move={text!r} is not one of the {len(CAMERA_MOVES)} documented "
                    f"moves {CAMERA_MOVES}"
                )
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(text)
        self.moves = cleaned

    def __len__(self) -> int:
        return len(self.moves)

    def __iter__(self):
        return iter(self.moves)

    def is_empty(self) -> bool:
        return not self.moves

    def to_dict(self) -> dict:
        return {"moves": list(self.moves), "count": len(self.moves)}

    def summary(self) -> str:
        if not self.moves:
            return "move stack: empty"
        return (
            f"move stack: {len(self.moves)} move(s), in order - "
            + " then ".join(self.moves)
        )

    def tag_string(self) -> str:
        """Render back to ``#a #b``, in order. Round-trips through
        :func:`parse_move_tags`."""
        return " ".join(f"{MOVE_TAG_PREFIX}{move}" for move in self.moves)

    @classmethod
    def from_dict(cls, data: dict) -> "MoveStack":
        if not isinstance(data, dict):
            raise ValueError(
                f"MoveStack.from_dict expects a dict, got {type(data).__name__}"
            )
        unknown = sorted(set(data) - {"moves", "count"})
        if unknown:
            raise ValueError(
                f"MoveStack.from_dict: unknown field(s) {unknown}; expected ['count', 'moves']"
            )
        moves = data.get("moves") or []
        if not isinstance(moves, (list, tuple)):
            raise ValueError("MoveStack.from_dict: 'moves' must be a list")
        return cls(moves=list(moves))


@dataclass
class ComposedPrompt:
    """The finished Stage 4 prompt, and everything that went into it."""

    action: str
    element_tags: list[str] = field(default_factory=list)
    move_tags: list[str] = field(default_factory=list)
    panel_fragment: str = ""
    final_prompt: str = ""
    attachments: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "element_tags": list(self.element_tags),
            "move_tags": list(self.move_tags),
            "panel_fragment": self.panel_fragment,
            "final_prompt": self.final_prompt,
            "attachments": [dict(a) for a in self.attachments],
            "unresolved": list(self.unresolved),
        }

    def is_ok(self) -> bool:
        """True when every tag resolved."""
        return not self.unresolved


def compose_prompt(
    action: str,
    panel: Any = None,
    elements: Any = None,
    moves: Any = None,
) -> ComposedPrompt:
    """Assemble the Stage 4 prompt from the action, the panel, Elements and moves.

    ``action``
        The prose describing what happens. May itself contain ``@`` and ``#``
        tags; they are extracted.
    ``panel``
        A :class:`cinematographer.director.DirectorPanel`, or ``None``. Only its
        non-auto groups contribute.
    ``elements``
        An :class:`~cinematographer.elements.ElementRegistry`, an iterable of
        :class:`~cinematographer.elements.Element`, or ``None``. With a registry
        every ``@Name`` is resolved and the misses are reported. With ``None`` the
        tags are still parsed but cannot be verified, so they are all reported as
        unresolved rather than assumed good.
    ``moves``
        A :class:`MoveStack`, an iterable of move names, or ``None``. Unknown
        moves are reported, never dropped.

    The returned ``final_prompt`` is the action, then the panel fragment, then the
    ``@`` tags, then the ``#`` tags -- and **nothing else**. This function adds no
    descriptive prose.

    Delimit your ``@`` tags
    -----------------------

    ``@`` names are greedy to the next ``@``, ``#`` or punctuation -- that is
    :func:`~cinematographer.elements.parse_element_tags`'s documented contract,
    and this function inherits it rather than second-guessing it. So::

        "@tamsin, walks into @the-diner."   ->  tags ['tamsin', 'the-diner']
        "@tamsin walks into @the-diner."    ->  tags ['the-diner'], and
                                                'tamsin walks into' is reported
                                                unresolved

    The second form is not silently repaired, because repairing it would mean
    guessing where the name ends. Put the delimiter in -- which is what the app
    does, since a tag is dropped in as a single token.
    """
    # --- action, and the @ tags inside it ---------------------------------
    raw_action = "" if action is None else str(action)
    registry: ElementRegistry | None = None
    if isinstance(elements, ElementRegistry):
        registry = elements
    elif elements is not None:
        registry = ElementRegistry(list(elements))

    element_tags: list[str] = []
    unresolved: list[str] = []
    attachments: list[dict] = []

    if registry is not None:
        resolution = resolve_elements(raw_action, registry)
        body = resolution.clean_prompt
        element_tags = list(resolution.names)
        unresolved.extend(resolution.missing)
        unresolved.extend(f"{name} (ambiguous)" for name in resolution.ambiguous)
        for position, element in enumerate(resolution.resolved, start=1):
            attachments.append(
                {
                    "token": API_REFERENCE_TOKEN.format(n=position),
                    "name": element.name,
                    "asset_path": element.asset_path,
                }
            )
    else:
        body, names = parse_element_tags(raw_action)
        element_tags = list(names)
        # No registry: the tags are real but unverifiable. Report them rather
        # than assume they resolve.
        unresolved.extend(names)

    # --- # moves ----------------------------------------------------------
    move_resolution = resolve_move_tags(body)
    body = move_resolution.clean_prompt
    move_tags = list(move_resolution.moves)
    unresolved.extend(move_resolution.unknown)

    if moves is not None:
        if isinstance(moves, MoveStack):
            stack = moves
        else:
            stack = MoveStack(list(moves))
        # A move supplied as a stack but absent from the text is still a move, so
        # it is appended rather than required to appear in the action.
        for move in stack:
            if move not in move_tags:
                move_tags.append(move)

    # --- panel ------------------------------------------------------------
    panel_fragment = ""
    if panel is not None:
        from .director import panel_prompt_fragment

        panel_fragment = panel_prompt_fragment(panel)

    # --- assemble: action, panel, @tags, #tags. Nothing else. -------------
    pieces: list[str] = []
    if body.strip():
        pieces.append(body.strip())
    if panel_fragment:
        pieces.append(panel_fragment)
    if element_tags:
        pieces.append(" ".join(f"@{name}" for name in element_tags))
    if move_tags:
        pieces.append(" ".join(f"{MOVE_TAG_PREFIX}{move}" for move in move_tags))
    final_prompt = _ascii(" ".join(pieces))

    return ComposedPrompt(
        action=raw_action,
        element_tags=element_tags,
        move_tags=move_tags,
        panel_fragment=panel_fragment,
        final_prompt=final_prompt,
        attachments=attachments,
        unresolved=unresolved,
    )
