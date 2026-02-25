"""Core CLOS topology calculation and link generation.

Implements a 2-layer (leaf-spine) CLOS fabric with:
- Minimum total switch count
- No oversubscription (equal north/south bandwidth per leaf)
- Full bisection bandwidth
- Symmetric connectivity
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClosTopology:
    """Complete description of a 2-layer CLOS topology."""

    num_hosts: int
    num_leafs: int
    num_spines: int
    ports_per_switch: int
    links_per_host: int
    hosts_per_leaf: int
    links_per_leaf_spine_pair: int
    leaf_south_ports_used: int
    leaf_north_ports_used: int
    spine_ports_used: int
    link_bandwidth: int
    links: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def total_switches(self) -> int:
        return self.num_leafs + self.num_spines

    @property
    def host_id_range(self) -> tuple[int, int]:
        return (0, self.num_hosts - 1)

    @property
    def leaf_id_range(self) -> tuple[int, int]:
        start = self.num_hosts
        return (start, start + self.num_leafs - 1)

    @property
    def spine_id_range(self) -> tuple[int, int]:
        start = self.num_hosts + self.num_leafs
        return (start, start + self.num_spines - 1)

    def summary(self) -> str:
        lines = [
            "=== 2-Layer CLOS Topology ===",
            f"Hosts:          {self.num_hosts}",
            f"  IDs:          [{self.host_id_range[0]}, {self.host_id_range[1]}]",
            f"  Links/host:   {self.links_per_host} x {self.link_bandwidth}G "
            f"(aggregated: {self.links_per_host * self.link_bandwidth}G)",
            f"Leaf switches:  {self.num_leafs}",
            f"  IDs:          [{self.leaf_id_range[0]}, {self.leaf_id_range[1]}]",
            f"  South ports:  {self.leaf_south_ports_used}/{self.ports_per_switch // 2} used",
            f"  North ports:  {self.leaf_north_ports_used}/{self.ports_per_switch // 2} used",
            f"  Total ports:  "
            f"{self.leaf_south_ports_used + self.leaf_north_ports_used}/{self.ports_per_switch} used",
            f"Spine switches: {self.num_spines}",
            f"  IDs:          [{self.spine_id_range[0]}, {self.spine_id_range[1]}]",
            f"  Ports used:   {self.spine_ports_used}/{self.ports_per_switch} used",
            f"Total switches: {self.total_switches}",
            f"Total links:    {len(self.links)}",
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

    ports_per_switch = switch_throughput // link_bandwidth
    if ports_per_switch % 2 != 0:
        raise ValueError(
            f"ports_per_switch ({ports_per_switch}) must be even for "
            f"non-oversubscribed leaf-spine split"
        )

    links_per_host = nic_throughput // link_bandwidth
    half_ports = ports_per_switch // 2
    if half_ports % links_per_host != 0:
        raise ValueError(
            f"Half the switch ports ({half_ports}) must be divisible by "
            f"links_per_host ({links_per_host}) for symmetric host attachment"
        )

    hosts_per_leaf = half_ports // links_per_host
    if num_hosts % hosts_per_leaf != 0:
        raise ValueError(
            f"num_hosts ({num_hosts}) must be divisible by "
            f"hosts_per_leaf ({hosts_per_leaf})"
        )


def generate_clos_topology(
    switch_throughput: int,
    nic_throughput: int,
    link_bandwidth: int,
    num_hosts: int,
) -> ClosTopology:
    """Generate a 2-layer CLOS topology minimizing total switch count.

    Args:
        switch_throughput: Total switching capacity per switch in Gbps.
        nic_throughput: Escape throughput per NIC in Gbps.
        link_bandwidth: Per-link bandwidth in Gbps.
        num_hosts: Total number of hosts.

    Returns:
        ClosTopology with all links and metadata.

    Raises:
        ValueError: If inputs don't produce a valid symmetric topology.
    """
    _validate_inputs(switch_throughput, nic_throughput, link_bandwidth, num_hosts)

    ports_per_switch = switch_throughput // link_bandwidth
    links_per_host = nic_throughput // link_bandwidth
    half_ports = ports_per_switch // 2

    hosts_per_leaf = half_ports // links_per_host
    num_leafs = num_hosts // hosts_per_leaf
    leaf_south_ports_used = hosts_per_leaf * links_per_host  # == half_ports

    # Spine count: minimize total switches while each spine has enough ports
    # for all leafs and each leaf can reach every spine.
    #
    # Each leaf has half_ports north ports to distribute across spines.
    # Each spine has ports_per_switch ports to connect to leafs.
    #
    # links_per_leaf_spine_pair * num_spines == half_ports  (leaf constraint)
    # links_per_leaf_spine_pair * num_leafs <= ports_per_switch  (spine constraint)
    #
    # Maximize links_per_leaf_spine_pair to minimize num_spines.
    # links_per_leaf_spine_pair <= ports_per_switch // num_leafs
    # links_per_leaf_spine_pair must divide half_ports evenly.

    max_links_per_pair = ports_per_switch // num_leafs
    if max_links_per_pair < 1:
        raise ValueError(
            f"Cannot build topology: {num_leafs} leafs require spines with "
            f">= {num_leafs} ports, but switches only have {ports_per_switch} ports. "
            f"Reduce num_hosts or increase switch_throughput."
        )

    # Find largest divisor of half_ports that is <= max_links_per_pair
    links_per_leaf_spine_pair = _largest_divisor_leq(half_ports, max_links_per_pair)
    num_spines = half_ports // links_per_leaf_spine_pair
    spine_ports_used = num_leafs * links_per_leaf_spine_pair
    leaf_north_ports_used = num_spines * links_per_leaf_spine_pair  # == half_ports

    # Generate links with aggregation
    links: list[tuple[int, int, int]] = []
    leaf_id_start = num_hosts
    spine_id_start = num_hosts + num_leafs

    # Host-to-leaf links (aggregated per host-leaf pair)
    aggregated_host_bw = links_per_host * link_bandwidth
    for leaf_idx in range(num_leafs):
        leaf_id = leaf_id_start + leaf_idx
        for h in range(hosts_per_leaf):
            host_id = leaf_idx * hosts_per_leaf + h
            links.append((host_id, leaf_id, aggregated_host_bw))

    # Leaf-to-spine links (aggregated per leaf-spine pair)
    aggregated_uplink_bw = links_per_leaf_spine_pair * link_bandwidth
    for leaf_idx in range(num_leafs):
        leaf_id = leaf_id_start + leaf_idx
        for spine_idx in range(num_spines):
            spine_id = spine_id_start + spine_idx
            links.append((leaf_id, spine_id, aggregated_uplink_bw))

    return ClosTopology(
        num_hosts=num_hosts,
        num_leafs=num_leafs,
        num_spines=num_spines,
        ports_per_switch=ports_per_switch,
        links_per_host=links_per_host,
        hosts_per_leaf=hosts_per_leaf,
        links_per_leaf_spine_pair=links_per_leaf_spine_pair,
        leaf_south_ports_used=leaf_south_ports_used,
        leaf_north_ports_used=leaf_north_ports_used,
        spine_ports_used=spine_ports_used,
        link_bandwidth=link_bandwidth,
        links=links,
    )


def _largest_divisor_leq(n: int, cap: int) -> int:
    """Find the largest divisor of n that is <= cap."""
    # Start from cap and go down; for typical port counts this is fast
    for d in range(min(cap, n), 0, -1):
        if n % d == 0:
            return d
    return 1
