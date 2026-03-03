# Standard Dragonfly: `_find_best_config` and `_wire_global_links`

Source: `src/dragonfly_generator/topology.py` lines 119-266

## Parameters Recap

| Symbol | Meaning |
|--------|---------|
| `k`    | Ports per switch (`switch_throughput / link_bandwidth`) |
| `a`    | Routers per group |
| `h`    | Global (inter-group) links per router |
| `p`    | Hosts per router |
| `g`    | Number of groups |
| `lph`  | Links per host (`nic_throughput / link_bandwidth`) |

Port budget constraint per router: `k = p * lph + (a - 1) + h`

---

## `_find_best_config` (lines 119-190)

### Goal

Find `(a, h, p, g)` that can accommodate `num_hosts` using the **fewest total routers** (`a * g`).

### Search Strategy — Single-Pass Brute Force

Iterates over all `(h, a)` pairs with `h in [1, k)` and `a in [2, k)`:

1. **Derive `p`** from the port budget:
   ```
   remaining = k - (a - 1) - h
   p = remaining / lph        (must be a positive integer)
   ```
   If `remaining <= 0` the inner loop breaks (increasing `a` only makes it worse).

2. **Iterate `g`** from 2 to the maximum `a*h + 1`:
   - Skip if `a * g * h` is odd (total global link endpoints must be even for pairing).
   - Skip if capacity `p * a * g < num_hosts`.

3. **Score** each valid config with a three-tier lexicographic comparison:
   | Priority | Metric | Prefers |
   |----------|--------|---------|
   | 1 | `total_routers = a * g` | Fewer routers |
   | 2 | `imbalance = |a - 2h| + |a - 2p*lph|` | Closer to the balanced ratio where local = 2 * global and local = 2 * terminal |
   | 3 | `host_slack = capacity - num_hosts` | Less overprovisioning |

   The comparison is flat `or`-chained: a new candidate wins if it has strictly fewer routers, **or** same routers with lower imbalance, **or** same routers and same imbalance with lower slack.

### Key Observations

- **Optimizes for cost** (router count) first, balance second. This means the selected config may be far from the `a = 2h` sweet spot if a more balanced config requires more routers.
- The imbalance metric sums two terms: global balance `|a - 2h|` and terminal balance `|a - 2p*lph|`. Both contribute equally — there's no weighting.
- No budget relaxation: the search space is not filtered to a "good enough" router count first.

---

## `_wire_global_links` (lines 193-266)

### Goal

Produce a list of `(src_router_offset, dst_router_offset)` pairs representing all inter-group links, ensuring every router uses exactly `h` global ports.

### Two-Phase Algorithm

#### Phase 1 — Group-Level Multigraph (lines 210-242)

Determines **how many** links connect each pair of groups.

- Each group has a target degree of `a * h` (total global port endpoints across its `a` routers).
- Greedy matching loop:
  1. Pick group `g1` with the highest remaining degree.
  2. Among candidates (groups with remaining > 0, excluding `g1`), pick `g2` that minimizes:
     ```
     (existing_pair_count, -remaining_degree, group_index)
     ```
     This spreads links across group pairs as evenly as possible (least-used pair first), breaking ties by preferring the candidate with the most remaining demand.
  3. Increment the pair count for `(g1, g2)`, decrement both groups' remaining.
- Validates all groups hit exactly zero remaining.

**For maximum-size dragonfly** (`g = a*h + 1`): every group pair gets exactly 1 link (since total endpoints = `g * a * h` and pairs = `g*(g-1)/2 = g*a*h/2`, each pair gets exactly 1).

**For smaller dragonflies** (`g < a*h + 1`): some pairs get multiple links (the multigraph has higher multiplicity).

#### Phase 2 — Router-Level Assignment (lines 244-266)

Maps each group-pair link to a specific router in each group.

For each `(g1, g2)` pair with multiplicity `m`:
1. For each of the `m` links, pick the router within each group that has the **fewest** global ports used so far:
   ```
   best_r1 = argmin_{r in [0,a)} router_ports_used[g1 * a + r]
   best_r2 = argmin_{r in [0,a)} router_ports_used[g2 * a + r]
   ```
2. Validate neither router exceeds `h` ports.
3. Record the link and increment both routers' port counts.

Final validation confirms every router uses exactly `h` global ports.

### Properties

- Deterministic for a given `(a, g, h)` — the sorted iteration over `group_pair_counts` ensures consistent ordering.
- Balanced by construction: the Phase 1 greedy ensures even spread across group pairs; Phase 2 greedy ensures even spread across routers within each group.
- Fails loudly if the degree sequence is unrealizable (odd total endpoints, impossible distribution, etc.).
