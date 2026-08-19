# Block 5b — how much of the traded surface is an artefact of what traded

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block5b_independent/independent_surface.json`
(`independent_sha256 = 5836474468fbf0e7baace517274d0d60874c2d2a72dc66ad555f3bedc2d0dac3`)
**Code:** `scripts/rp2_block5b_independent_surface.py`
**Decision:** 77

---

## 1. The limitation this measures

B1 is reconstructed from the NBBO carried on option *trades*. Block 5 made B1 and B2 read
disjoint row windows, which removes the mechanical overlap between them, and said plainly that
it does not remove the **selection**: a contract enters the surface only because somebody
traded it.

Rebuilding all 184,632 origins from an independent quote feed is not affordable. The listed
chain runs to roughly a thousand contracts per underlying per session; at one directed quote
per contract per origin that is millions of requests. So the bias is measured on a designed
subsample instead of being asserted.

## 2. The design

At each sampled origin the same surface is built twice:

* **traded** — the latest NBBO carried on a trade, exactly as Block 5 does it;
* **listed** — one directed quote per contract from the chain the exchange *published*,
  whether or not it traded.

Two disciplines make the comparison mean something.

**The listing is taken `as_of` the session.** Without that the reference endpoint answers with
today's chain, which for a historical session includes contracts that had not been listed yet.
Asking for their quotes returns silence, and reading that silence as an illiquid strike would be
a look-ahead wearing the costume of a data gap. With `as_of`, **zero of
1,152 directed quotes came back empty**; without it three quarters did.

**The moneyness span is matched.** The listed side samples the strikes nearest the money, so it
spans a narrower range than the traded side, and a quadratic fitted over a narrower range has a
different slope for reasons that have nothing to do with what traded. The traded surface is
therefore restricted to the listed side's own span before the two are compared. Before matching,
the slope difference read t = −7.73; after matching it reads t = -3.56. Half of that
statistic was the sampling, and it would have been reported as the effect.

## 3. The result

36 paired origins over 12 session-assets,
1,152 directed quotes, 72 listings, no chain
download.

| | traded (span-matched) | listed | difference | t |
|---|---|---|---|---|
| smile level (ATM) | 0.3083 | 0.3069 | -0.0010 | **-2.83** |
| smile slope | -0.2485 | -0.4611 | -0.1936 | **-3.56** |
| smile curvature | 2.420 | 1.149 | -9.049 | -0.95 |

**Trade selection flattens the skew.** The listed surface carries a slope of
-0.461 against the traded surface's -0.248: building the
surface only from contracts that traded **understates put skew by about 46 %**. The strikes that
actually trade are tilted toward the side where implied volatility is lower.

**It leaves the level alone.** The at-the-money difference is
-0.0010 in volatility — a tenth of a volatility point
on a level of 0.31. Statistically separable at t = -2.83,
economically negligible. `b1_iv_30d`, the surface feature every later block consumes, is
therefore near-free of this bias.

**Curvature is not distinguishable** (t = -0.95).

## 4. What this licenses, and what it does not

The level-based B1 features may be read as they stand. **Any claim resting on the skew features
carries a 46 % understatement**, and this document is the correction to apply.

It does not license treating B1 as source-independent. 36 origins is a
measurement of the bias, not a rebuild of the panel without it. The panel remains trade-sourced
and the correction remains external to it.
