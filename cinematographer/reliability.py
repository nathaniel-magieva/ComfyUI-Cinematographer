"""Cinematographer — the reliability zone, computed rather than hard-coded.

``comfy-reshoot`` shows a green/yellow/red reliability indicator. Ours computes
it from the view-steering model's training envelope, so the user can see *which
axis* left the envelope and by how much.

The envelope comes from CrossView-Warp (Cseti, Apache-2.0), an LTX 2.3 IC-LoRA
whose trained range is documented as **green within +/-45 degrees of azimuth**.
Distance does not behave as expected — CrossView-Warp *steers* the viewpoint, it
does not reproject it — so we grade azimuth and elevation and say so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .continuity import cam_azimuth_deg
from .geometry import CamPose, Subject, round3

#: Azimuth within this many degrees of the source view is inside the trained range.
GREEN_AZIMUTH_DEG = 45.0

#: Beyond green but within this, the model is extrapolating.
YELLOW_AZIMUTH_DEG = 60.0

#: Elevation beyond this leaves the trained range.
YELLOW_ELEVATION_DEG = 30.0

ZONES = ("green", "yellow", "red")


@dataclass
class ReliabilityZone:
    zone: str  # "green" | "yellow" | "red"
    reason: str
    azimuth_deg: float
    elevation_deg: float

    def to_dict(self) -> dict:
        return {
            "zone": self.zone,
            "reason": self.reason,
            "azimuth_deg": self.azimuth_deg,
            "elevation_deg": self.elevation_deg,
        }


def camera_reliability_zone(
    camera: CamPose,
    subject: Subject,
    azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
) -> ReliabilityZone:
    """Grade a requested camera pose against the view-steering training envelope.

    If ``azimuth_deg`` / ``elevation_deg`` are not supplied they are derived from
    the camera pose relative to the subject.
    """
    if azimuth_deg is None:
        azimuth_deg = cam_azimuth_deg(subject.base, camera.eye)
    if elevation_deg is None:
        eye_y = camera.eye[1]
        eye_height = subject.base[1] + 0.92 * subject.height
        horiz = max(
            1e-6,
            ((camera.eye[0] - subject.base[0]) ** 2 + (camera.eye[2] - subject.base[2]) ** 2)
            ** 0.5,
        )
        elevation_deg = math.degrees(math.atan2(eye_y - eye_height, horiz))

    az = abs(azimuth_deg)
    el = abs(elevation_deg)

    if az <= GREEN_AZIMUTH_DEG and el <= YELLOW_ELEVATION_DEG:
        return ReliabilityZone(
            "green",
            f"inside the trained range (azimuth {az:.0f} deg <= {GREEN_AZIMUTH_DEG:.0f} deg, "
            f"elevation {el:.0f} deg <= {YELLOW_ELEVATION_DEG:.0f} deg)",
            round3(azimuth_deg),
            round3(elevation_deg),
        )

    if az <= YELLOW_AZIMUTH_DEG and el <= YELLOW_ELEVATION_DEG:
        return ReliabilityZone(
            "yellow",
            f"extrapolating on azimuth ({az:.0f} deg > {GREEN_AZIMUTH_DEG:.0f} deg) - "
            "the model is guessing beyond its trained range",
            round3(azimuth_deg),
            round3(elevation_deg),
        )

    if az > YELLOW_AZIMUTH_DEG:
        reason = (
            f"azimuth {az:.0f} deg is beyond the trained range "
            f"({YELLOW_AZIMUTH_DEG:.0f} deg) - the hidden side will be invented"
        )
    else:
        reason = (
            f"elevation {el:.0f} deg is beyond the trained range "
            f"({YELLOW_ELEVATION_DEG:.0f} deg) - the hidden side will be invented"
        )
    return ReliabilityZone("red", reason, round3(azimuth_deg), round3(elevation_deg))
