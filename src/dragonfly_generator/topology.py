"""Core Dragonfly topology calculation and link generation.

Implements the canonical Dragonfly topology (Kim et al., 2008) with:
- Hierarchical structure: router -> group -> system
- Fully-connected intra-group (local) links
- Round-robin inter-group (global) wiring
- Host-to-router terminal connections

Parameters (from the paper):
    p -- terminals (hosts) per router
    a -- routers per group
    h -- global links per router
    k -- router radix = p * links_per_host + (a - 1) + h
    g -- number of groups = a * h + 1  (maximum-size)
    N -- total hosts = p * a * g
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DragonflyTopology:
    """Complete description of a Dragonfly topology."""

    num_hosts: int
    routers_per_group: int      # a
    num_groups: int              # g
    hosts_per_router: int        # p
    global_links_per_router: int # h
    ports_per_switch: int        # k
    links_per_host: int
    link_bandwidth: int
    links: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def total_routers(self) -> int:
        return self.routers_per_group * self.num_groups

    @property
    def host_id_range(self) -> tuple[int, int]:
        return (0, self.num_hosts - 1)

    @property
    def router_id_range(self) -> tuple[int, int]:
        start = self.num_hosts
        return (start, start + self.total_routers - 1)

    @property
    def router_ports_used(self) -> int:
        terminal = self.hosts_per_router * self.links_per_host
        local = self.routers_per_group - 1
        global_ = self.global_links_per_router
        return terminal + local + global_

    def summary(self) -> str:
        a = self.routers_per_group
        p = self.hosts_per_router
        h = self.global_links_per_router
        g = self.num_groups
        terminal_ports = p * self.links_per_host
        local_ports = a - 1
        host_bw = self.links_per_host * self.link_bandwidth

        lines = [
            "=== Dragonfly Topology ===",
            f"Hosts:              {self.num_hosts}",
            f"  IDs:              [{self.host_id_range[0]}, {self.host_id_range[1]}]",
            f"  Links/host:       {self.links_per_host} x {self.link_bandwidth}G "
            f"(aggregated: {host_bw}G)",
            f"Routers:            {self.total_routers}  (a={a}, g={g})",
            f"  IDs:              [{self.router_id_range[0]}, {self.router_id_range[1]}]",
            f"  Terminal ports:   {terminal_ports} (p={p}, links_per_host={self.links_per_host})",
            f"  Local ports:      {local_ports} (a-1={a - 1})",
            f"  Global ports:     {h}",
            f"  Ports used:       {self.router_ports_used}/{self.ports_per_switch}",
            f"Groups:             {g}",
            f"  Routers/group:    {a}",
            f"  Hosts/group:      {a * p}",
            f"  Intra-group links:{a * (a - 1) // 2} per group",
            f"Total links:        {len(self.links)}",
        ]
        return "\n".join(lines)

    def to_json(self) -> list[list[int]]:
        return [list(link) for link in self.links]

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)


def _validate_inputs(
    switch_throughput: int,
    nic_throughput: int,
    link_bandwidth: int,
    num_hosts: int,
) -> None:
    if switch_throughput <= 0 or nic_throughput <= 0 or link_bandwidth <= 0:
        raise ValueError("All throughput/bandwidth values must be positive")
    if num_hosts <= 0:
        raise ValueError("num_hosts must be positive")
    if switch_throughput % link_bandwidth != 0:
        raise ValueError(
            f"switch_throughput ({switch_throughput}) must be divisible by "
            f"link_bandwidth ({link_bandwidth})"
        )
    if nic_throughput % link_bandwidth != 0:
        raise ValueError(
            f"nic_throughput ({nic_throughput}) must be divisible by "
            f"link_bandwidth ({link_bandwidth})"
        )


def _find_best_config(
    ports_per_switch: int,
    links_per_host: int,
    num_hosts: int,
) -> tuple[int, int, int, int]:
    """Find (a, h, p, g) that accommodates num_hosts with minimum routers.

    Searches all valid (a, h, g) triples where:
        p = (k - (a-1) - h) / links_per_host  is a positive integer
        N = p * a * g >= num_hosts
        2 <= g <= a*h + 1

    Returns the configuration with minimum total routers (a * g),
    breaking ties by preferring configurations closer to the balanced
    ratio a = 2h, then by lower host overprovisioning.
    """
    k = ports_per_switch
    best: tuple[int, int, int, int] | None = None
    best_routers = float("inf")
    best_imbalance = float("inf")
    best_host_slack = float("inf")

    for h in range(1, k):
        for a in range(2, k):
            remaining = k - (a - 1) - h
            if remaining <= 0:
                break
            if remaining % links_per_host != 0:
                continue
            p = remaining // links_per_host
            if p < 1:
                continue

            g_max = a * h + 1
            for g in range(2, g_max + 1):
                # Inter-group links count is (a * g * h) / 2 and must be integral.
                if (a * g * h) % 2 != 0:
                    continue
                capacity = p * a * g
                if capacity < num_hosts:
                    continue

                total_routers = a * g
                # Use terminal channels per router (p * links_per_host) for balance.
                imbalance = abs(a - 2 * h) + abs(a - 2 * p * links_per_host)
                host_slack = capacity - num_hosts

                if (
                    (total_routers < best_routers)
                    or (
                        total_routers == best_routers
                        and imbalance < best_imbalance
                    )
                    or (
                        total_routers == best_routers
                        and imbalance == best_imbalance
                        and host_slack < best_host_slack
                    )
                ):
                    best = (a, h, p, g)
                    best_routers = total_routers
                    best_imbalance = imbalance
                    best_host_slack = host_slack

    if best is None:
        raise ValueError(
            f"No valid Dragonfly configuration found for {num_hosts} hosts "
            f"with {ports_per_switch}-port switches and {links_per_host} links/host. "
            f"Try fewer hosts or higher switch throughput."
        )

    return best


def _wire_global_links(
    a: int, g: int, h: int
) -> list[tuple[int, int]]:
    """Compute inter-group global links as (router_offset, router_offset) pairs.

    For maximum-size dragonfly (g = ah + 1), exactly one link connects each
    group pair. Links are distributed across routers so each router uses
    exactly h global ports.

    For smaller dragonflies (g < ah + 1), multiple links per group pair are
    created, still respecting per-router port budgets.

    Returns list of (src_router_offset, dst_router_offset) into the flat
    router array (index = group * a + router_in_group).
    """
    total_routers = a * g

    # Phase 1: build group-level interconnect as a regular multigraph where
    # each group has degree a*h (one degree unit per global channel endpoint).
    target_group_degree = a * h
    group_remaining = [target_group_degree] * g
    group_pair_counts: dict[tuple[int, int], int] = {}

    while sum(group_remaining) > 0:
        g1 = max(range(g), key=lambda gi: group_remaining[gi])
        if group_remaining[g1] == 0:
            break

        candidates = [gi for gi in range(g) if gi != g1 and group_remaining[gi] > 0]
        if not candidates:
            raise ValueError("Unable to realize global links for given Dragonfly parameters")

        # Prefer the least-used pair, then the candidate with highest remaining
        # degree to avoid starving high-demand groups.
        g2 = min(
            candidates,
            key=lambda gi: (
                group_pair_counts.get((min(g1, gi), max(g1, gi)), 0),
                -group_remaining[gi],
                gi,
            ),
        )

        pair = (min(g1, g2), max(g1, g2))
        group_pair_counts[pair] = group_pair_counts.get(pair, 0) + 1
        group_remaining[g1] -= 1
        group_remaining[g2] -= 1

    if any(v != 0 for v in group_remaining):
        raise ValueError("Failed to satisfy group-level global degree targets")

    # Phase 2: map group-level multiplicities to router-level links while
    # respecting h global ports per router.
    router_ports_used = [0] * total_routers
    links: list[tuple[int, int]] = []

    for (g1, g2), multiplicity in sorted(group_pair_counts.items()):
        for _ in range(multiplicity):
            best_r1 = min(range(a), key=lambda r: router_ports_used[g1 * a + r])
            best_r2 = min(range(a), key=lambda r: router_ports_used[g2 * a + r])
            src = g1 * a + best_r1
            dst = g2 * a + best_r2

            if router_ports_used[src] >= h or router_ports_used[dst] >= h:
                raise ValueError("Failed to place router-level global links within port budget")

            links.append((src, dst))
            router_ports_used[src] += 1
            router_ports_used[dst] += 1

    if any(v != h for v in router_ports_used):
        raise ValueError("Router-level global links do not match target h ports/router")

    return links


def generate_dragonfly_topology(
    switch_throughput: int,
    nic_throughput: int,
    link_bandwidth: int,
    num_hosts: int,
) -> DragonflyTopology:
    """Generate a Dragonfly topology minimizing total router count.

    Args:
        switch_throughput: Total switching capacity per switch in Gbps.
        nic_throughput: Escape throughput per NIC in Gbps.
        link_bandwidth: Per-link bandwidth in Gbps.
        num_hosts: Total number of hosts.

    Returns:
        DragonflyTopology with all links and metadata.

    Raises:
        ValueError: If inputs don't produce a valid topology.
    """
    _validate_inputs(switch_throughput, nic_throughput, link_bandwidth, num_hosts)

    ports_per_switch = switch_throughput // link_bandwidth
    links_per_host = nic_throughput // link_bandwidth

    a, h, p, g = _find_best_config(ports_per_switch, links_per_host, num_hosts)

    actual_hosts = num_hosts
    router_id_start = actual_hosts

    links: list[tuple[int, int, int]] = []

    # 1) Host-to-router links (aggregated per host-router pair)
    aggregated_host_bw = links_per_host * link_bandwidth
    total_routers = a * g
    base_hosts_per_router = actual_hosts // total_routers
    extra_hosts = actual_hosts % total_routers
    router_host_counts = [
        base_hosts_per_router + (1 if i < extra_hosts else 0)
        for i in range(total_routers)
    ]

    host_id = 0
    for router_offset, hosts_on_router in enumerate(router_host_counts):
        if hosts_on_router > p:
            raise ValueError(
                f"Internal error: router {router_offset} requires {hosts_on_router} hosts "
                f"but capacity is p={p}"
            )
        router_id = router_id_start + router_offset
        for _ in range(hosts_on_router):
            links.append((host_id, router_id, aggregated_host_bw))
            host_id += 1

    # 2) Intra-group links (all-to-all within each group, 1 link per pair)
    for grp in range(g):
        for i in range(a):
            for j in range(i + 1, a):
                src = router_id_start + grp * a + i
                dst = router_id_start + grp * a + j
                links.append((src, dst, link_bandwidth))

    # 3) Inter-group global links
    global_pairs = _wire_global_links(a, g, h)
    for src_offset, dst_offset in global_pairs:
        src = router_id_start + src_offset
        dst = router_id_start + dst_offset
        links.append((src, dst, link_bandwidth))

    return DragonflyTopology(
        num_hosts=actual_hosts,
        routers_per_group=a,
        num_groups=g,
        hosts_per_router=p,
        global_links_per_router=h,
        ports_per_switch=ports_per_switch,
        links_per_host=links_per_host,
        link_bandwidth=link_bandwidth,
        links=links,
    )
