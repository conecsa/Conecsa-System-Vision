#!/usr/bin/env python3
"""Render ``docs/communication.png`` — the service communication diagram.

The PNG embedded in the README and ``docs/architecture.md`` has no other
source, so it kept going stale across the refactor (``os`` → ``os-base``,
``node-red`` → ``flow``, ``app`` → WASM-only ``system-vision``) and the
``hub-vision``/``training-service`` additions. This script *is* the source —
edit it and re-run to regenerate the image:

    python3 docs/communication-diagram.py     # writes docs/communication.png

Pure matplotlib (already in the docs/dev venv); no extra tooling needed.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ── Palette (dark, to match the previous diagram) ────────────────────────────
BG = "#14171c"
GRID = "#20262e"
BOX_FC = "#1b1f26"
BOX_EC = "#5fc9c9"
TITLE = "#9cc2ff"
SUBTITLE = "#7f8a99"
LABEL = "#9aa4b2"
ARROW = "#6b7686"
OFF_EC = "#3a4250"

XLIM, YLIM = 14.0, 10.0
HW, HH = 1.55, 0.62  # default box half-width / half-height


# (key) -> (cx, cy, title, subtitle)
BOXES = {
    "training": (2.7, 8.7, "training-service", "datasets · SAM3 · YOLO"),
    "os-base": (7.0, 8.7, "os-base", "hardware agent"),
    "inference": (2.4, 5.8, "inference-service", "consumer"),
    "gateway": (7.0, 5.8, "api-gateway", "HTTP ↔ gRPC / SHM"),
    "webcam": (11.6, 5.8, "webcam-server", "producer"),
    "system-vision": (4.3, 2.4, "system-vision", "web / WASM"),
    "flow": (8.2, 2.4, "flow", "Node-RED"),
    "hub": (12.1, 2.4, "hub-vision", "fleet hub"),
}

# (a, b, label, style)  — style: "bi" double-headed, "uni" one-way a→b,
#                                 "mdns" dashed one-way.
EDGES = [
    ("os-base", "gateway", "gRPC :50051", "bi"),
    ("training", "gateway", "gRPC :50071", "bi"),
    ("inference", "gateway", "gRPC :50061\nProcessed SHM", "bi"),
    ("webcam", "gateway", "Camera SHM", "uni"),  # producer → consumers
    ("system-vision", "gateway", "HTTP / SSE / MJPEG", "bi"),
    ("flow", "gateway", "HTTP / SSE", "bi"),
    ("flow", "hub", "HTTP detections", "uni"),
    ("hub", "gateway", "mDNS discovery", "mdns"),
]


def _half(key: str) -> tuple[float, float]:
    # hub-vision sits in the off-device frame; everything else uses defaults.
    return (HW, HH)


def _boundary(key: str, tx: float, ty: float) -> tuple[float, float]:
    """Point on *key*'s box border along the ray toward (tx, ty)."""
    cx, cy = BOXES[key][0], BOXES[key][1]
    hw, hh = _half(key)
    dx, dy = tx - cx, ty - cy
    sx = hw / abs(dx) if dx else float("inf")
    sy = hh / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _draw_box(ax, key: str) -> None:
    cx, cy, title, sub = BOXES[key]
    hw, hh = _half(key)
    ax.add_patch(
        FancyBboxPatch(
            (cx - hw, cy - hh),
            2 * hw,
            2 * hh,
            boxstyle="round,pad=0.02,rounding_size=0.18",
            linewidth=1.6,
            edgecolor=BOX_EC,
            facecolor=BOX_FC,
            mutation_aspect=1.0,
            zorder=3,
        )
    )
    ax.text(cx, cy + 0.12, title, color=TITLE, ha="center", va="center",
            fontsize=11, fontweight="bold", zorder=4)
    ax.text(cx, cy - 0.24, sub, color=SUBTITLE, ha="center", va="center",
            fontsize=8.5, zorder=4)


def _draw_edge(ax, a: str, b: str, label: str, style: str) -> None:
    ax_, ay_ = BOXES[a][0], BOXES[a][1]
    bx_, by_ = BOXES[b][0], BOXES[b][1]
    pa = _boundary(a, bx_, by_)
    pb = _boundary(b, ax_, ay_)

    dashed = style == "mdns"
    arrowstyle = "<|-|>" if style == "bi" else "-|>"

    ax.add_patch(
        FancyArrowPatch(
            pa,
            pb,
            arrowstyle=arrowstyle,
            mutation_scale=12,
            linewidth=1.4,
            linestyle="--" if dashed else "-",
            color=ARROW,
            shrinkA=0,
            shrinkB=0,
            zorder=2,
        )
    )
    mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
    ax.text(
        mx, my, label, color=LABEL, ha="center", va="center", fontsize=8,
        zorder=5,
        bbox=dict(boxstyle="round,pad=0.18", fc=BG, ec="none"),
    )


def main() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 8.0), dpi=100)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, XLIM)
    ax.set_ylim(0, YLIM)
    ax.set_aspect("auto")
    ax.axis("off")

    # Faint grid, like the original.
    for x in range(1, int(XLIM)):
        ax.axvline(x, color=GRID, linewidth=0.6, zorder=0)
    for y in range(1, int(YLIM)):
        ax.axhline(y, color=GRID, linewidth=0.6, zorder=0)

    # Off-device frame around the fleet hub.
    hx, hy = BOXES["hub"][0], BOXES["hub"][1]
    ax.add_patch(
        FancyBboxPatch(
            (hx - HW - 0.35, hy - HH - 0.55),
            2 * HW + 0.7,
            2 * HH + 1.0,
            boxstyle="round,pad=0.02,rounding_size=0.18",
            linewidth=1.1,
            linestyle="--",
            edgecolor=OFF_EC,
            facecolor="none",
            zorder=1,
        )
    )
    ax.text(hx, hy + HH + 0.30, "off-device · hub host", color=SUBTITLE,
            ha="center", va="center", fontsize=8, style="italic", zorder=4)

    for key in BOXES:
        _draw_box(ax, key)
    for a, b, label, style in EDGES:
        _draw_edge(ax, a, b, label, style)

    ax.text(0.4, 9.6, "Communication between services", color=SUBTITLE,
            ha="left", va="center", fontsize=9.5, style="italic")

    out = Path(__file__).resolve().parent / "communication.png"
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
