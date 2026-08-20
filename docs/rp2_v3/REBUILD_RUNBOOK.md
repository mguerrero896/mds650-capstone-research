# Rebuilding RP2-v3

One command, one run id, one set of hashes.

```powershell
uv run python scripts/run_rp2_v3_pipeline.py `
    --data-root D:\MDS650 `
    --output-root artifacts\rp2_v3 `
    --run-id rp2-v3-20260820-001 `
    --roles D V `
    --forbid-sealed-cohorts
```

`--dry-run` prints the thirteen steps and exits without creating anything.

## What it runs, in this order

| # | Step | Producer |
| ---: | --- | --- |
| 1 | `validate-input-manifests` | internal - every file in `data/GATED_DATA_POINTERS.json` exists and still hashes as recorded |
| 2 | `build-targets` | `scripts/rp2_block3_target_panel.py` |
| 3 | `build-b0` | `scripts/rp2_block4_b0_panel.py` |
| 4 | `build-b1` | `scripts/rp2_block5_surface_panel.py` |
| 5 | `build-b2` | `scripts/rp2_block6_flow_panel.py` |
| 6 | `validate-feature-registry` | in-process, against this run's panels |
| 7 | `construct-common-masks` | in-process, one mask per role |
| 8 | `fit-model-ladder` | `scripts/rp2_block8_ladder.py` |
| 9 | `run-dml-diagnostics` | `scripts/rp2_block7_dml.py` |
| 10 | `run-incremental-inference` | `scripts/rp2_block10_inference.py` |
| 11 | `generate-scorecard` | `mds650.rp2.scorecard` |
| 12 | `generate-provenance` | `mds650.rp2.run_manifest` |
| 13 | `verify-artifact-hashes` | internal |

The run directory `artifacts/rp2_v3/<run_id>/` keeps the same layout as `artifacts/`: each
producer writes into its own `rp2_blockN_*` subdirectory. Flattening it would be tidier and
wrong - Block 4 and Block 8 both write a file called `ladder.json`, and the second would
replace the first with nothing recording that the baseline comparison had ever been there.

Blocks 5, 6, 7, 8 and 10 are given `--panel-root <run directory>`, so the run reads its own
panels rather than the previous run's: without it a rebuild would silently score last
week's B1 and label the result with this week's run id.

Steps 6 and 7 run inside the runner rather than as subprocesses, and they read the panels
this run just built. Importing the registry in a subshell would prove the configuration
parses, which is not the question that can fail: the question is whether the features the
registry names exist in *these* panels, whether they clear their coverage floors, and
whether the mask they imply is non-empty. Both steps leave an artifact -
`feature_registry_report.json` and `common_masks.json` - so the answer is on disk rather
than only in an exit code.

## What stops the run

- an input the manifest declares that is absent or whose bytes changed;
- a step that exits zero without writing the artifact it is supposed to produce;
- a path naming a sealed cohort - cohort C, phase 8, phase 9 - anywhere in its components;
- an artifact that already exists under this run id with a different hash;
- a scorecard field the schema requires that the run could not measure.

The last one is not a formality. `configs/rp2_v3_scorecard_fields.json` states what a
rebuild must report, and `assemble_scorecard` refuses to write a scorecard with a hole in
it: a metric reported as absent and a metric never computed look identical afterwards.

## Reproducibility

`run_manifest.json` carries a `scientific_sha256` over the run id, the commit, the data
root, the roles, the registry, input-manifest and model-config digests, the seeds, and
every step's command, exit code and artifact hashes. The execution clock, the runtime and
the peak memory are recorded beside it and are deliberately outside the hash: two runs of
the same inputs at the same commit must agree on the science and will not agree on when
they happened.

## Resuming

`--skip-panels` reuses the four panels already in the run directory instead of rebuilding
them, and fails if any of them is missing. It is for re-running the modelling steps after a
code change that cannot affect the panels; a change that can affect them needs a new run id.
