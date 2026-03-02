"""High-bandwidth Dragonfly topology calculation and link generation.

This variant keeps the same feasibility constraints as the canonical
Dragonfly generator but uses a router-budget approach:
  1. Find the minimum achievable router count.
  2. Allow up to ceil(min_routers * budget_factor) routers.
  3. Within that budget, optimize for balance:
     a) minimize |a - 2h|          (global-link balance)
     b) minimize |a - 2p*lph|      (terminal balance)
     c) minimize total routers      (prefer fewer within budget)
     d) minimize host overprovisioning
"""

from __future__ import annotations

import json
import math
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
            "=== Dragonfly High-BW Topology ===",
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


def _iter_valid_configs(
    ports_per_switch: int,
    links_per_host: int,
    num_hosts: int,
):
    """Yield all feasible (a, h, p, g) with their metrics."""
    k = ports_per_switch
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
                if (a * g * h) % 2 != 0:
                    continue
                capacity = p * a * g
                if capacity < num_hosts:
                    continue
                yield a, h, p, g


def _find_best_config(
    ports_per_switch: int,
    links_per_host: int,
    num_hosts: int,
    router_budget_factor: float = 2.0,
) -> tuple[int, int, int, int]:
    """Find (a, h, p, g) that accommodates num_hosts with high-BW balance.

    Two-pass approach:
      Pass 1 — find minimum achievable router count.
      Pass 2 — among configs with routers <= ceil(min * budget_factor),
               select by:
                 1) |a - 2h|          (global-link balance)
                 2) |a - 2p*lph|      (terminal balance)
                 3) total routers     (prefer fewer within budget)
                 4) host slack        (overprovisioning)
    """
    configs = list(_iter_valid_configs(
        ports_per_switch, links_per_host, num_hosts,
    ))
    if not configs:
        raise ValueError(
            f"No valid Dragonfly High-BW configuration found for {num_hosts} hosts "
            f"with {ports_per_switch}-port switches and {links_per_host} links/host. "
            f"Try fewer hosts or higher switch throughput."
        )

    min_routers = min(a * g for a, _, _, g in configs)
    router_cap = math.ceil(min_routers * router_budget_factor)

    best: tuple[int, int, int, int] | None = None
    best_key = (float("inf"), float("inf"), float("inf"), float("inf"))

    for a, h, p, g in configs:
        total_routers = a * g
        if total_routers > router_cap:
            continue

        key = (
            abs(a - 2 * h),
            abs(a - 2 * p * links_per_host),
            total_routers,
            p * a * g - num_hosts,
        )
        if key < best_key:
            best = (a, h, p, g)
            best_key = key

    assert best is not None
    return best


def _wire_global_links(
    a: int, g: int, h: int
) -> list[tuple[int, int]]:
    """Compute inter-group global links as (router_offset, router_offset) pairs."""
    total_routers = a * g

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
    router_budget_factor: float = 2.0,
) -> DragonflyTopology:
    """Generate a Dragonfly topology favoring high-balance global connectivity."""
    _validate_inputs(switch_throughput, nic_throughput, link_bandwidth, num_hosts)

    ports_per_switch = switch_throughput // link_bandwidth
    links_per_host = nic_throughput // link_bandwidth

    a, h, p, g = _find_best_config(
        ports_per_switch, links_per_host, num_hosts, router_budget_factor,
    )

    actual_hosts = num_hosts
    router_id_start = actual_hosts

    links: list[tuple[int, int, int]] = []

    # 1) Host-to-router links (aggregated per host-router pair)
    aggregated_host_bw = links_per_host * link_bandwidth
    total_routers = a * g
    # Distribute hosts round-robin across groups/routers to avoid concentrating
    # low host counts in the first group.
    router_host_counts = [0] * total_routers
    router_round_robin_order = [
        grp * a + router_in_group
        for router_in_group in range(a)
        for grp in range(g)
    ]
    for i in range(actual_hosts):
        router_host_counts[router_round_robin_order[i % total_routers]] += 1

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
