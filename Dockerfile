# Computational-reproducibility container (decision 63).
# Proves the full methodological pipeline runs from a clean clone with zero
# licensed data: hermetic test suite + the synthetic end-to-end demo.
#
#   docker build -t mds650-repro .
#   docker run --rm mds650-repro                          # hermetic suite + demo
#   docker run --rm mds650-repro uv run python scripts/run_public_repro_demo.py
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY . .
RUN uv sync --locked

# ponytail: same four tier-2-only ignores as .github/workflows/ci.yml
CMD ["bash", "-lc", "uv run pytest tests -q \
  --ignore=tests/unit/test_generate_date_level_pit_preflight_plan_v1.py \
  --ignore=tests/unit/test_independent_replication_panel.py \
  --ignore=tests/unit/test_date_level_pit_preflight_request_budget_v1.py \
  --ignore=tests/contract/test_b2_confirmation_inputs.py \
  && uv run python scripts/run_public_repro_demo.py"]
