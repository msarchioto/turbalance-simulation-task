"""Visualize a Dragonfly topology as a grouped network diagram.

Groups are arranged in a circle. Within each group, routers are shown as a
cluster with hosts below them. Three link types are drawn with distinct styles:
  - Host-to-router (blue)
  - Intra-group / local (orange)
  - Inter-group / global (gray, dashed)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection


COLORS = {
    "host": "#4A90D9",
    "router": "#E8913A",
    "host_link": "#8BBBE0",
    "local_link": "#E8913A",
    "global_link": "#999999",
}


def _parse_topology(
    links: list[list[int]],
    num_hosts: int | None = None,
    routers_per_group: int | None = None,
    num_groups: int | None = None,
) -> dict:
    """Derive Dragonfly structure from the link list.

    Identifies hosts (source-only nodes), routers (everything else),
    and classifies links into host, local (same group), and global
    (cross-group) categories.
    """
    all_ids: set[int] = set()
    for src, dst, _ in links:
        all_ids.add(src)
        all_ids.add(dst)

    src_set = {src for src, _, _ in links}
    dst_set = {dst for _, dst, _ in links}

    hosts = sorted(src_set - dst_set)
    # Routers connect to hosts (appear as dst of host links) and to each other
    routers = sorted(all_ids - set(hosts))

    if not routers:
        return {"hosts": hosts, "routers": [], "groups": [], "host_links": [],
                "local_links": [], "global_links": []}

    router_set = set(routers)
    host_set = set(hosts)

    # Router-to-router links where both are routers.
    rtr_links = [(s, d, b) for s, d, b in links if s in router_set and d in router_set]
    host_links = [(s, d, b) for s, d, b in links if s in host_set]

    # Fast path: use explicit generator metadata when available.
    if (
        num_hosts is not None
        and routers_per_group is not None
        and num_groups is not None
        and num_hosts >= 0
        and routers_per_group > 0
        and num_groups > 0
    ):
        a = routers_per_group
        expected_router_count = a * num_groups
        if expected_router_count == len(routers):
            router_id_start = num_hosts
            groups = [
                list(range(router_id_start + gi * a, router_id_start + (gi + 1) * a))
                for gi in range(num_groups)
            ]
            group_of = {r: gi for gi, grp in enumerate(groups) for r in grp}
            local_links = [
                (s, d, b)
                for s, d, b in rtr_links
                if group_of.get(s) == group_of.get(d)
            ]
            global_links = [
                (s, d, b)
                for s, d, b in rtr_links
                if group_of.get(s) != group_of.get(d)
            ]
            return {
                "hosts": hosts,
                "routers": routers,
                "groups": groups,
                "group_of": group_of,
                "host_links": host_links,
                "local_links": local_links,
                "global_links": global_links,
            }

    # Group by bandwidth: local links are typically at base link_bandwidth,
    # global links too, but local links connect routers within a group.
    # We use connectivity: in a fully-connected group, local links form cliques.
    # Heuristic: find connected components treating ALL router-router links,
    # then separate local vs global based on group membership.

    # Actually, we need to distinguish local from global first.
    # In Dragonfly, intra-group routers form a clique. We can detect cliques
    # by checking which routers share the most neighbors.

    # Simpler approach: since we know hosts are [0..N-1] and routers are
    # [N..N+total-1], and routers are laid out as group*a + router_in_group,
    # we can infer group size from the link pattern.

    # Find group size (a) by looking at the smallest router ID's clique
    adj: dict[int, set[int]] = {r: set() for r in routers}
    for s, d, _ in rtr_links:
        adj[s].add(d)
        adj[d].add(s)

    # In a Dragonfly, each router connects to (a-1) local routers and h
    # global routers. Local routers form a clique (all mutual neighbors).
    # Global connections don't form cliques across groups.

    # Detect cliques via union-find on mutual-neighbor pairs
    for s, d, _ in rtr_links:
        # Two routers are in the same group if they share many mutual neighbors
        mutual = adj[s] & adj[d]
        # In a fully-connected group of size a, two members share (a-2) mutual
        # neighbors within the group. For a>=3 this is >=1.
        # For a=2, mutual neighbors within group = 0, but they're still connected.
        # Use degree-based heuristic: local neighbors have higher mutual count.
        pass

    # Fallback: assume routers are numbered sequentially by group.
    # Infer group size from the first router's local connectivity.
    first_router = routers[0]
    # Count consecutive routers that are all mutually connected (clique)
    a = 1
    for i in range(1, len(routers)):
        candidate = routers[i]
        # Check if candidate is connected to all routers[0..i-1]
        is_clique = all(routers[j] in adj[candidate] for j in range(i))
        if is_clique:
            a += 1
        else:
            break

    # Build groups
    groups: list[list[int]] = []
    for i in range(0, len(routers), a):
        groups.append(routers[i:i + a])

    group_of: dict[int, int] = {}
    for gi, grp in enumerate(groups):
        for r in grp:
            group_of[r] = gi

    local_links = [(s, d, b) for s, d, b in rtr_links if group_of.get(s) == group_of.get(d)]
    global_links = [(s, d, b) for s, d, b in rtr_links if group_of.get(s) != group_of.get(d)]

    return {
        "hosts": hosts,
        "routers": routers,
        "groups": groups,
        "group_of": group_of,
        "host_links": host_links,
        "local_links": local_links,
        "global_links": global_links,
    }


def visualize_topology(
    links: list[list[int]],
    output_path: Path,
    title: str = "Dragonfly Topology",
    num_hosts: int | None = None,
    routers_per_group: int | None = None,
    num_groups: int | None = None,
) -> None:
    topo = _parse_topology(
        links,
        num_hosts=num_hosts,
        routers_per_group=routers_per_group,
        num_groups=num_groups,
    )
    hosts = topo["hosts"]
    routers = topo["routers"]
    groups: list[list[int]] = topo["groups"]
    group_of: dict[int, int] = topo.get("group_of", {})

    if not groups:
        return

    g = len(groups)
    a = len(groups[0]) if groups else 1

    # Layout: groups in a circle, routers within each group in a small row,
    # hosts below their router.
    circle_radius = max(3.0, g * 0.8)
    intra_spacing = 0.4
    host_drop = 1.0

    positions: dict[int, tuple[float, float]] = {}

    for gi, grp in enumerate(groups):
        angle = 2 * math.pi * gi / g - math.pi / 2
        cx = circle_radius * math.cos(angle)
        cy = circle_radius * math.sin(angle)

        group_width = (a - 1) * intra_spacing
        for ri, rtr in enumerate(grp):
            rx = cx + (ri - (a - 1) / 2) * intra_spacing
            ry = cy
            positions[rtr] = (rx, ry)

    # Place hosts below their connected router
    router_host_count: dict[int, int] = {}
    host_router_map: dict[int, int] = {}
    for s, d, _ in topo["host_links"]:
        host_router_map[s] = d
        router_host_count[d] = router_host_count.get(d, 0) + 1

    router_host_placed: dict[int, int] = {}
    for h in hosts:
        rtr = host_router_map.get(h)
        if rtr is None or rtr not in positions:
            continue
        rx, ry = positions[rtr]
        placed = router_host_placed.get(rtr, 0)
        total = router_host_count.get(rtr, 1)
        host_spacing = max(0.35, min(0.7, intra_spacing * 1.5))
        hx = rx + (placed - (total - 1) / 2) * host_spacing
        hy = ry - host_drop
        positions[h] = (hx, hy)
        router_host_placed[rtr] = placed + 1

    # Figure sizing
    all_x = [p[0] for p in positions.values()]
    all_y = [p[1] for p in positions.values()]
    x_range = max(all_x) - min(all_x) if all_x else 4
    y_range = max(all_y) - min(all_y) if all_y else 4
    fig_width = max(8, x_range * 1.4)
    fig_height = max(6, y_range * 1.4)
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))

    # Draw links (back to front: global, local, host)
    def _collect_lines(link_list: list) -> list:
        segs = []
        for s, d, _ in link_list:
            if s in positions and d in positions:
                segs.append([positions[s], positions[d]])
        return segs

    global_segs = _collect_lines(topo["global_links"])
    local_segs = _collect_lines(topo["local_links"])
    host_segs = _collect_lines(topo["host_links"])

    if global_segs:
        lc = LineCollection(global_segs, colors=COLORS["global_link"],
                            linewidths=3.0, alpha=0.4)
        ax.add_collection(lc)
    if local_segs:
        lc = LineCollection(local_segs, colors=COLORS["local_link"],
                            linewidths=4.0, alpha=0.7)
        ax.add_collection(lc)
    if host_segs:
        lc = LineCollection(host_segs, colors=COLORS["host_link"],
                            linewidths=3.0, alpha=0.6)
        ax.add_collection(lc)

    # Draw group backgrounds
    for gi, grp in enumerate(groups):
        xs = [positions[r][0] for r in grp if r in positions]
        ys = [positions[r][1] for r in grp if r in positions]
        # Include hosts in the bounding box
        for h in hosts:
            if host_router_map.get(h) in set(grp) and h in positions:
                xs.append(positions[h][0])
                ys.append(positions[h][1])
        if not xs:
            continue
        pad = 0.35
        rect = plt.Rectangle(
            (min(xs) - pad, min(ys) - pad),
            max(xs) - min(xs) + 2 * pad,
            max(ys) - min(ys) + 2 * pad,
            linewidth=1, edgecolor="#CCCCCC", facecolor="#F8F8F8",
            alpha=0.4, zorder=1,
        )
        ax.add_patch(rect)
        ax.text(
            (min(xs) + max(xs)) / 2, max(ys) + pad + 0.15,
            f"G{gi}", ha="center", va="bottom", fontsize=6, color="#888",
        )

    # Draw nodes
    node_size_host = min(20, max(5, 150 / max(len(hosts), 1)))
    node_size_router = min(30, max(10, 200 / max(len(routers), 1)))

    for h in hosts:
        if h in positions:
            x, y = positions[h]
            ax.plot(x, y, "s", color=COLORS["host"], markersize=node_size_host, zorder=5)

    for r in routers:
        if r in positions:
            x, y = positions[r]
            ax.plot(x, y, "o", color=COLORS["router"], markersize=node_size_router, zorder=5)

    # Labels for small topologies
    if len(hosts) <= 32:
        for h in hosts:
            if h in positions:
                x, y = positions[h]
                ax.annotate(str(h), (x, y), textcoords="offset points",
                            xytext=(0, -10), ha="center", fontsize=4, color="#666")
    if len(routers) <= 32:
        for r in routers:
            if r in positions:
                x, y = positions[r]
                ax.annotate(str(r), (x, y), textcoords="offset points",
                            xytext=(0, -10), ha="center", fontsize=5, color="#666")

    # Legend
    legend_items = [
        mpatches.Patch(color=COLORS["host"], label=f"Hosts ({len(hosts)})"),
        mpatches.Patch(color=COLORS["router"], label=f"Routers ({len(routers)})"),
        mpatches.Patch(color=COLORS["local_link"], label=f"Local links ({len(topo['local_links'])})"),
        mpatches.Patch(color=COLORS["global_link"], label=f"Global links ({len(topo['global_links'])})"),
    ]
    ax.legend(handles=legend_items, loc="upper right", fontsize=7, framealpha=0.9)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    margin = 1.5
    ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
    ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
    ax.set_aspect("equal")
    ax.axis("off")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dragonfly-visualize",
        description="Render a Dragonfly topology JSON as a grouped network diagram (PNG).",
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
    title = args.title or f"Dragonfly Topology ({input_path.stem})"

    visualize_topology(links, output_path, title)
    print(f"Diagram written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
