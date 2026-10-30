"""The Director's Panel -- set the parameters *before* the render, not after.

Why this module exists
----------------------

Every other module in this engine judges a frame that already exists. This one
is the inversion the whole entry turns on: it *sets* the conditioning before
generation. The pack's pitch is "tell me the frame is wrong, by how much, and
which way to move"; the Director's Panel is the other half -- "here is how to
aim it in the first place".

Five groups, and **every one of them starts on auto**. Auto is modelled as
``None``, so "the user did not touch this group" is representable and is not the
same as "the user chose the first option". A panel where every group is auto
contributes nothing to the prompt, which is the correct behaviour and is tested.

Provenance, and what is *not* known
-----------------------------------

Every enum below is transcribed from the Cinema Studio 4.0 evidence set, not
invented. Where the evidence is incomplete the constant carries a comment saying
so, and the list is left short rather than padded. Three conflicts are recorded
in place rather than silently resolved:

* **Genre count.** The API enum has 6 genres and no ``general``; the UI and help
  centre list 7 including General. Both are first-party. We implement the 6 the
  API accepts, because that is the set a request can actually carry.
* **Tempo vs Montage Pacing.** The 4.0 editorial and settings reference call the
  group *Tempo*; the how-we-built FAQ and product page call the same control
  *Montage Pacing*. Same control, two first-party names. The API field is
  ``pacing``, so that is the attribute name here and the UI label is recorded in
  a comment.
* **Emotion count.** The settings reference enumerates 8; the on-screen wheel
  showed 8 legible segments that are *not* the same 8; one tutorial claims 80
  across 3 strength levels. We implement the union of what was actually read and
  say so. There is **no ``emotion`` field in the API schema at all**, so the
  emotion group is UI-only as far as the public contract goes.

Focal length
------------

``FOCAL_LENGTH_DROPPED_IN_4_0`` records a real finding: focal length was one of
the three original Cinema Studio 1.0 controls and was still named in 2.0 and 3.5,
but it is absent from the 4.0 settings reference, the 4.0 help-centre walkthrough
and the 4.0 API schema. Our engine has focal length first-class, which makes it a
**superset** of 4.0 -- a claim this pack can support, unlike most of the field.

Stdlib only. No numpy, no torch, no ComfyUI.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "GENRES",
    "ERAS",
    "TEMPOS",
    "CAMERA_BODIES",
    "LENSES",
    "APERTURES",
    "LIGHTING_LOOKS",
    "COLOUR_PALETTES",
    "COLOUR_PALETTES_TOTAL",
    "EMOTIONS",
    "EMOTION_INTENSITY_MIN",
    "EMOTION_INTENSITY_MAX",
    "FOCAL_LENGTH_DROPPED_IN_4_0",
    "PANEL_FIELDS",
    "FilmSetup",
    "CameraSetup",
    "LightingSetup",
    "PaletteSetup",
    "EmotionDirection",
    "DirectorPanel",
    "panel_prompt_fragment",
    "panel_conditioning",
    "panel_summary",
]

# --------------------------------------------------------------------------
# Film setup -- genre / era / tempo
# --------------------------------------------------------------------------

#: The API enum. Six values, and **no** ``general``.
#:
#: CONFLICT: the UI and help centre list 7 genres including General. Both are
#: first-party. We implement the 6 the API accepts, because a request cannot
#: carry a genre the schema does not define.
GENRES = ("epic", "drama", "noir", "comedy", "horror", "action")

#: The API ``era`` enum. Five decades.
ERAS = ("1960s", "1980s", "1990s", "2000s", "2020s")

#: The API ``pacing`` enum.
#:
#: CONFLICT: the 4.0 editorial and settings reference call this group **Tempo**;
#: the how-we-built FAQ and product page call the same control **Montage
#: Pacing**. Same control, two first-party names. The API field is ``pacing``,
#: so that is the attribute name used here.
TEMPOS = ("chaotic", "dynamic", "calm", "single-shot")

# --------------------------------------------------------------------------
# Camera -- body / lens / aperture
# --------------------------------------------------------------------------

#: Four bodies. The API enum, and all four were also read on screen.
CAMERA_BODIES = ("modern", "35mm-film", "8mm-film", "dv-camcorder")

#: Five lenses. All five are in the API enum; ``anamorphic`` and
#: ``vintage-anamorphic`` were not observed on screen, but the picker column
#: scrolls, so that is a coverage gap rather than evidence of absence.
LENSES = (
    "clean-sharp",
    "anamorphic",
    "vintage-anamorphic",
    "warm-vintage",
    "halation-vintage",
)

#: Three apertures. The slug ``f14`` is the API's own typo for ``f/1.4``; the
#: on-screen label reads ``f/1.4 Wide Open``. We keep the slug verbatim so the
#: value can be sent to the API unchanged, and record the discrepancy here.
APERTURES = ("f14-wide-open", "f4-moderate", "f11-deep-focus")

# --------------------------------------------------------------------------
# Lighting
# --------------------------------------------------------------------------

#: Six presets, and this list is **complete**: the API enum supplies all six.
#: Three were read on screen (``practicals``, ``window``, and a truncated
#: ``Si...`` read as ``silhouette``), two were read truncated, and
#: ``contre-jour`` was never legible -- but the enum names all six, so nothing
#: here is guessed.
LIGHTING_LOOKS = (
    "silhouette",
    "practicals",
    "window",
    "overhead-fall",
    "contre-jour",
    "soft-cross",
)

# --------------------------------------------------------------------------
# Colour palette
# --------------------------------------------------------------------------

#: How many palettes the API enum actually holds.
COLOUR_PALETTES_TOTAL = 50

#: **COMPLETE -- 50 of 50.** Every value of the API's ``color_palette`` enum,
#: transcribed verbatim and in source order from the first-party schema capture
#: ``research/cinema-studio-4.0-api-schema.txt`` (shipped in this repository),
#: prose field ``color_palette``
#: (line 161, ``Allowed values:`` list). The capture's trailing JSON block is
#: truncated mid-object, so the prose list is the authoritative source; the two
#: agree on every field that appears in both.
#:
#: An earlier revision of this module shipped only eight of these and claimed the
#: other 42 were "not published in any source we hold". That claim was false --
#: it came from reading the truncated JSON block and never checking the prose
#: section above it. The full list was on disk the whole time.
#:
#: Note also that user-created palettes (``Molten Dawn``, ``Nostalgic Blue``,
#: ``dreamy teal``, ``graveyard shift``, ``violet hour``) are **not** enum
#: members and are deliberately absent -- a custom palette is free text, not a
#: preset. :class:`PaletteSetup` accepts them only with ``custom=True``.
COLOUR_PALETTES = (
    "static-noon",
    "twilight-fable",
    "back-row-kissing-seats",
    "on-the-other-side-of-the-porthole",
    "the-emerald-ambush",
    "highway-standoff",
    "the-faded-fresco",
    "oil-ochre",
    "the-mountain-convent",
    "ghost-in-the-code",
    "pink-velvet",
    "two-days-to-the-horizon",
    "industrial-fog",
    "stairs-go-up",
    "field-post",
    "home-is-the-next-gas-station",
    "glossy-flesh",
    "the-crimson-ballet",
    "neon-rain-at-midnight",
    "the-morning-after-rain",
    "the-iron-borough",
    "the-ground",
    "the-investigation",
    "turquoise-mirage",
    "a-dream-in-color",
    "breakfast-on-schedule",
    "favela-gold",
    "a-hotel-for-one",
    "after-dark",
    "crimson-vigi",
    "the-neighbors-saw-everything",
    "the-grey-channel",
    "mirage-at-noon",
    "bubblegum-boulevard",
    "yellow-room",
    "the-earth-keeps-things-reluctantly",
    "tropic-fever-dream",
    "bioluminescent-night",
    "dont-turn-it-off-im-watching",
    "the-silk-curtain-falls",
    "the-butterfly",
    "playtime",
    "wallpaper-romance",
    "overtime",
    "the-way-home-is-longer",
    "everyone-speaks-in-whispers",
    "runaway-summer",
    "amber-wasteland",
    "the-circus",
    "gasoline-sunset",
)

# --------------------------------------------------------------------------
# Emotion wheel
# --------------------------------------------------------------------------

#: **PARTIAL, and the source disagrees with itself.** Nine names, being the union
#: of the two lists the evidence actually contains:
#:
#: * read off the on-screen wheel: Sadness, Fear, Anger, Joy, Trust, Disgust,
#:   Surprise, Interest
#: * enumerated by the settings reference: Hope, Anger, Joy, Trust, Fear,
#:   Surprise, Sadness, Disgust
#:
#: The two 8-item lists differ by exactly one member (``Interest`` vs ``Hope``),
#: so the union is 9. One tutorial claims **80 emotions across 3 strength
#: levels**; that is unverified and we do not implement 80. The wheel is visibly
#: larger than the visible arc, so this list is a floor, not a ceiling.
#:
#: Title Case is the on-screen form. There is no API ``emotion`` field, so there
#: is no slug convention to follow.
EMOTIONS = (
    "Sadness",
    "Fear",
    "Anger",
    "Joy",
    "Trust",
    "Disgust",
    "Surprise",
    "Interest",
    "Hope",
)

#: INVENTED -- no published source. The evidence claims three discrete strength
#: levels but **no intensity or strength control was legible in any frame**, so
#: the number of levels and their boundaries are unknown. We model intensity as a
#: continuous 0..1 instead of inventing three cut points, and say so.
EMOTION_INTENSITY_MIN = 0.0
EMOTION_INTENSITY_MAX = 1.0

#: Focal length was one of the three original Cinema Studio 1.0 controls and was
#: still named in 2.0 and 3.5. It is absent from the 4.0 settings reference, the
#: 4.0 help-centre walkthrough, and the 4.0 API schema. It was dropped in 4.0.
#: Our engine keeps it, which makes this pack a superset of 4.0.
FOCAL_LENGTH_DROPPED_IN_4_0 = True

#: The API field names this module emits, in the order they are emitted. Kept as
#: a constant so the director's-panel web mirror can assert against it rather
#: than against a hand-copied list.
#:
#: ``camera_movement`` is deliberately **not** here. The move is not a panel
#: value: it is carried in the prompt as a ``#`` tag (see :mod:`cinematographer.prompt`).
#: ``compose_prompt`` emits it. Putting it here would misrepresent the mechanism.
PANEL_FIELDS = (
    "genre",
    "era",
    "pacing",
    "camera_model",
    "camera_lens",
    "camera_aperture",
    "light",
    "color_palette",
    "emotion",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ascii(text: str) -> str:
    """Fold ``text`` to ASCII, transliterating accents rather than dropping them.

    The prompt fragment is required to be ASCII-only, and a character name is
    user-supplied, so it is the one field that can carry non-ASCII. NFKD splits
    an accented letter into base + combining mark, and the combining mark is then
    discarded -- so ``Zoë`` becomes ``Zoe`` rather than ``Zo``.
    """
    folded = unicodedata.normalize("NFKD", str(text))
    return folded.encode("ascii", "ignore").decode("ascii")


def _check(value: Any, allowed: tuple[str, ...], label: str) -> str | None:
    """Return ``value`` if it is ``None`` or a member of ``allowed``; else raise.

    ``None`` is auto and is always legal. Anything else must be an exact member:
    the error names the bad value *and* the legal set, because "invalid genre" is
    not an actionable message.
    """
    if value is None:
        return None
    text = str(value)
    if text not in allowed:
        raise ValueError(
            f"{label}={text!r} is not one of {allowed}"
        )
    return text


def _reject_unknown(cls_name: str, data: Any, allowed: tuple[str, ...]) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{cls_name}.from_dict expects a dict, got {type(data).__name__}")
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValueError(
            f"{cls_name}.from_dict: unknown field(s) {unknown}; expected {sorted(allowed)}"
        )


# --------------------------------------------------------------------------
# The five groups
# --------------------------------------------------------------------------


@dataclass
class FilmSetup:
    """Genre / era / tempo. All three default to auto (``None``)."""

    genre: str | None = None
    era: str | None = None
    pacing: str | None = None

    def __post_init__(self) -> None:
        self.genre = _check(self.genre, GENRES, "genre")
        self.era = _check(self.era, ERAS, "era")
        self.pacing = _check(self.pacing, TEMPOS, "pacing")

    def is_auto(self) -> bool:
        """True when no axis in this group was set."""
        return self.genre is None and self.era is None and self.pacing is None

    def to_dict(self) -> dict:
        return {"genre": self.genre, "era": self.era, "pacing": self.pacing}

    @classmethod
    def from_dict(cls, data: dict) -> "FilmSetup":
        _reject_unknown(cls.__name__, data, ("genre", "era", "pacing"))
        return cls(genre=data.get("genre"), era=data.get("era"), pacing=data.get("pacing"))


@dataclass
class CameraSetup:
    """Body / lens / aperture. All three default to auto (``None``)."""

    camera_model: str | None = None
    camera_lens: str | None = None
    camera_aperture: str | None = None

    def __post_init__(self) -> None:
        self.camera_model = _check(self.camera_model, CAMERA_BODIES, "camera_model")
        self.camera_lens = _check(self.camera_lens, LENSES, "camera_lens")
        self.camera_aperture = _check(self.camera_aperture, APERTURES, "camera_aperture")

    def is_auto(self) -> bool:
        return (
            self.camera_model is None
            and self.camera_lens is None
            and self.camera_aperture is None
        )

    def to_dict(self) -> dict:
        return {
            "camera_model": self.camera_model,
            "camera_lens": self.camera_lens,
            "camera_aperture": self.camera_aperture,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CameraSetup":
        _reject_unknown(
            cls.__name__, data, ("camera_model", "camera_lens", "camera_aperture")
        )
        return cls(
            camera_model=data.get("camera_model"),
            camera_lens=data.get("camera_lens"),
            camera_aperture=data.get("camera_aperture"),
        )


@dataclass
class LightingSetup:
    """One named look, or auto."""

    light: str | None = None

    def __post_init__(self) -> None:
        self.light = _check(self.light, LIGHTING_LOOKS, "light")

    def is_auto(self) -> bool:
        return self.light is None

    def to_dict(self) -> dict:
        return {"light": self.light}

    @classmethod
    def from_dict(cls, data: dict) -> "LightingSetup":
        _reject_unknown(cls.__name__, data, ("light",))
        return cls(light=data.get("light"))


@dataclass
class PaletteSetup:
    """One named preset, or auto. A user-created palette is free text and is not
    a member of :data:`COLOUR_PALETTES`; it is accepted here as-is."""

    color_palette: str | None = None
    custom: bool = False

    def __post_init__(self) -> None:
        if self.color_palette is None:
            self.custom = False
            return
        text = _ascii(self.color_palette).strip()
        if not text:
            raise ValueError("color_palette must be a non-empty name, or None for auto")
        # A preset must be an exact enum member. Anything else is treated as a
        # user-created palette, which the product genuinely supports -- but only
        # when the caller says so, so a typo'd preset is not silently accepted as
        # a custom palette.
        if text not in COLOUR_PALETTES and not self.custom:
            raise ValueError(
                f"color_palette={text!r} is not one of the {len(COLOUR_PALETTES)} "
                f"documented presets {COLOUR_PALETTES}; pass custom=True if this is "
                "a user-created palette"
            )
        self.color_palette = text

    def is_auto(self) -> bool:
        return self.color_palette is None

    def to_dict(self) -> dict:
        return {"color_palette": self.color_palette, "custom": self.custom}

    @classmethod
    def from_dict(cls, data: dict) -> "PaletteSetup":
        _reject_unknown(cls.__name__, data, ("color_palette", "custom"))
        return cls(
            color_palette=data.get("color_palette"),
            custom=bool(data.get("custom", False)),
        )


@dataclass
class EmotionDirection:
    """One character's emotion, applied as ``@character Emotion``.

    ``intensity`` is INVENTED -- see :data:`EMOTION_INTENSITY_MIN`.
    """

    character: str
    emotion: str | None = None
    intensity: float | None = None

    def __post_init__(self) -> None:
        self.character = _ascii(self.character).strip()
        if not self.character:
            raise ValueError("EmotionDirection.character must be a non-empty name")
        self.emotion = _check(self.emotion, EMOTIONS, "emotion")
        if self.intensity is None:
            return
        if self.emotion is None:
            raise ValueError(
                f"intensity={self.intensity!r} was given for {self.character!r} with "
                "no emotion; intensity is meaningless on auto"
            )
        value = float(self.intensity)
        if not (EMOTION_INTENSITY_MIN <= value <= EMOTION_INTENSITY_MAX):
            raise ValueError(
                f"intensity={value!r} is outside "
                f"{EMOTION_INTENSITY_MIN}..{EMOTION_INTENSITY_MAX}"
            )
        self.intensity = value

    def is_auto(self) -> bool:
        return self.emotion is None

    def to_dict(self) -> dict:
        return {
            "character": self.character,
            "emotion": self.emotion,
            "intensity": self.intensity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionDirection":
        _reject_unknown(cls.__name__, data, ("character", "emotion", "intensity"))
        if "character" not in data:
            raise ValueError("EmotionDirection.from_dict requires 'character'")
        return cls(
            character=data["character"],
            emotion=data.get("emotion"),
            intensity=data.get("intensity"),
        )


@dataclass
class DirectorPanel:
    """The five groups, composed. Every group starts on auto."""

    film: FilmSetup = field(default_factory=FilmSetup)
    camera: CameraSetup = field(default_factory=CameraSetup)
    lighting: LightingSetup = field(default_factory=LightingSetup)
    palette: PaletteSetup = field(default_factory=PaletteSetup)
    emotions: list[EmotionDirection] = field(default_factory=list)

    @classmethod
    def defaults(cls) -> "DirectorPanel":
        """A panel with every group on auto -- the state the product opens in."""
        return cls()

    def is_auto(self) -> bool:
        """True when the whole panel is untouched, so it contributes nothing.

        A direction that is itself auto (a character named but no emotion chosen)
        does **not** count as a change -- otherwise merely listing the cast would
        flip the panel off auto and it would start contributing.
        """
        return (
            self.film.is_auto()
            and self.camera.is_auto()
            and self.lighting.is_auto()
            and self.palette.is_auto()
            and all(direction.is_auto() for direction in self.emotions)
        )

    def direction_for(self, character: str) -> EmotionDirection | None:
        """The direction for ``character``, or ``None``. Case-insensitive."""
        wanted = _ascii(character).strip().casefold()
        for direction in self.emotions:
            if direction.character.casefold() == wanted:
                return direction
        return None

    def to_dict(self) -> dict:
        """Flat, and keyed by the **API field names**.

        Flat rather than nested so the director's-panel web mirror can diff this
        against its own state without a rename step. ``emotion`` is included even
        though the API has no such field, because the UI genuinely has the
        control and hiding it would understate the panel.
        """
        out: dict[str, Any] = {}
        out.update(self.film.to_dict())
        out.update(self.camera.to_dict())
        out.update(self.lighting.to_dict())
        out["color_palette"] = self.palette.color_palette
        out["emotion"] = [direction.to_dict() for direction in self.emotions]
        if self.palette.custom:
            # Emitted only when true, so a preset panel's dict is byte-identical
            # to what it was before this key existed. Without it the round-trip
            # is lossy: a user-created palette name is not a member of
            # COLOUR_PALETTES, so from_dict would reject its own to_dict output.
            out["custom"] = True
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "DirectorPanel":
        # ``custom`` is not an API field -- it is the local flag that says a
        # palette name is user-created rather than a documented preset. It is
        # accepted here because to_dict emits it and PaletteSetup.from_dict
        # reads it; rejecting it made the round-trip impossible.
        _reject_unknown(cls.__name__, data, PANEL_FIELDS + ("custom",))
        emotions = data.get("emotion") or []
        if not isinstance(emotions, (list, tuple)):
            raise ValueError("DirectorPanel.from_dict: 'emotion' must be a list")
        return cls(
            film=FilmSetup.from_dict(
                {k: data.get(k) for k in ("genre", "era", "pacing")}
            ),
            camera=CameraSetup.from_dict(
                {
                    k: data.get(k)
                    for k in ("camera_model", "camera_lens", "camera_aperture")
                }
            ),
            lighting=LightingSetup.from_dict({"light": data.get("light")}),
            palette=PaletteSetup.from_dict(
                {
                    "color_palette": data.get("color_palette"),
                    "custom": bool(data.get("custom", False)),
                }
            ),
            emotions=[EmotionDirection.from_dict(e) for e in emotions],
        )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def panel_prompt_fragment(panel: DirectorPanel) -> str:
    """The panel's contribution to the prompt: only non-auto groups, ASCII only.

    A fully-auto panel returns ``""`` -- it must not add a single character, or
    "auto" would stop meaning "the model decides".
    """
    bits: list[str] = []
    if panel.film.genre is not None:
        bits.append(f"genre {panel.film.genre}")
    if panel.film.era is not None:
        bits.append(f"era {panel.film.era}")
    if panel.film.pacing is not None:
        bits.append(f"pacing {panel.film.pacing}")
    if panel.camera.camera_model is not None:
        bits.append(f"camera {panel.camera.camera_model}")
    if panel.camera.camera_lens is not None:
        bits.append(f"lens {panel.camera.camera_lens}")
    if panel.camera.camera_aperture is not None:
        bits.append(f"aperture {panel.camera.camera_aperture}")
    if panel.lighting.light is not None:
        bits.append(f"lighting {panel.lighting.light}")
    if panel.palette.color_palette is not None:
        bits.append(f"palette {panel.palette.color_palette}")
    for direction in panel.emotions:
        if direction.is_auto():
            continue
        text = f"@{direction.character} {direction.emotion}"
        if direction.intensity is not None:
            text += f" {direction.intensity:g}"
        bits.append(text)
    return _ascii(", ".join(bits))


def panel_conditioning(panel: DirectorPanel) -> dict:
    """The panel as API-shaped conditioning: non-auto fields only.

    Keys are the API's own field names. ``camera_movement`` is absent by design:
    the move travels in the prompt, not the panel.
    """
    out: dict[str, Any] = {}
    if panel.film.genre is not None:
        out["genre"] = panel.film.genre
    if panel.film.era is not None:
        out["era"] = panel.film.era
    if panel.film.pacing is not None:
        out["pacing"] = panel.film.pacing
    if panel.camera.camera_model is not None:
        out["camera_model"] = panel.camera.camera_model
    if panel.camera.camera_lens is not None:
        out["camera_lens"] = panel.camera.camera_lens
    if panel.camera.camera_aperture is not None:
        out["camera_aperture"] = panel.camera.camera_aperture
    if panel.lighting.light is not None:
        out["light"] = panel.lighting.light
    if panel.palette.color_palette is not None:
        out["color_palette"] = panel.palette.color_palette
    active = [d.to_dict() for d in panel.emotions if not d.is_auto()]
    if active:
        out["emotion"] = active
    return out


def panel_summary(panel: DirectorPanel) -> str:
    """A one-line, ASCII-only summary. Says 'auto' out loud when nothing is set."""
    if panel.is_auto():
        return "director panel: all groups auto (contributes nothing)"
    parts: list[str] = []
    for label, value in (
        ("genre", panel.film.genre),
        ("era", panel.film.era),
        ("pacing", panel.film.pacing),
        ("camera", panel.camera.camera_model),
        ("lens", panel.camera.camera_lens),
        ("aperture", panel.camera.camera_aperture),
        ("light", panel.lighting.light),
        ("palette", panel.palette.color_palette),
    ):
        parts.append(f"{label}={value if value is not None else 'auto'}")
    for direction in panel.emotions:
        if direction.is_auto():
            parts.append(f"@{direction.character}=auto")
        elif direction.intensity is not None:
            parts.append(
                f"@{direction.character}={direction.emotion}@{direction.intensity:g}"
            )
        else:
            parts.append(f"@{direction.character}={direction.emotion}")
    return _ascii("director panel: " + ", ".join(parts))
