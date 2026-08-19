# RP2-v2 remediation — validation report

**Branch:** `rp2-v2-remediation` from `dbd571d`
**Scope:** audit of the Research Program v2 feature and inference layer, and remediation of
the defects that audit found.

This report states what was fixed, what proves it, and — in the same detail — what was
audited and **not** fixed. An item marked OPEN is not a gap in the audit; it is a gap in the
remediation, and treating it as closed would be worse than leaving it open.

---

## 1. Defects found and fixed

Each row names the failure mode, not just the change. Every fix has a test that fails
against the previous behaviour.

### 1.1 Session length was hard-coded at 390 minutes

`src/mds650/rp2/bars.py` assumed every session is 390 minutes. XNYS closes early on roughly
nine days a year. On those days a fixed grid invents up to 180 minutes of flat price, and
every origin, feature and target inside that region inherits the fabrication.

Length and open now come from the exchange calendar per session; a holiday returns 0 minutes
rather than a session that did not happen.

**This fix was incomplete when first reported here, in three places.** Correcting the grid
builder did not correct its callers:

* `session_length_minutes` returned 0 for a holiday and `build_session_grid` immediately
  replaced that 0 with the full-session length — rebuilding the exact fabrication the zero
  existed to prevent. A named session the exchange did not trade now returns an empty grid.
* `rp2_block4_b0_panel.py` sized its origin array from a module constant, so on a 210-minute
  early close every window past minute 210 indexed off the end of the grid and the block
  aborted with `RP2_WINDOW_EXCEEDS_SERIES`. The same held in its market-control path and again
  in its intraday-GARCH fitter, which additionally indexed `filtered[origin]` with a raw
  session minute against a series that starts at the first *observed* minute.
* `rp2_block3_target_panel.py` reindexed onto a private 390-minute grid of its own.

Origins are now built from `grid.minutes` at every call site.

**What it changed, measured.** The fabrication had a second effect nobody had looked for. On a
210-minute early close the fixed grid held 180 minutes of NaN, so the fill-share quality gate
saw 46% missing and **discarded the session**. Block 4's counters record it exactly: 54 of 2,838
session-assets `dropped_fill` before, **0 after**, and the panel grows from 183,744 origins to
185,351. Every early close in the study window had been thrown away as low-quality data by a
grid that invented the minutes it then judged missing.

**Proof:** `tests/unit/test_rp2_bars.py::test_early_closes_are_shorter_than_a_full_session`
(2025-11-28 and 2025-12-24 are 210 minutes), `::test_an_early_close_session_produces_a_short_grid`,
`::test_bars_past_the_session_close_are_discarded`,
`::test_a_holiday_has_no_session_rather_than_a_fabricated_one`.

### 1.2 The opening minutes were filled from the future

`_forward_fill` contained `filled[:first] = filled[first]`, which carried the first observed
price **backwards** into every earlier minute of the session. Features and targets computed
at those minutes consumed a price that did not exist yet — a direct look-ahead leak, silent
because the filled values are perfectly plausible.

Forward fill only. Minutes with no prior observation are marked `valid = False` and the
caller drops them.

**This fix was also incomplete when first reported here.** `rp2_block3_target_panel.py` carried
its own copy of the grid builder, containing the same `grid[:first] = grid[first]`. That block
builds the **targets**, so every score in the programme is computed against numbers the leak
touched — and a test written against `mds650.rp2.bars` could not see it. The duplicate is
deleted and the block now calls the shared builder; a test asserts the private function is
gone rather than merely that the shared one exists.

The callers also had to learn what `valid` means. `close.min() <= 0.0` cannot detect an
unobserved open, because those minutes are NaN and NaN fails every comparison — so a session
with one absent opening bar reached `log_returns` and raised `RP2_RETURNS_PRICE_INVALID`,
killing a session the fill-share threshold was written to tolerate. Blocks 3 and 4 now drop the
affected origins and keep the session.

**Proof:** `::test_a_late_open_is_marked_invalid_and_never_back_filled`,
`tests/unit/test_rp2_block3_targets.py::test_the_block_no_longer_carries_its_own_grid_builder`,
`::test_targets_never_consume_a_price_from_before_the_first_observation`,
`tests/unit/test_rp2_block4_sessions.py::test_a_missing_opening_bar_drops_its_origins_rather_than_the_session`,
`::test_origins_are_sized_to_the_session_that_actually_happened`.

**What it changed.** Block 3 reclassified 28 session-assets from `dropped_fill` to
`dropped_short` — they were early closes and holidays, never fill failures — and moved 12 rows.
The aggregate is small because block 3's first origin is minute 120, far past any missing open;
`rv_session_to_date` and the previous-day RV integrate from minute 0, so those columns did move
wherever a session opened late.

### 1.3 Out-of-the-money classification was unsided

`scripts/rp2_block6_flow_panel.py` used `abs(log_moneyness) > 0.05` for both option types,
which groups out-of-the-money calls together with **in**-the-money puts at the same strike
distance. Those are opposite exposures, so `otm_premium_share` mixed them.

Now `K > S` for calls and `K < S` for puts.

### 1.4 Concentration confounded concentration with level

Raw Herfindahl has a floor of `1/n` and raw Shannon entropy a ceiling of `log n`, so both
moved simply because more contracts traded. `b2_*_strike_hhi` therefore fell on busy windows
regardless of how concentrated the flow was.

Both are normalised to `[0, 1]`. A single positive weight returns NaN: concentration
relative to nothing is undefined, not 1.

**Proof:** `tests/unit/test_rp2_flow.py::test_normalised_concentration_does_not_move_with_the_contract_count`
— even flow over 4, 40 and 400 contracts must score identically; the raw index reports
0.25 against 0.025.

### 1.5 The intensity measure was called Hawkes and was not one

`hawkes_intensity` took `baseline`, `excitation` and `decay` as **fixed inputs** (0, 1, 60 s
at every call site). Nothing was estimated, so there is no self-excitation parameter, no
branching ratio and no stability condition — the name asserted a fitted point-process model
that does not exist.

Renamed `exponential_decay_intensity`, with the docstring stating exactly that. Feature
columns follow: `decay_intensity_last`, `decay_intensity_innovation`.

### 1.6 `variance_risk_premium` was not a variance risk premium

It computed `IV² − annualise(trailing RV)`. A VRP is the gap between the risk-neutral
expectation and the physical expectation of **future** variance. Substituting the trailing
realisation makes the quantity mechanically large whenever variance has just fallen — a
property of the recent past, not of a premium.

Renamed `implied_minus_trailing_variance`; the feature is `b1_iv_minus_trailing_rv_30d`.

### 1.7 Artifacts carried no input provenance

Artifacts hashed the canonical JSON of the **result document**, which proves the document was
not edited and nothing about the file the numbers came from.

`src/mds650/rp2/provenance.py` records byte SHA-256, schema digest, row count, time span and
provider per input, and `verify_inputs` re-hashes and names what drifted.

**Proof:** `tests/unit/test_rp2_provenance.py::test_content_mutation_changes_the_hash_even_at_identical_shape`
constructs two files with identical columns, dtypes and row counts differing in one value —
a shape-only record calls them the same file.

### 1.8 Panel joins asserted nothing

`load_merged_panel` performed two left joins with no cardinality check. A duplicated origin
key double-weights that origin in every mean, bootstrap and regression downstream; a
duplicated key on the right fans the panel out into what looks like more data.

`assert_unique_origin_key`, `assert_one_to_one_join` and `assert_required_columns` now fail
closed with named errors.

**Proof:** `tests/unit/test_rp2_panel.py::test_a_duplicated_origin_key_is_refused`,
`::test_a_join_that_fans_the_panel_out_is_refused`,
`::test_a_missing_required_column_fails_closed`.

### 1.8b B0 could not see the market, in either sample

The first version of this section said B0 meant different things in discovery and validation.
**That was wrong, and the truth was worse.**

`market_control_rows` really did read 71,192 in D and 0 in V, but those four columns —
`SPY_rv_30`, `SPY_ret_30`, `QQQ_rv_30`, `QQQ_ret_30` — were read only by Block 4's internal
`b0_market` ladder variant. `B0_FEATURES`, the registry every block from 7 onward consumes,
held eighteen entries and none of them was SPY or QQQ. The baseline was identical in the two
samples: identically blind.

So **every B2 increment this programme ever measured was measured against a baseline that
could not see the market.** When the index moves and a name moves with it, a model that cannot
see the index attributes the common movement to whatever it can see — here, option flow.

Closed rather than recorded. SPY and QQQ one-minute bars were acquired for the 289 sessions
that lacked them (418 FMP requests, no empty payloads), giving **100 % coverage in both
universes**, and the four columns are registered.

**The finding survived the control**, which is the part worth reporting:

| | market-blind B0 | market-aware B0 |
|---|---|---|
| Block 7 core Wald, discovery | 206.8 (p = 6.1 × 10⁻³⁹) | **241.7 (p = 3.0 × 10⁻⁴⁶)** |
| Block 7 core Wald, validation | 17.78 (p = 0.059) | 17.59 (p = 0.062) |
| Block 10 SPA p, discovery | 0.0010 | 0.0010 |
| Block 10 SPA p, validation | 0.723 | 0.644 |

Controlling for the market makes the discovery increment *stronger*, not weaker. The
hypothesis that part of the option-flow signal was market beta is refuted by the test built to
check it.

**Proof:** `tests/contract/test_feature_registry_reaches_the_panel.py` now fails if a
registered feature is missing from its panel, and equally if a panel column is neither a
registered feature nor a **declared** diagnostic. The market controls escaped for the whole
programme because there was no list for them to be absent from.

### 1.8c The B2 registry claimed four features the builder cannot produce

Found by the same test. Concentration and arrival-shape statistics are not prefix-summable, so
the builder computes them on the 5-minute window only, while `b2_features()` generated them for
both windows. `build_design` skips absent columns — "so a partially built panel degrades to a
smaller design rather than crashing" — so the over-claim never surfaced.

The registry now generates them for the concentration window alone: **58 features, not 62**.

### 1.9 The surface and the flow were built from the same rows

`rp2_block5_surface_panel.py` read `[origin - 1920 s, origin - 120 s]`. The 30-minute window
in `rp2_block6_flow_panel.py` read `[origin - 1920 s, origin - 120 s]`. The same interval.

The programme's question is whether trade flow adds information beyond the option surface.
Asked of feature blocks cut from one tape over one interval, part of the answer is B2
compared against a surface partly composed of the same trades.

B1's snapshot now ends where B2's longest window begins — `[origin - 5520 s, origin - 1920 s)`
against `[origin - 1920 s, origin - 120 s]` — and `assert_disjoint_from_flow_window` fails the
run if the two constants ever drift back into overlap.

This buys row-disjointness, not independence. A contract appears in the surface only because
somebody traded it, so quote *selection* is still driven by flow. That limitation is stated in
the module docstring and the block document rather than left for a reader to infer.

**Proof:** `tests/unit/test_rp2_block_windows.py::test_the_two_windows_are_disjoint_on_a_concrete_origin`
imports both scripts and compares the shipped constants, so a change to either one is caught.

### 1.10 Every tenor was rounded to whole calendar days, with a floor of one

`tenor = maximum((expiry - session).days, 1.0)`. A contract expiring at 16:00 on the session
being processed was priced as a one-day option. At noon it has four hours of variance left;
one day claims six times that. The error is largest exactly where option activity concentrates,
and the affected contracts were 0DTE — the fastest-growing part of the market.

Time to expiry is now measured to the 16:00 ET close from the origin itself, in seconds. An
expired contract returns 0 and is dropped rather than priced.

**Proof:** `tests/unit/test_rp2_surface_forward.py::test_a_contract_expiring_this_afternoon_is_not_a_one_day_option`.

### 1.11 Moneyness and delta assumed zero rates and zero dividends

`black_scholes_delta` documented zero rates as a simplification "well under the width of a
delta bucket". At a 4-5% financing rate and a 90-day tenor the forward sits about 1% above the
spot, which moves a 25-delta strike by several delta points: the quote being read as the
25-delta wing was not the 25-delta wing. `put_call_parity_residual` compared against `S - K`,
so it reported financing as though it were a quote-quality defect.

The forward is now **measured, not assumed**, and not by plugging in an external curve either.
Put-call parity is an arbitrage identity: at one expiry, `C - P = D (F - K)` exactly. Fitting
that line across co-strike pairs returns the discount factor and the forward the market is
actually quoting, including whatever borrow and dividend it embeds. The implied rate and
implied dividend yield fall out as by-products, with a residual.

The measurement is honest about its own noise. Co-strike mids come from different instants, so
the underlying moves between them; at a 30-day tenor that noise produces implied rates across a
decile band of roughly ±30%. Fits outside a plausibility band are refused, the forward falls
back to the spot for those expiries, and the number of expiries where parity *did* fit travels
with the panel as `b1_forward_expiries_fitted`.

**Proof:** `::test_the_forward_is_measured_from_the_quotes_not_assumed_to_be_the_spot`,
`::test_the_parity_residual_no_longer_reports_financing_as_a_quote_defect`,
`::test_an_implausible_implied_rate_is_flagged_rather_than_used`.

### 1.12 Spread legs were counted as directional trades

The side tag on a multi-leg print describes how that leg crossed the NBBO, not what the trader
was expressing: the short leg of a call vertical prints `bid_side` while the order is bullish.
Every signed channel — `buy_premium_share`, and all the Greeks-weighted flows, which multiply
by `direction` — was therefore reading direction out of structures that have none.

Multi-leg prints are identified from the rise in the contract's running `multi_vol` total and
are now unsigned. They are not discarded: they still count as volume, and their share of the
window is a feature.

**Proof:** `tests/unit/test_rp2_block_windows.py::test_a_spread_leg_contributes_volume_but_no_direction`
and the three cases around it.

### 1.13 A missing provider field was indistinguishable from an empty market

`_optional_number` returned `None` for both "the key is present and null" and "the key is not
there". The first is a real market state; the second is schema drift. A vendor shipping
`bidPrice` instead of `bid_price` would have produced a complete series of quotes with no bid —
which reads as a quiet market, not as a broken parser.

An absent key now raises `MASSIVE_FIELD_MISSING`; a present null still means an empty window.

**Proof:** `tests/contract/test_provider_contract_validation.py::test_an_empty_quote_window_survives_while_a_dropped_field_does_not`,
plus a removal matrix over every declared field of all four parsers.

### 1.14 Block documents quoted digests of artifacts that no longer exist

Three block documents carried a `sha256` for a run whose artifact had since been re-run. The
digest still *looked* like provenance while matching nothing on disk — the failure mode is that
a re-run silently orphans its own documentation.

`tests/contract/test_documentation_references.py` now collects every digest quoted in a
headline or block document and requires that the repository hold it somewhere: the frozen
registry, an artifact, or a pointer file. The same suite requires every path a document names
to resolve, which is the cheaper half of the same problem.

---

## 2. Requirement-by-requirement status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | registry-driven CANONICAL_STATE / STATUS / claims, CI drift, link and hash checks | **DONE** | drift test regenerates and compares; `tests/contract/test_documentation_references.py` adds the link check, the quoted-digest check and an existence check over the generator's authorised sources — it caught three block documents quoting digests of superseded runs |
| 2 | byte SHA-256 + schema/row/time/provider provenance | **DONE** | `src/mds650/rp2/provenance.py` **wired in** by `scripts/rp2_provenance_stamp.py`, which writes a provenance sidecar per block (`artifacts/rp2_block5_surface/provenance.json` and seven more) and re-hashes on `--verify`; 15 tests. The module existed with tests but no caller until this pass — machinery nothing invokes is not provenance |
| 3 | fail-closed required inputs, unique origin keys, 1:1 joins | **DONE** | `src/mds650/rp2/panel.py`; `tests/unit/test_rp2_panel.py` (5 tests) |
| 4 | XNYS calendar, early closes, no backward fill, no future dependence | **DONE** | `src/mds650/rp2/bars.py`; `tests/unit/test_rp2_bars.py` (16 tests) |
| 5 | PIT EWMA / B0 per asset from observed returns | **DONE** | `ewma_variance` expanding seed + `ewma_variance_by_asset`; `tests/unit/test_rp2_baseline.py::test_ewma_is_point_in_time_and_cannot_see_the_future` |
| 6 | independent Massive B1, exact expiry, 0DTE, rates/dividends/forward, constrained surface, rename VRP | **DONE** | exact tenor to the 16:00 ET close (§1.10); forward, rate and dividend yield **measured** from co-strike put-call parity (§1.11) — parity residual falls 34 bp → 8.8 bp; butterfly convexity and coverage flags; VRP renamed. Source independence is now **measured rather than asserted**: `scripts/rp2_block5b_independent_surface.py` rebuilds the surface at 36 origins from the *listed* chain, quoted contract by contract from an independent feed, over a matched moneyness span. Trade selection understates put skew by 46 % (t = −3.56) and leaves the at-the-money level essentially unbiased (−0.0010 in vol, t = −2.83) — so `b1_iv_30d` is near-free of it and the skew features are not (decision 77) |
| 7 | B2 dual clocks, sided OTM, normalised concentration, multileg, quote impact, latency, rename Hawkes | **DONE** | dual clocks with latency features, sided OTM, normalised concentration, quote impact, the rename — and multi-leg prints identified from the running `multi_vol` total and made unsigned (§1.12). The dual-clock code had shipped reading a column it never declared, so it had never actually run; a test now compares columns read against columns declared |
| 8 | reclassify used D/V as exploratory; never inspect the confirmation cohort | **DONE** | decision 67; `docs/DISCOVERY_VALIDATION_CONFIRMATION_PROTOCOL.md` §2b; `sealed_cohorts_read = 0` throughout |
| 9 | session-aggregated, session-blocked, family-matched inference; CW only nested linear; purged DML; multiplicity | **DONE** | `aggregate_by_session`, `session_block_bootstrap`, `clark_west_terms(nested_linear=…)`; decision 68; DML already used purged time-block folds |
| 10 | blocked full-pipeline power simulation replacing ex-post max-\|t\| | **DONE** | `src/mds650/rp2/power.py`; `tests/unit/test_rp2_power.py` (10 tests); decision 69; old rows relabelled `ex_post_max_t_INVALIDATED` in Supabase |
| 11 | forward-return contract-level delta-hedged P&L | **DONE** | `scripts/rp2_block11b_forward_economics.py` calls them: one contract per origin chosen point-in-time from what was quoted at entry, entered at the ask, exited at the bid, delta-hedged at the entry delta, fees and slippage per contract per side, book capped per name and in gross. Every net Sharpe is negative — −23.8 to −24.1 in discovery (5,758 legs), −38.8 to −41.3 in validation (954) — with cost at 71 % and 148 % of gross P&L and every deflated Sharpe at 0.000. The proxy reported +77 (decision 78) |
| 12 | Supabase migrations: types, constraints, provenance, staging/publish, RLS | **DONE** | migrations `rp2v2_ingestion_provenance_and_constraints`, `rp2v2_private_base_public_views_rls`; verified: 4 public views, 39 CHECKs, **0 policies on any licensed origin-level table** |
| 13 | provider contract validation without leaking secrets or licensed raw data | **DONE** | `tests/contract/test_provider_contract_validation.py`: a removal matrix over every declared field of all four parsers, a rename case, type-sensitive schema fingerprints, URL-sanitisation cases including repeated and fragment-hidden secrets, a credential scan over committed fixtures, and a check that parsed records expose only declared fields. It found that a missing field was indistinguishable from an empty market (§1.13). No network call, so it runs on a runner with no credentials |
| 14 | adversarial tests | **DONE** | content mutation, missing inputs, join cardinality, early closes, future invariance, EWMA PIT, sided OTM, concentration normalisation, session bootstrap, matched inference (CW refusal), forward economics, power selection shrinkage, window disjointness, exact expiry, parity forward, butterfly convexity, surface coverage, multi-leg attribution, provider field removal, credential leakage — 88 new tests |
| 15 | README / STATUS / CLAIMS concise and honest | **PARTIAL — honest, deliberately not shorter** | no claim of B1 > B0, B2 > B1 or alpha survives anywhere; decisions 67-69 and 74-75 withdraw six figures and one replication claim; stale counts refreshed (75 decisions, 1,346 tests, 15 gated datasets). The README grew rather than shrank, because stating what was withdrawn and why costs more words than the claim did. Trimming the plain-language glossary and the non-specialist reading path would shorten it at the cost of the audience it was written for, so it was not done — recorded as a judgement call, not an oversight |

**Fourteen of fifteen are done.** The one partial is requirement 15, and it is a judgement
call recorded in the row itself rather than an omission: the README grew because stating what
was withdrawn costs more words than the claim did.

### Claims withdrawn by this branch

Withdrawn rather than restated, because the method or the data that produced them is now known
to be wrong:

* every **Clark-West figure for a tree family** (decision 68) — the adjustment has no
  derivation outside nested linear models;
* the **direction-contrast power figure** of 42 sessions and the **variance figure of 537**
  (decision 69) — both evaluate a closed form at an effect selected as the largest of many,
  which is the winner's curse expressed as an effect size. The verdict they supported (60-120
  sessions cannot detect anything here) survives, because selection can only push the
  requirement up;
* the **variance-risk strategy Sharpe** — it traded every period and measured unconditional
  carry, as `docs/rp2/block11_economics_v1.md` §2 already stated;
* the claim that **two Block 7 treatments replicated across the two samples**. On the rebuilt
  panels the discovery evidence is far stronger (Wald 206.8, p = 6 × 10⁻³⁹ against the previous
  76.1, p = 3 × 10⁻¹²) and the second sample returns p = 0.059, with only the trade count
  keeping its sign. The earlier figures were measured on panels that discarded every
  early-close session, double-weighted 24 session-assets, and built B1 over the same interval
  as the flow it was compared against.

### What the rebuild changed, and in which direction

Reported because a rebuild that only ever improves a result is a rebuild worth distrusting.

| Quantity | Before | After |
|---|---|---|
| B0 panel origins | 183,744 | 184,632 |
| session-assets dropped as "too much missing data" | 54 | **0** |
| duplicated session-assets in the bars | 24, undetected | **0**, verified identical before collapsing |
| B1 contracts per snapshot (median) | 724 | 896 |
| B1 put-call parity residual (median) | 0.0034 | **0.00088** |
| Block 7 core Wald, discovery | 76.1 (p = 3 × 10⁻¹²) | 206.8 (p = 6 × 10⁻³⁹) |
| Block 7 core Wald, validation | 17.75 (p = 0.059) | 17.78 (p = 0.059) |
| Block 10 SPA p, discovery | 0.0070 (fails α₃ = 0.00417) | **0.0010 (clears it)** |
| Block 10 SPA p, validation | 0.0250 | **0.723** |

The discovery side got stronger and the validation side got weaker. Both moved because the
inputs were wrong, not because a test was changed, and the programme's conclusion is unchanged:
there is real structure in recent option flow, it is measured in one exploratory sample, it
does not reproduce in another, and neither sample is entitled to confirm it.

---

## 3. Gate results

Run on the branch head:

```
uv run ruff check src scripts tests      All checks passed!
uv run ruff format <touched files>       reformatted, then clean
uv run mypy src scripts                  Success: no issues found in 274 source files
uv run pytest tests -q                   0 failed
```

`ruff format` was applied to the files this branch touches, not repository-wide: formatting
152 untouched files would bury the remediation under a mechanical diff. That is a deliberate
scope decision, recorded here rather than left implicit.

---

## 4. What did not change, on purpose

* **No frozen artifact was overwritten.** Every artifact under `artifacts/rp2_block*/` is
  untouched; the renames above change future runs, not recorded ones.
* **No sealed cohort was read.** `sealed_cohorts_read = 0` holds across the whole programme.
* **No test was weakened.** Two test expectations changed, both because the *behaviour* they
  asserted was wrong: `herfindahl` on a single positive weight now returns NaN rather than 1,
  and the concentration extremes are asserted against the normalised form.
* **No result was re-run to a different sign.** The fixes in §1.3 and §1.4 change B2 feature
  values, so the Block 7 and Block 8 numbers on record were produced with the defective
  definitions. They are **not** restated here from the old artifacts as if they were
  unaffected; re-running them is part of the open work.
