"""Visualize a CLOS topology as a layered network diagram."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection


COLORS = {
    "host": "#4A90D9",
    "leaf": "#E8913A",
    "spine": "#50B86C",
    "host_link": "#8BBBE0",
    "uplink": "#C4C4C4",
}

LAYER_Y = {"spine": 3.0, "leaf": 2.0, "host": 1.0}


def _parse_topology(links: list[list[int]]) -> dict:
    """Derive topology structure from the link list."""
    all_ids: set[int] = set()
    for src, dst, _ in links:
        all_ids.add(src)
        all_ids.add(dst)

    # Hosts are sources of host-leaf links (lowest IDs)
    # Spines are destinations of leaf-spine links (highest IDs)
    # Leafs are in between
    src_only = {src for src, dst, _ in links} - {dst for _, dst, _ in links}
    dst_only = {dst for _, dst, _ in links} - {src for src, dst, _ in links}
    middle = all_ids - src_only - dst_only

    hosts = sorted(src_only)
    spines = sorted(dst_only)
    leafs = sorted(middle)

    return {"hosts": hosts, "leafs": leafs, "spines": spines}


def _place_nodes(ids: list[int], y: float, x_span: float) -> dict[int, tuple[float, float]]:
    """Distribute nodes evenly across x_span at height y."""
    n = len(ids)
    if n == 0:
        return {}
    if n == 1:
        return {ids[0]: (x_span / 2, y)}
    spacing = x_span / (n - 1) if n > 1 else 0
    return {nid: (i * spacing, y) for i, nid in enumerate(ids)}


def visualize_topology(
    links: list[list[int]],
    output_path: Path,
    title: str = "2-Layer CLOS Topology",
) -> None:
    topo = _parse_topology(links)
    hosts, leafs, spines = topo["hosts"], topo["leafs"], topo["spines"]

    max_layer_width = max(len(hosts), len(leafs), len(spines))
    x_span = max(max_layer_width * 0.5, 4.0)

    positions: dict[int, tuple[float, float]] = {}
    positions.update(_place_nodes(spines, LAYER_Y["spine"], x_span))
    positions.update(_place_nodes(leafs, LAYER_Y["leaf"], x_span))
    positions.update(_place_nodes(hosts, LAYER_Y["host"], x_span))

    fig_width = max(x_span * 1.2, 8)
    fig_height = 6
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))

    # Draw links
    host_lines = []
    uplink_lines = []
    for src, dst, bw in links:
        if src in positions and dst in positions:
            p1, p2 = positions[src], positions[dst]
            if src in set(hosts):
                host_lines.append([p1, p2])
            else:
                uplink_lines.append([p1, p2])

    if host_lines:
        lc = LineCollection(host_lines, colors=COLORS["host_link"], linewidths=1.5, alpha=0.6)
        ax.add_collection(lc)
    if uplink_lines:
        lc = LineCollection(uplink_lines, colors=COLORS["uplink"], linewidths=2.0, alpha=0.55)
        ax.add_collection(lc)

    # Draw nodes
    node_size_host = min(25, max(8, 200 / max(len(hosts), 1)))
    node_size_switch = min(35, max(15, 300 / max(len(leafs), len(spines), 1)))

    for nid in hosts:
        x, y = positions[nid]
        ax.plot(x, y, "s", color=COLORS["host"], markersize=node_size_host, zorder=5)

    for nid in leafs:
        x, y = positions[nid]
        ax.plot(x, y, "o", color=COLORS["leaf"], markersize=node_size_switch, zorder=5)

    for nid in spines:
        x, y = positions[nid]
        ax.plot(x, y, "D", color=COLORS["spine"], markersize=node_size_switch, zorder=5)

    # Labels for small topologies
    if len(hosts) <= 32:
        for nid in hosts:
            x, y = positions[nid]
            ax.annotate(str(nid), (x, y), textcoords="offset points",
                        xytext=(0, -12), ha="center", fontsize=5, color="#666")
    if len(leafs) <= 32:
        for nid in leafs:
            x, y = positions[nid]
            ax.annotate(str(nid), (x, y), textcoords="offset points",
                        xytext=(0, -12), ha="center", fontsize=6, color="#666")
    if len(spines) <= 32:
        for nid in spines:
            x, y = positions[nid]
            ax.annotate(str(nid), (x, y), textcoords="offset points",
                        xytext=(0, -12), ha="center", fontsize=6, color="#666")

    # Legend
    legend_items = [
        mpatches.Patch(color=COLORS["host"], label=f"Hosts ({len(hosts)})"),
        mpatches.Patch(color=COLORS["leaf"], label=f"Leaf switches ({len(leafs)})"),
        mpatches.Patch(color=COLORS["spine"], label=f"Spine switches ({len(spines)})"),
    ]
    ax.legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.9)

    # Layer labels
    label_x = -x_span * 0.08 - 0.5
    ax.text(label_x, LAYER_Y["spine"], "Spine", ha="right", va="center", fontsize=10, fontweight="bold")
    ax.text(label_x, LAYER_Y["leaf"], "Leaf", ha="right", va="center", fontsize=10, fontweight="bold")
    ax.text(label_x, LAYER_Y["host"], "Hosts", ha="right", va="center", fontsize=10, fontweight="bold")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    left_margin = label_x - 1.0
    ax.set_xlim(left_margin, x_span + 1)
    ax.set_ylim(0.5, 3.5)
    ax.set_aspect("auto")
    ax.axis("off")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clos-visualize",
        description="Render a CLOS topology JSON as a layered network diagram (PNG).",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input topology JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path (default: same name as input with .png extension)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Diagram title",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path: Path = args.input

    if not input_path.exists():
        print(f"ERROR: {input_path} not found", file=sys.stderr)
        return 1

    with open(input_path) as f:
        links = json.load(f)

    output_path = args.output or input_path.with_suffix(".png")
    title = args.title or f"2-Layer CLOS Topology ({input_path.stem})"

    visualize_topology(links, output_path, title)
    print(f"Diagram written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
