# Provider license review (v1, 2026-08-18)

Scope: what the **public mirror** (github.com — filtered history) and the **gated
Supabase bucket** actually expose, read against the exact public Terms of Service of
the three data providers, retrieved 2026-08-18. This review covers the public
self-service terms only; any account-specific addendum (order form, enterprise rider)
in the owner's email or dashboard would supersede it. This is a documented reading by
the research team, not legal advice.

## What we publish, factually

| Surface | Content | Raw provider values? |
|---|---|---|
| Public repo (mirror) | Code, docs, governance, aggregate results (`results.json` deltas, p-values, tables), small stability/audit summaries, synthetic fixtures (`pilot_preview/fixture_*` — generator "deliberately never calls a provider") | **No** (after the 2026-08-18 remediation below) |
| Gated Supabase bucket (private) | 15 files (~135 MB): per-origin model forecasts, engineered features, IV attempt/failure diagnostics | Yes at row level (derived per-origin values; one diagnostic CSV with real contract IDs, SIP timestamps, quote midpoints) |
| Not stored in either | Raw provider payloads (1-min bars, tape archives, quote sweeps) — live only on the owner's local `D:/MDS650` | — |

**Remediation applied in this review:** `artifacts/b2_confirmation/b1/b1_iv_failures_20d.csv`
(real OCC contract symbols, `sip_timestamp`, quote `midpoint`, `relative_spread` per row)
was found tracked in the public history. It was moved to the gated set (pointer +
Supabase upload verified 15/15) and is stripped from the whole published history by
`publish_mirror.sh`. A standing tripwire test now fails the suite if any tracked CSV
outside fixtures carries quote-level columns
(`tests/test_gated_publish_contract.py::test_no_quote_level_csv_reaches_the_mirror`).

## Financial Modeling Prep (FMP)

Source: https://site.financialmodelingprep.com/terms-of-service (last updated 2023-08-01).

Exact clauses that bind:

- §2.2: "…without the prior written approval of FMP, the Customer may not distribute,
  publicly perform or display, lease, sell, transmit, transfer, publish, edit, copy,
  create derivative works from … or otherwise make unauthorized use of the Services."
- §2.2.1 (Personal Use): license "strictly for their own personal, non-business and
  non-commercial purposes"; "may not share FMP Services or Data, resell, … integrate
  the Data or Services into any tools or applications accessible by any third parties."
- §2.2.2 (Data Display): "customers are prohibited from showcasing FMP Services or
  Data on platforms including but not limited to websites, blogs, software products,
  or applications…" without a specific agreement.
- §2.6.1: shall not "resell, sublicense, distribute or otherwise provide access to The
  Services, **or data or information contained in or derived from The Services**, to
  any third party."
- §6.3: on termination, "Customer must delete all Data it has received from FMP…"
- §10.4: "…Customer may not identify FMP as the source of the Data to any third party
  without FMP's prior written consent…" (drafted inside the security-incident section
  but worded generally).

Reading vs what we publish: raw FMP bars are neither in the public repo nor in the
bucket — compliant. The exposure is the broad "derived from" language (§2.2, §2.6.1):
a maximal literal reading could reach even statistical aggregates; the ordinary
academic reading (results of the customer's own analysis, no recoverable data values)
treats the published tables as the researcher's work. §10.4 additionally makes even
*naming FMP as the source* consent-gated on a literal reading — while academic norms
(and FMP's own visibility interest) point the other way. Residual: **low for
aggregates, but not zero; attribution clause is an oddity worth clearing in writing.**

## Unusual Whales (UW)

Source: https://unusualwhales.com/terms (terms last updated 2021-06-15; API section
current as retrieved 2026-08-18).

Exact clauses that bind:

- §4: "YOU AGREE … NOT TO REDISTRIBUTE ANY DATA YOU RECEIVE THROUGH YOUR USE OF THE
  SITE OR PRODUCTS." §4A: "You MAY NOT copy, modify, scrape, reproduce, republish,
  distribute, or transmit any of the website material for ANY reason … strictly for
  PERSONAL USE."
- §5: "limited license to use its contents for personal or internal company use only."
- API RESTRICTIONS: "you shall not: (a) redistribute, resell, … publish, broadcast, or
  otherwise share the Data **or any data derived from the Data** with any third party
  … **Redistribution of Data includes the distribution of derived data.**"
- NON-PROFESSIONAL USE: "The standard, self-serve API is strictly for non-professional,
  personal use. If … you wish to redistribute the Data … you must obtain a separate
  enterprise license."
- SUSPENSION AND TERMINATION: "Upon termination … you must cease all use of the API
  and Data and delete any stored or cached Data in your possession."

Reading vs what we publish: UW's is the most explicit "derived data" clause of the
three. Raw tape archives never leave the owner's machine — compliant. Per-origin
derived rows are only in the private bucket (not published; each grant of access is an
owner decision — see "Bucket access" below). Published aggregates (deltas, p-values)
are analysis conclusions with no recoverable UW values; the clause does not carve out
academic use, so the strictest reading is not formally excluded. Residual: **low for
aggregates; bucket grants should stay per-request and academic.**

## Massive

Source: https://massive.com/legal/market-data-terms-of-service (retrieved 2026-08-18).

Exact clauses that bind:

- §1: license "for personal, non-business, and non-commercial purposes … you may not
  use the Market Data for any business or commercial purpose."
- §2: Market Data "may not be copied, reproduced, republished, uploaded, posted,
  publicly displayed … or distributed in any way … for publication or commercial
  enterprise" without express written consent.
- §5(c): shall not "redistribute, display, disseminate, … publish, broadcast, transmit,
  distribute … or otherwise transfer the Market Data — **or any data, charts,
  analytics, research, or other works based on, referring to, or derived from the
  Market Data ('Derived Works')**" without consent.
- §5(d): no non-display use / derivative works ("any index, indicative value, …
  investment strategy") "unless you are licensed to do so."
- No academic/research carve-out exists in the document.

Reading vs what we publish: Massive's §5(c) is the broadest clause in this review —
literally it covers "research … derived from the Market Data", which would include any
published QLIKE table whose models consumed Massive quotes. The quote-level failure
CSV found on the public mirror was the one concrete violation-shaped exposure under
§2/§5(c); it is now gated (see remediation above). For the remaining aggregates the
same low-but-nonzero reading applies as for FMP/UW. Residual: **highest of the three
on paper; the remediation removed the only row-level exposure.**

## Consolidated verdict

| Item | Status |
|---|---|
| Raw provider data in public repo | **None** (synthetic fixtures only; verified by schema scan of every tracked parquet/CSV, 2026-08-18) |
| Quote-level derived rows in public repo | **Removed** — `b1_iv_failures_20d.csv` gated; tripwire added |
| Per-origin derived data | Private bucket only; SHA-256 pointers public, values not |
| Published aggregates (tables, deltas, p-values) | Low residual risk under all three ToS; "derived data" clauses have no academic carve-out, so risk is not formally zero |
| FMP attribution clause (§10.4) | Open oddity: naming FMP as source is literally consent-gated |
| Account-specific addenda | Not reviewed (owner's email/dashboard; self-service plans normally have none) |

## Bucket access discipline (binding)

Sharing a signed URL **is** distribution under all three ToS. Grants from the gated
bucket stay: (1) per-request, (2) owner-approved, (3) academic-evaluation scope
(supervisor, examiners), (4) logged. No standing public links, no tokens in the repo.

## The one step that closes the residual completely

A short written consent from each provider ("customer may publish aggregate
statistical results derived from the data in an academic thesis and public research
repository, with attribution") converts every low-but-nonzero cell above to zero and
simultaneously clears FMP §10.4. Contacts: info@financialmodelingprep.com,
support@unusualwhales.com, Massive support. Drafting these three emails is a
five-minute task the owner can trigger at any time; sending them is the owner's call
(standing instruction: Claude drafts, never sends).
