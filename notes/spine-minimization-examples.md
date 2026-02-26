# Spine Minimization: Numerical Examples

## Algorithm Recap

```
max_links_per_pair = ports_per_switch // num_leafs
links_per_pair     = largest_divisor(north_ports, <= max_links_per_pair)
num_spines         = north_ports / links_per_pair
```

---

## Case 1: Default Parameters Scaling (32-port switches)

**Setup**: `ports_per_switch = 32`, `north_ports = 16`

| num_leafs | max_links_per_pair | links_per_pair | num_spines | spine ports used | naive spines (lpp=1) | switches saved |
|:---------:|:------------------:|:--------------:|:----------:|:----------------:|:--------------------:|:--------------:|
| 1         | 32                 | 16             | **1**      | 16/32 (50%)      | 16                   | 15             |
| 2         | 16                 | 16             | **1**      | 32/32 (100%)     | 16                   | 15             |
| 4         | 8                  | 8              | **2**      | 32/32 (100%)     | 16                   | 14             |
| 8         | 4                  | 4              | **4**      | 32/32 (100%)     | 16                   | 12             |
| 16        | 2                  | 2              | **8**      | 32/32 (100%)     | 16                   | 8              |
| 32        | 1                  | 1              | **16**     | 32/32 (100%)     | 16                   | 0              |

**Insight**: With power-of-2 port counts, every `max_links_per_pair` is already a divisor of `north_ports`, so there's never a divisor gap. Spine count doubles each time leafs double. At 32 leafs, the optimization can't help -- each spine has exactly 1 port per leaf.

---

## Case 2: Divisor Gap (48-port switches)

**Setup**: `ports_per_switch = 48`, `north_ports = 24`, divisors of 24 = {1, 2, 3, 4, 6, 8, 12, 24}

| num_leafs | max_links_per_pair | links_per_pair | **gap** | num_spines | spine util   |
|:---------:|:------------------:|:--------------:|:-------:|:----------:|:------------:|
| 5         | 9                  | **8**          | 1       | 3          | 40/48 (83%)  |
| 9         | 5                  | **4**          | 1       | 6          | 36/48 (75%)  |
| 11        | 4                  | **4**          | 0       | 6          | 44/48 (92%)  |
| 7         | 6                  | **6**          | 0       | 4          | 42/48 (88%)  |

**Insight**: When `max_links_per_pair` doesn't divide `north_ports`, the algorithm drops to the next-lower divisor. With 5 leafs, the budget is 9 links/pair but 9 doesn't divide 24 -- we fall to 8, needing 3 spines instead of the theoretical minimum of ~2.67 (impossible anyway). The gap wastes spine ports: `5 * 8 = 40` out of 48 used.

---

## Case 3: Bigger Switch = Fewer Spines

**Same fabric (16 leafs)**, different switch sizes:

| ports_per_switch | north_ports | max_links_per_pair | links_per_pair | num_spines | total switches |
|:----------------:|:-----------:|:------------------:|:--------------:|:----------:|:--------------:|
| 32               | 16          | 2                  | 2              | **8**      | 24             |
| 48               | 24          | 3                  | 3              | **8**      | 24             |
| 64               | 32          | 4                  | 4              | **8**      | 24             |
| 128              | 64          | 8                  | 8              | **8**      | 24             |

Interestingly, 16 leafs always yields 8 spines here because `north_ports / (ports_per_switch / num_leafs)` simplifies to `num_leafs / 2` when everything divides cleanly.

Now try **10 leafs** (where things get interesting):

| ports_per_switch | north_ports | max_links_per_pair | links_per_pair | num_spines | spine util    |
|:----------------:|:-----------:|:------------------:|:--------------:|:----------:|:-------------:|
| 32               | 16          | 3                  | **2**          | **8**      | 20/32 (63%)   |
| 48               | 24          | 4                  | **4**          | **6**      | 40/48 (83%)   |
| 64               | 32          | 6                  | **4**          | **8**      | 40/64 (63%)   |
| 128              | 64          | 12                 | **8**          | **8**      | 80/128 (63%)  |

**Insight**: Bigger switches don't always help. With 10 leafs, the 48-port switch actually achieves the fewest spines (6) because its `north_ports = 24` has richer divisors that align with the constraint. The 64-port switch has `max_links_per_pair = 6` but the largest divisor of 32 that's <= 6 is only 4, wasting budget.

---

## Case 4: Extreme -- Single Spine (Best Possible)

A single spine is achievable when `north_ports <= ports_per_switch / num_leafs`, i.e., one spine can absorb all north links from all leafs.

| ports_per_switch | north_ports | num_leafs | max_links_per_pair | links_per_pair | num_spines |
|:----------------:|:-----------:|:---------:|:------------------:|:--------------:|:----------:|
| 32               | 16          | 2         | 16                 | 16             | **1**      |
| 64               | 32          | 2         | 32                 | 32             | **1**      |
| 128              | 64          | 2         | 64                 | 64             | **1**      |

**Condition**: `num_leafs <= ports_per_switch / north_ports = 2` (for the 50/50 split). So a single spine is only possible with 1 or 2 leafs.

---

## Summary of Key Takeaways

| Scenario | What happens | Spine impact |
|---|---|---|
| **Power-of-2 ports & leafs** | `max_links_per_pair` always divides `north_ports` | No waste, optimal |
| **Divisor gap** | `max_links_per_pair` is not a divisor of `north_ports` | Extra spines + wasted spine ports |
| **Few leafs, big switch** | `links_per_pair` can be very large | Collapses to 1-2 spines |
| **Leafs = ports_per_switch** | `max_links_per_pair = 1`, no aggregation possible | `num_spines = north_ports` (maximum) |
| **Richer divisor set** (e.g., 24 vs 32 north_ports) | More "landing spots" for the divisor search | Can beat larger switches in specific cases |
