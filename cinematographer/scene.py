"""Cinematographer — scene-level rules that need more than the framed subject.

A port of the reference ``SceneFramingExtras``.

Three rules that compare *all* placed entities in frame, not just the key subject:

* **size_importance** (#34, Hitchcock) — the beat's key subject should be the
  largest element; flag when a minor prop or character out-sizes it.
* **foreground_occlusion** (#35, "dirty" frame) — a nearer element hugging a frame
  edge that does *not* cover the face reads as depth / intimacy / voyeurism.
  Informational.
* **eyeline** (#26, two-shot) — the primary subject should look toward the other.

**Simplification, stated plainly.** The reference implementation derives entity
half-extents from a full dimension resolver. This port
uses documented role-derived defaults instead, overridable per entity. That
changes absolute areas but not the *comparison* the rules make, which is what
matters. Do not read a size_importance ratio from this port as identical to the
reference service's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import (
    CamPose,
    FramingScore,
    Subject,
    Vec3,
    clamp,
    dot,
    eye_pt,
    norm,
    projector,
    round3,
)

#: Default half-extents (x, y, z) in metres, by role. Person-sized by default.
DEFAULT_HALF_EXTENTS: dict[str, Vec3] = {
    "character": (0.25, 0.90, 0.15),
    "person": (0.25, 0.90, 0.15),
    "prop": (0.30, 0.30, 0.30),
    "furniture": (0.60, 0.40, 0.60),
    "vehicle": (0.90, 0.70, 2.00),
}


@dataclass
class PlacedEntity:
    """An entity placed in the scene, with a world transform."""

    role: str
    translate: Vec3
    scale: float = 1.0
    rotate_y: float = 0.0
    half_extents: Vec3 | None = None

    def to_dict(self) -> dict:
        d = {
            "role": self.role,
            "translate": list(self.translate),
            "scale": self.scale,
            "rotate_y": self.rotate_y,
        }
        if self.half_extents is not None:
            d["half_extents"] = list(self.half_extents)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PlacedEntity":
        he = d.get("half_extents")
        return cls(
            role=str(d.get("role", "prop")),
            translate=tuple(d["translate"]),  # type: ignore[arg-type]
            scale=float(d.get("scale", 1.0)),
            rotate_y=float(d.get("rotate_y", 0.0)),
            half_extents=tuple(he) if he else None,  # type: ignore[arg-type]
        )


@dataclass
class SceneGraph:
    """The minimal scene the extras need: a key subject, other characters, props."""

    characters: list[PlacedEntity] = field(default_factory=list)
    props: list[PlacedEntity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "characters": [c.to_dict() for c in self.characters],
            "props": [p.to_dict() for p in self.props],
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "SceneGraph":
        if not d:
            return cls()
        return cls(
            characters=[PlacedEntity.from_dict(c) for c in d.get("characters", [])],
            props=[PlacedEntity.from_dict(p) for p in d.get("props", [])],
        )


def entity_half_extents(e: PlacedEntity) -> Vec3:
    """Role-derived half-extents, scaled. See the module docstring's caveat."""
    scale = e.scale if e.scale > 0 else 1.0
    hx, hy, hz = e.half_extents or DEFAULT_HALF_EXTENTS.get(
        e.role.lower(), DEFAULT_HALF_EXTENTS["prop"]
    )
    return (hx * scale, hy * scale, hz * scale)


@dataclass
class EntityBBox:
    """An entity's projected screen bounds plus its mean depth."""

    min_x: float = math.inf
    max_x: float = -math.inf
    min_y: float = math.inf
    max_y: float = -math.inf
    depth: float = math.inf
    in_front: bool = False
    area: float = 0.0


def project_entity_bbox(proj, e: PlacedEntity) -> EntityBBox:
    """Project an entity's world bounding box through the camera to NDC bounds."""
    hx, hy, hz = entity_half_extents(e)
    cx, cz = e.translate[0], e.translate[2]
    cy = e.translate[1] + hy  # base on the floor, box centred at mid-height

    bb = EntityBBox()
    any_in = False
    for sx in (-hx, hx):
        for sy in (-hy, hy):
            for sz in (-hz, hz):
                x, y, d, in_front = proj((cx + sx, cy + sy, cz + sz))
                if not in_front:
                    continue
                any_in = True
                bb.min_x, bb.max_x = min(bb.min_x, x), max(bb.max_x, x)
                bb.min_y, bb.max_y = min(bb.min_y, y), max(bb.max_y, y)
                bb.depth = min(bb.depth, d)
    bb.in_front = any_in
    if any_in:
        w = min(bb.max_x, 1.0) - max(bb.min_x, -1.0)
        h = min(bb.max_y, 1.0) - max(bb.min_y, -1.0)
        bb.area = max(0.0, w) * max(0.0, h)
    return bb


def scene_framing_extras(
    scene: SceneGraph | None,
    cam: CamPose,
    key_subject: Subject,
) -> list[FramingScore]:
    """Compute the multi-entity rules (#34, #35, #26) for a shot as seen from ``cam``."""
    if scene is None:
        return []
    proj = projector(cam)

    # The key subject's own box, built from its person extents at its base.
    key_ent = PlacedEntity(
        role="character",
        translate=key_subject.base,
        scale=key_subject.height / 1.8,
        rotate_y=key_subject.facing_yaw_deg,
    )
    key = project_entity_bbox(proj, key_ent)
    key_area = max(key.area, 1e-4)

    # The eye anchor in NDC, for the "face not covered" test in #35.
    ex, ey, key_depth, _ = proj(eye_pt(key_subject))

    # Other entities: props plus any character that is not the key subject.
    others: list[PlacedEntity] = list(scene.props)
    others.extend(scene.characters[1:])

    scores: list[FramingScore] = []

    # #34 size = importance: does any minor element out-size the key subject?
    max_ratio, biggest = 0.0, ""
    for e in others:
        bb = project_entity_bbox(proj, e)
        if not bb.in_front:
            continue
        r = bb.area / key_area
        if r > max_ratio:
            max_ratio, biggest = r, e.role
    size_pass = max_ratio <= 1.0
    scores.append(
        FramingScore(
            rule="size_importance",
            passed=size_pass,
            value=round3(max_ratio),
            target="key subject is the largest element (ratio \u2264 1)",
            weight=0.4,
            correction=""
            if size_pass
            else f"a {biggest} out-sizes the key subject - resize/reposition so the subject dominates",
        )
    )

    # #35 foreground occlusion (dirty frame). Informational.
    dirty = False
    for e in scene.props:
        bb = project_entity_bbox(proj, e)
        if not bb.in_front or bb.depth >= key_depth:
            continue  # must be in front of the subject
        edge = bb.min_x < -0.4 or bb.max_x > 0.4 or bb.max_y > 0.6
        covers_face = bb.min_x <= ex <= bb.max_x and bb.min_y <= ey <= bb.max_y
        if edge and not covers_face:
            dirty = True
            break
    scores.append(
        FramingScore(
            rule="foreground_occlusion",
            passed=True,
            value=1.0 if dirty else 0.0,
            target="foreground element present (depth / voyeur cue)"
            if dirty
            else "clean frame",
            weight=0.0,
        )
    )

    # #26 eyeline (two-shot): the primary subject should look toward the other.
    if len(scene.characters) >= 2:
        a, b = scene.characters[0].translate, scene.characters[1].translate
        dir_ab = norm((b[0] - a[0], 0.0, b[2] - a[2]))
        yaw = math.radians(scene.characters[0].rotate_y)
        gaze_a = norm((math.sin(yaw), 0.0, math.cos(yaw)))
        ang = math.degrees(math.acos(clamp(dot(gaze_a, dir_ab), -1.0, 1.0)))
        eye_pass = ang < 45
        scores.append(
            FramingScore(
                rule="eyeline",
                passed=eye_pass,
                value=round3(ang),
                target="primary subject's gaze leads to the other (<45\u00b0)",
                weight=0.4,
                correction=""
                if eye_pass
                else "turn the primary subject to look toward the other (eyeline)",
            )
        )
    return scores
