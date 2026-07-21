# MDS650 research pipeline

This repository contains the local, modular source of truth for the MDS650
point-in-time options research pipeline. It is research-only: it does not submit
orders, send email, publish externally, or perform a historical backfill before
the provider and pilot gates pass.

The current implementation phase is fixture-first. Provider credentials are
loaded from the environment and are never written to source, manifests, logs,
or notebooks.
