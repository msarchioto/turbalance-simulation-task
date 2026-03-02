"""CLI entry point for single-run Dragonfly High-BW topology generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dragonfly_generator.visualize import visualize_topology
from dragonfly_high_bw_generator.topology import generate_dragonfly_topology


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dragonfly-high-bw-generate",
        description="Generate a Dragonfly topology prioritizing high-balance bandwidth.",
    )
    parser.add_argument(
        "--switch-throughput",
        type=int,
        required=True,
        help="Total switching throughput per switch in Gbps (e.g. 6400)",
    )
    parser.add_argument(
        "--nic-throughput",
        type=int,
        required=True,
        help="Escape throughput per NIC in Gbps (e.g. 800)",
    )
    parser.add_argument(
        "--link-bandwidth",
        type=int,
        required=True,
        help="Per-link bandwidth in Gbps (e.g. 200)",
    )
    parser.add_argument(
        "--num-hosts",
        type=int,
        required=True,
        help="Total number of hosts (e.g. 128)",
    )
    parser.add_argument(
        "--router-budget-factor",
        type=float,
        default=2.0,
        help="Allow up to ceil(min_routers * factor) routers for better balance (default: 2.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path (default: output_dragonfly_high_bw/dragonfly_{num_hosts}.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        topo = generate_dragonfly_topology(
            switch_throughput=args.switch_throughput,
            nic_throughput=args.nic_throughput,
            link_bandwidth=args.link_bandwidth,
            num_hosts=args.num_hosts,
            router_budget_factor=args.router_budget_factor,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output_path = args.output or Path(f"output_dragonfly_high_bw/dragonfly_{args.num_hosts}.json")
    topo.write_json(output_path)

    print(topo.summary())
    print(f"\nTopology written to: {output_path}")

    png_path = output_path.with_suffix(".png")
    visualize_topology(
        topo.to_json(),
        png_path,
        f"Dragonfly High-BW Topology ({output_path.stem})",
        num_hosts=topo.num_hosts,
        routers_per_group=topo.routers_per_group,
        num_groups=topo.num_groups,
    )
    print(f"Diagram written to: {png_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
