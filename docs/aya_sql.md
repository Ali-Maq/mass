# AYA SQL workflow experiment on Crusoe

This integration runs MASS's actual recursive harness improvement (RHI) module
against SQL episodes executed by AYA's bounded Hermes worker in OpenShell.
The optimizer and in-loop judge use an explicitly selected Crusoe-hosted model.
The accepted SQL executor stays fixed. What changes is the workflow that turns
natural-language requests into queries.

This is a task-1001 adaptation of the upstream workflow-search stage. It is not
a reproduction of the paper's full training run. A complete MASS cycle also
collects trajectories from eligible workflows, ranks them, builds an SFT dataset,
updates weights and evaluates the resulting model. No weight update is performed
by this adapter. An API response or workflow revision alone is not evidence of
improvement.

## Controller inputs

The AYA controller owns the frozen contract, public development dataset and
evaluator. It separately executes bare-baseline, initial-workflow and revised-
workflow episodes. Each workspace supplies:

| File | Meaning |
| --- | --- |
| `queries.json` | Actual worker-generated SQL or explicit refusals |
| `results.json` | Controller-scored metrics with `split: development` |
| `run_status.json` | Native episode status and trace provenance |

Task 1001 is separate from the paper's original task split. Its minimal task text
is in [query1001.txt](../tasks/bare/query1001.txt). The controller may supply its
own task file. Plain task text receives an initial workflow and an immutable
execution boundary. A supplied template must contain exactly one start marker
`Create an agent team with following agent candidates to solve this problem:`
and one end marker `IMMUTABLE AYA EXECUTION BOUNDARY`.

The boundary permits at most one child at concurrency one and depth one, with no
child delegation. The native controller must enforce these limits independently.
A prompt boundary is not an operating-system isolation mechanism.

## Run a proposal

Install `requirements-core.txt` and supply `CRUSOE_API_KEY` through the process
environment. The key is never written to an artifact or passed as a CLI argument.
From this repository:

```bash
python -m mass.aya_sql propose \
  --task-file tasks/bare/query1001.txt \
  --workspace /path/to/run/v0 \
  --run-dir /path/to/run \
  --contract /path/to/run/contract.json \
  --dataset /path/to/run/dataset.json \
  --evaluator /path/to/controller/sql_benchmark.py \
  --version 0
```

The adapter invokes `harness_improvement.iterate_multi_agent_prompt` with
`--llm-backend hosted-chat`. It uses the original RHI optimizer and comparison
logic. The hosted transport sends standard Chat Completions JSON requests and
does not send vLLM-specific sampling fields. The default model is
`deepseek-ai/DeepSeek-V4-Pro`; `--model` selects a different model explicitly.

The JSON response includes `workflow_path`, pointing to
`rhi/updated_queries/query1001_ourTeam-v1.txt`. The controller executes that full
template in the next bounded Hermes episode and independently creates `v1`'s
metrics. Passing an output file to this command does not execute it.

## Compare the measured episodes

```bash
python -m mass.aya_sql compare \
  --task-file tasks/bare/query1001.txt \
  --workspace /path/to/run/v1 \
  --previous-workspace /path/to/run/v0 \
  --baseline-workspace /path/to/run/baseline \
  --run-dir /path/to/run \
  --contract /path/to/run/contract.json \
  --dataset /path/to/run/dataset.json \
  --evaluator /path/to/controller/sql_benchmark.py \
  --version 1
```

This calls upstream `--evaluate-only` with fixed-reference judging and champion
arbitration. `retained_workflow_path` points to the actual RHI verdict. The
independent controller should reject regressions even when the model judge
prefers a candidate, then evaluate the selected workflow on a final held-out
split. Ties do not establish superiority. A small SQL benchmark does not support
a general claim that this system outperforms other coding agents.

To continue search, use `propose` at version 1 with the same previous and baseline
arguments. This compares the measured version and proposes version 2. Preserve
each version workspace. `compare` ends search without producing an unused next
workflow.

## Evidence and integrity

- `rhi-input-manifest.json` freezes task, contract, dataset and evaluator hashes,
  along with model and endpoint. Changing them requires a new run directory.
- `rhi-views/` contains an allowlisted snapshot of development evidence. Evaluator
  source, held-out outputs and arbitrary workspace files are never copied.
- `rhi/` contains the upstream prompts, model output, usage, versioned workflow
  designs and pairwise comparison records.
- `rhi-propose-v0.json` or `rhi-compare-v1.json` is written only after success.
  Successful retries reuse the recorded receipt after integrity checks.
- `rhi-logs/` preserves errors and upstream diagnostics. A failed request is not
  shown as a completed experiment.

Hosted cost is `null`, not `$0`, when no price estimate is available. Response
IDs, served model and token counts are retained. The optimizer sees development
results only; the evaluator is referenced by hash, not inserted into its prompt.

## Validation

```bash
python -m unittest discover -s tests -v
python tools/check_source.py
```

Offline transport and integrity tests use fixtures and are labeled accordingly.
Only saved provider response receipts establish that a live RHI call occurred.
The real native episode traces establish execution; SQLite result comparison
establishes functional correctness.

## Public database tasks

New experiments can provide `public-tasks.json` in each development workspace.
The adapter copies this file into the evidence bundle and its research report.
The file must identify the development split. Questions may contain only `id`,
`db_id`, and `question`. Reference SQL and held-out context remain outside RHI.

The optimizer now receives its immutable runtime budget before the design marker:
one child in total, concurrency one, depth one, a 90-second child timeout, and
40 coordinator turns. Each episode reads its own public input file. A revised
workflow must not embed development questions for later held-out use.

Historical receipts remain under their original implementation hash. Use a fresh
run directory after changing the adapter; frozen runs reject implementation drift.
