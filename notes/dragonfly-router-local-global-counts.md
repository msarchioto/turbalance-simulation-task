# Dragonfly Counts: Routers, Local Links, Global Links

## Scope

This note explains, numerically, why the current Dragonfly implementation
produces the observed counts for:

- routers (`a * g`)
- local links (intra-group)
- global links (inter-group)

for host counts `[4, 8, 16, 32, 64]` with the default sweep parameters:

- `switch_throughput = 6400`
- `nic_throughput = 800`
- `link_bandwidth = 200`

Derived constants:

- `k = ports_per_switch = 6400 / 200 = 32`
- `links_per_host = 800 / 200 = 4`

---

## Formulas Used by This Implementation

### 1) Per-router port equation

For a candidate `(a, h, p)`:

`p * links_per_host + (a - 1) + h = k`

With defaults (`links_per_host = 4`, `k = 32`):

`4p + (a - 1) + h = 32`

### 2) Host capacity and routers

- Capacity: `capacity = p * a * g` must be `>= N`
- Routers: `routers = a * g`

The optimizer minimizes `routers` first.

### 3) Local links

Each group is a clique of size `a`, so:

- local links per group: `a * (a - 1) / 2`
- total local links: `g * a * (a - 1) / 2`

### 4) Global links

The implementation first builds a group-level regular multigraph where each
group has target degree `a*h` (global channel endpoints per group). Therefore:

- sum of group degrees = `g * a * h`
- each link contributes degree 2
- total global links = `(g * a * h) / 2`

Then it maps those group-level multiplicities to router-level links while
enforcing exactly `h` global ports per router.

---

## Case-by-Case Numerical Breakdown

## N = 4

Selected config: `(a, h, p, g) = (2, 27, 1, 2)`

Checks:

- Port equation: `4*1 + (2-1) + 27 = 4 + 1 + 27 = 32`
- Capacity: `1 * 2 * 2 = 4` hosts

Counts:

- Routers: `a * g = 2 * 2 = 4`
- Local links: `g * a*(a-1)/2 = 2 * (2*1/2) = 2`
- Global links: `a * h = 2 * 27 = 54` (since `g=2`)

## N = 8

Selected config: `(a, h, p, g) = (2, 23, 2, 2)`

Checks:

- Port equation: `4*2 + (2-1) + 23 = 8 + 1 + 23 = 32`
- Capacity: `2 * 2 * 2 = 8` hosts

Counts:

- Routers: `2 * 2 = 4`
- Local links: `2 * (2*1/2) = 2`
- Global links: `2 * 23 = 46`

## N = 16

Selected config: `(a, h, p, g) = (2, 15, 4, 2)`

Checks:

- Port equation: `4*4 + (2-1) + 15 = 16 + 1 + 15 = 32`
- Capacity: `4 * 2 * 2 = 16` hosts

Counts:

- Routers: `2 * 2 = 4`
- Local links: `2 * (2*1/2) = 2`
- Global links: `2 * 15 = 30`

## N = 32

Selected config: `(a, h, p, g) = (3, 6, 6, 2)`

Checks:

- Port equation: `4*6 + (3-1) + 6 = 24 + 2 + 6 = 32`
- Capacity: `6 * 3 * 2 = 36` hosts (4 host slack)

Counts:

- Routers: `3 * 2 = 6`
- Local links: `2 * (3*2/2) = 6`
- Global links: `a * h = 3 * 6 = 18` (since `g=2`)

## N = 64

Selected config: `(a, h, p, g) = (2, 3, 7, 5)`

Checks:

- Port equation: `4*7 + (2-1) + 3 = 28 + 1 + 3 = 32`
- Capacity: `7 * 2 * 5 = 70` hosts (6 host slack)

Counts:

- Routers: `2 * 5 = 10`
- Local links: `5 * (2*1/2) = 5`
- Global links:
  - `(g * a * h) / 2 = (5 * 2 * 3) / 2 = 15`

---

## Consolidated Table

| hosts N | (a,h,p,g) | routers `a*g` | local links `g*a*(a-1)/2` | global links (generated) |
|---:|---|---:|---:|---:|
| 4  | (2,27,1,2) | 4  | 2 | 54 |
| 8  | (2,23,2,2) | 4  | 2 | 46 |
| 16 | (2,15,4,2) | 4  | 2 | 30 |
| 32 | (3,6,6,2)  | 6  | 6 | 18 |
| 64 | (2,3,7,5)  | 10 | 5 | 15 |

---

## Why These Values Are Chosen

The optimizer is lexicographic:

1. minimize total routers (`a * g`)
2. if tied, minimize imbalance against balanced Dragonfly ratios
   (`|a-2h| + |a-2p*links_per_host|`)
3. if still tied, minimize host slack (`capacity - N`)

This is why small `N` heavily favors `g=2` and very large `h`: it yields very
few routers, even though global-link count becomes high.
