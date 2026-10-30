"""ComfyUI-Cinematographer — pack root.

ComfyUI loads a custom node pack by executing ``<pack_root>/__init__.py`` and reading
``NODE_CLASS_MAPPINGS`` from the resulting module. It does **not** recurse into
subdirectories (``init_external_custom_nodes`` uses ``os.listdir``), so this file must
exist at the pack root and must re-export the mappings from the package below it.

The implementation lives in ``cinematographer/``, a sibling of this file.

**This repository is the pack root.** ``__init__.py`` sits at the top level, so the
standard ComfyUI install works unchanged::

    git clone https://github.com/nathaniel-magieva/ComfyUI-Cinematographer \
        ComfyUI/custom_nodes/ComfyUI-Cinematographer

The one thing to get right is that whatever directory you put in ``custom_nodes/`` must
contain this file at its top level. ComfyUI does not recurse, so a checkout that keeps
the pack one level down (``<dir>/app/__init__.py``) fails with
``FileNotFoundError: '<dir>/__init__.py'`` rather than a clear message.

Verified by replaying ComfyUI's exact loader (``os.listdir`` with no recursion, then
``spec_from_file_location(pack_root/__init__.py)``) against a clean copy: this layout
loads 18 nodes. See ``README.md`` for the same note in install form.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Make the package importable regardless of how ComfyUI put this directory on the
# path. ComfyUI inserts the pack root into sys.path, but being explicit costs nothing
# and survives being imported by a test harness or a linter.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from cinematographer import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except ImportError as exc:  # pragma: no cover - only hit on a broken checkout
    raise ImportError(
        "ComfyUI-Cinematographer: could not import the 'cinematographer' package from "
        f"{_HERE!r}. The pack directory should contain a 'cinematographer/' subdirectory. "
        "If you vendored this pack into a larger repository, make sure the directory you "
        "pointed ComfyUI at is the one that contains __init__.py (see README.md, "
        "'Install')."
    ) from exc

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

# ComfyUI reads these. WEB_DIRECTORY is optional; the director's panel is a standalone
# page under web/ and is not registered as a ComfyUI frontend extension, so it is
# deliberately not declared here.
__version__ = "0.1.0"
