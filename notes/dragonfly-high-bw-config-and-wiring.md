# High-BW Dragonfly: `_find_best_config` and `_wire_global_links`

Source: `src/dragonfly_high_bw_generator/topology.py` lines 116-252

## How It Differs From Standard

The standard generator optimizes for **fewest routers first**, balance second. The high-BW variant flips this: it optimizes for **bandwidth balance first**, accepting more routers within a budget. The global wiring algorithm is identical.

---

## `_iter_valid_configs` (lines 116-141)

Factored out from `_find_best_config` as a separate generator. Same feasibility logic as the standard variant:

- Iterates `(h, a)` pairs, derives `p = (k - (a-1) - h) / lph`.
- Iterates `g` from 2 to `a*h + 1`.
- Skips odd `a*g*h`, skips under-capacity.
- Yields `(a, h, p, g)` for every feasible combination.

No scoring here — just enumeration.

---

## `_find_best_config` (lines 144-193)

### Goal

Find `(a, h, p, g)` that accommodates `num_hosts` with the **best bandwidth balance**, allowing up to `router_budget_factor` times the minimum router count.

### Two-Pass Approach

#### Pass 1 — Establish Router Budget (lines 161-172)

```
configs = list(_iter_valid_configs(...))
min_routers = min(a * g for all configs)
router_cap = ceil(min_routers * router_budget_factor)
```

Default `router_budget_factor = 2.0`, so the search accepts configs with up to 2x the minimum router count.

#### Pass 2 — Select Best Within Budget (lines 174-192)

Iterates all configs where `a * g <= router_cap` and scores with a **4-tuple lexicographic key**:

| Priority | Metric | Purpose |
|----------|--------|---------|
| 1 | `|a - 2h|` | Global-link balance (Kim et al. sweet spot) |
| 2 | `|a - 2p*lph|` | Terminal balance (host bandwidth symmetry) |
| 3 | `total_routers` | Fewer routers preferred (cost) |
| 4 | `p*a*g - num_hosts` | Less overprovisioning |

Uses Python tuple comparison (`key < best_key`) for clean lexicographic ordering.

### Key Differences From Standard

| Aspect | Standard | High-BW |
|--------|----------|---------|
| Primary objective | Minimize router count | Minimize `|a - 2h|` |
| Router count role | Hard optimize | Soft constraint (budget cap) |
| Balance role | Tiebreaker | Primary criterion |
| Imbalance metric | Single sum `|a-2h| + |a-2p*lph|` | Two separate lexicographic levels |
| Implementation | Single pass, inline scoring | Two passes, separate enumeration |
| Extra parameter | None | `router_budget_factor` (default 2.0) |

The **practical effect**: for the same inputs, the high-BW variant may select a config with more routers but where `a ≈ 2h` and `a ≈ 2p*lph`, yielding more uniform bandwidth distribution across the network.

---

## `_wire_global_links` (lines 196-252)

**Identical** to the standard variant. Same two-phase algorithm:

1. **Phase 1 — Group-level multigraph**: greedy matching that spreads links evenly across group pairs, targeting degree `a*h` per group.
2. **Phase 2 — Router-level assignment**: maps group-pair links to specific routers by always choosing the least-loaded router in each group.

Same validation checks (all groups fully connected, all routers use exactly `h` global ports).

No changes were needed here because the wiring logic is parameterized by `(a, g, h)` — the different config selection upstream naturally produces different wiring outcomes without any algorithm changes.
