"""Idempotent sweep runner that generates CLOS topologies across host counts.

Iterates host counts [4, 8, 16, 32, 64] (powers of 2), skips runs where
the output file already exists, and reports results per configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clos_generator.topology import generate_clos_topology
from clos_generator.visualize import visualize_topology


DEFAULT_HOST_COUNTS = [2**i for i in range(2, 7)]  # [4, 8, 16, 32, 64]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clos-sweep",
        description="Sweep CLOS topology generation across host counts [4..64] in powers of 2.",
    )
    parser.add_argument(
        "--switch-throughput",
        type=int,
        required=True,
        help="Total switching throughput per switch in Gbps",
    )
    parser.add_argument(
        "--nic-throughput",
        type=int,
        required=True,
        help="Escape throughput per NIC in Gbps",
    )
    parser.add_argument(
        "--link-bandwidth",
        type=int,
        required=True,
        help="Per-link bandwidth in Gbps",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for output JSON files (default: output/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if output file already exists",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    results: dict[str, list[int]] = {
        "generated": [],
        "skipped": [],
        "failed": [],
    }

    for n_hosts in DEFAULT_HOST_COUNTS:
        output_path = args.output_dir / f"topo_{n_hosts}.json"

        if output_path.exists() and not args.force:
            results["skipped"].append(n_hosts)
            continue

        try:
            topo = generate_clos_topology(
                switch_throughput=args.switch_throughput,
                nic_throughput=args.nic_throughput,
                link_bandwidth=args.link_bandwidth,
                num_hosts=n_hosts,
            )
        except ValueError as e:
            print(f"[FAIL] hosts={n_hosts}: {e}", file=sys.stderr)
            results["failed"].append(n_hosts)
            continue

        topo.write_json(output_path)

        png_path = output_path.with_suffix(".png")
        visualize_topology(topo.to_json(), png_path, f"2-Layer CLOS Topology ({output_path.stem})")

        print(f"[OK]   hosts={n_hosts} -> {output_path} + {png_path}")
        print(topo.summary())
        print()
        results["generated"].append(n_hosts)

    print("--- Sweep Summary ---")
    print(f"Generated: {results['generated'] or 'none'}")
    print(f"Skipped:   {results['skipped'] or 'none'}")
    print(f"Failed:    {results['failed'] or 'none'}")

    return 1 if results["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
