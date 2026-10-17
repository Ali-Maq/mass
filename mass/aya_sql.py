"""Run upstream RHI on independently evaluated AYA SQL workflow episodes.

This adapter does not execute agent code, evaluate SQL, or update model weights.
It snapshots development evidence and invokes the unmodified RHI search logic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from mass.io import ROOT, read_json, write_json

START = "Create an agent team with following agent candidates to solve this problem:"
END = "IMMUTABLE AYA EXECUTION BOUNDARY"
ENDPOINT = "https://api.inference.crusoecloud.com/v1"
MODEL = "deepseek-ai/DeepSeek-V4-Pro"
IMPLEMENTATION_FILES = (
    "mass/aya_sql.py",
    "harness_improvement/iterate_multi_agent_prompt.py",
    "harness_improvement/llm_backend.py",
    "evaluation/artifacts.py",
    "evaluation/bundle.py",
    "evaluation_claudecodex/pairwise_judge.py",
    "evaluation_claudecodex/pairwise_prompts.py",
    "evaluation_claudecodex/pairwise_schema.py",
)
INITIAL_DESIGN = """The coordinator reads the supplied schema and natural-language questions, then writes a SQL answer for every allowed read request and an explicit refusal for prohibited requests. It checks column order, grouping, NULL behavior, ordering and ties against the question before writing queries.json. It may ask one child reviewer to inspect ambiguous queries, then resolves that feedback itself. The reviewer cannot delegate. The coordinator owns the final output."""
BOUNDARY = """The contract.json and dataset.json supplied by the controller are immutable. The accepted query.py executor and the controller evaluator are fixed; do not rewrite either. Produce queries.json using the exact contract, with no extra IDs. Read only the public questions and fixture supplied for this episode; do not seek hidden tests or evaluator source. At most one child may be created, at concurrency one and depth one; that child must not delegate. The controller enforces the native runtime time and turn limits. Do not fetch external data or install dependencies. Record concise decisions and observable tool outputs, not private reasoning. Controller-owned results.json is the measured development evidence; self-reported results cannot replace it. A revised workflow is only a candidate until the independent controller evaluates it."""
OPTIMIZER_BUDGET = """Immutable workflow budget: at most one child in total, one concurrent child, maximum spawn depth one, child timeout 90 seconds, and at most 40 coordinator turns. The child cannot delegate. Optimize within this budget; do not propose parallel reviewer teams. The episode's public-tasks.json supplies its schema and questions separately. Never carry development questions into a held-out episode."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_json(path: Path, value: dict) -> None:
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f"Frozen input changed: {path}")
    else:
        write_json(path, value)


def freeze_bytes(path: Path, value: bytes) -> None:
    if path.exists():
        if path.read_bytes() != value:
            raise ValueError(f"Frozen input changed: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)


def prepare_task(source: Path, target: Path) -> None:
    raw = source.read_text()
    if START not in raw and END not in raw:
        raw = f"{raw.rstrip()}\n\n{START}\n{INITIAL_DESIGN}\n\n{END}\n{BOUNDARY}\n"
    elif (
        raw.count(START) != 1
        or raw.count(END) != 1
        or raw.index(START) >= raw.index(END)
    ):
        raise ValueError(
            "Task must contain both workflow markers exactly once, in order"
        )
    # Always append our runtime ceiling, even when a caller supplies a template.
    if BOUNDARY not in raw:
        raw = f"{raw.rstrip()}\n\n{BOUNDARY}\n"
    if OPTIMIZER_BUDGET not in raw:
        prefix, design = raw.split(START, 1)
        raw = f"{prefix.rstrip()}\n\n{OPTIMIZER_BUDGET}\n\n{START}{design}"
    freeze_bytes(target, raw.encode())


def snapshot_workspace(source: Path, target: Path) -> dict:
    """Copy an allowlist, never evaluator source, holdout files, or API secrets."""
    required = {
        "queries.json": "queries.json",
        "results.json": "results/metrics.json",
        "run_status.json": "run_status.json",
    }
    evidence = read_json(source / "results.json")
    if not isinstance(evidence, dict) or evidence.get("split") not in (
        "development",
        "dev",
    ):
        raise ValueError(
            "RHI accepts only controller-scored development results with split=development"
        )
    hashes = {}
    public_input = source / "public-tasks.json"
    if public_input.exists():
        public = read_json(public_input)
        if public.get("split") not in ("development", "dev"):
            raise ValueError("Public RHI input must be the development split")
        questions = public.get("questions")
        if not isinstance(questions, list) or any(
            not isinstance(item, dict)
            or not set(item) <= {"id", "db_id", "question"}
            or not {"id", "question"} <= set(item)
            for item in questions
        ):
            raise ValueError("Public RHI questions may not contain oracle fields")
        required["public-tasks.json"] = "public-tasks.json"
    for original, normalized in required.items():
        data = (source / original).read_bytes()
        json.loads(data)
        hashes[original] = hashlib.sha256(data).hexdigest()
        freeze_bytes(target / normalized, data)
    freeze_json(target / "snapshot.json", {"files": hashes, "split": "development"})
    # This index makes the actual query artifact visible to MASS's evidence bundler.
    freeze_json(
        target / "deliverables/index.json",
        {
            "artifacts": list(required.values()),
            "evaluation": "Independent SQLite result equivalence; development split only",
        },
    )
    report = (
        "# Development episode\n\nIndependent controller results:\n\n```json\n"
        + json.dumps(evidence, indent=2)
        + "\n```\n\nSubmitted queries:\n\n```json\n"
        + (source / "queries.json").read_text()
        + "\n```\n"
    )
    if public_input.exists():
        report += (
            "\nPublic development schemas and questions:\n\n```json\n"
            + public_input.read_text()
            + "\n```\n"
        )
    freeze_bytes(target / "research_report.md", report.encode())
    return hashes


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("propose", "compare"))
    for name in (
        "task-file",
        "workspace",
        "run-dir",
        "contract",
        "dataset",
        "evaluator",
    ):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--previous-workspace", type=Path)
    p.add_argument("--baseline-workspace", type=Path)
    p.add_argument("--version", type=int, default=0)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--timeout-seconds", type=float, default=150)
    p.add_argument("--max-output-tokens", type=int, default=4000)
    return p


def run(args: argparse.Namespace) -> dict:
    if args.version < 0 or (args.action == "compare" and args.version < 1):
        raise ValueError("Propose requires version >= 0; compare requires version >= 1")
    if args.version > 0 and (
        args.previous_workspace is None or args.baseline_workspace is None
    ):
        raise ValueError("Versions after zero require previous and baseline workspaces")
    if not os.environ.get("CRUSOE_API_KEY"):
        raise ValueError("Set CRUSOE_API_KEY in the process environment")
    run_dir = args.run_dir.resolve()
    rhi_dir, views = run_dir / "rhi", run_dir / "rhi-views"
    immutable_paths = {
        name: getattr(args, name).resolve()
        for name in ("task_file", "contract", "dataset", "evaluator")
    }
    frozen = {
        "sha256": {name: digest(path) for name, path in immutable_paths.items()},
        "implementation_sha256": {
            name: digest(ROOT / name) for name in IMPLEMENTATION_FILES
        },
        "model": args.model,
        "endpoint": ENDPOINT,
        "task": 1001,
        "format": 1,
        "max_output_tokens": args.max_output_tokens,
    }
    freeze_json(run_dir / "rhi-input-manifest.json", frozen)
    initial = run_dir / "rhi-task/query1001_ourTeam.txt"
    prepare_task(immutable_paths["task_file"], initial)
    current = views / f"v{args.version}" / "query1001_ourTeam"
    workspace_hashes = snapshot_workspace(args.workspace.resolve(), current)
    if args.version:
        previous = views / f"v{args.version - 1}" / "query1001_ourTeam"
        snapshot_workspace(args.previous_workspace.resolve(), previous)
        snapshot_workspace(
            args.baseline_workspace.resolve(), views / "reference/query1001"
        )
        query = rhi_dir / f"updated_queries/query1001_ourTeam-v{args.version}.txt"
        if not query.is_file():
            raise ValueError(f"Run the preceding proposal first: {query}")
    else:
        query = initial
    # Generated candidates may change the design block only.
    original = initial.read_text()
    candidate = query.read_text()
    if (
        candidate.count(START) != 1
        or candidate.count(END) != 1
        or candidate.split(START)[0] != original.split(START)[0]
        or candidate.split(END)[-1] != original.split(END)[-1]
    ):
        raise ValueError("Candidate changed immutable task or execution boundary")
    command = [
        sys.executable,
        "-m",
        "harness_improvement.iterate_multi_agent_prompt",
        "--query-file",
        str(query),
        "--current-version",
        str(args.version),
        "--current-repo",
        str(current),
        "--current-run-status-file",
        str(current / "run_status.json"),
        "--out-dir",
        str(rhi_dir),
        "--end-marker",
        END,
        "--llm-backend",
        "hosted-chat",
        "--model",
        args.model,
        "--base-url",
        ENDPOINT,
        "--api-key-env",
        "CRUSOE_API_KEY",
        "--temperature",
        "0.2",
        "--max-output-tokens",
        str(args.max_output_tokens),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--context-window-tokens",
        "64000",
        "--context-safety-tokens",
        "4000",
        "--max-design-chars",
        "7000",
        "--target-design-chars",
        "4000",
        "--json-max-tokens",
        "14000",
        "--code-max-tokens",
        "3000",
        "--results-json-total-max-chars",
        "40000",
        "--include-best-design",
        "--history-design-diffs",
        "--include-v0-design",
        "--submission-label",
        "the bounded Hermes SQL workflow",
    ]
    if args.version:
        command += [
            "--previous-repo",
            str(previous),
            "--judge-vs-baseline",
            "--baseline-repo-root",
            str(views / "reference"),
            "--champion-repo-v0-root",
            str(views / "v0"),
            "--champion-repo-root-pattern",
            str(views / "v{version}"),
        ]
    if args.action == "compare":
        command += ["--evaluate-only"]
    receipt_path = run_dir / f"rhi-{args.action}-v{args.version}.json"
    if receipt_path.exists():
        cached = read_json(receipt_path)
        if args.action == "propose":
            if digest(Path(cached["workflow_path"])) != cached["workflow_sha256"]:
                raise ValueError(
                    "Recorded workflow changed after the successful proposal"
                )
        elif read_json(Path(cached["retained_workflow_path"])) != cached["retained"]:
            raise ValueError("Retained workflow verdict changed after comparison")
        return cached
    log_dir = run_dir / "rhi-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    lock = run_dir / ".rhi.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with (log_dir / f"{args.action}-v{args.version}.log").open("w") as log:
            process = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds * 5 + 60,
                check=False,
            )
        if frozen["sha256"] != {
            name: digest(path) for name, path in immutable_paths.items()
        }:
            raise ValueError("Immutable controller inputs changed during the RHI call")
        if frozen["implementation_sha256"] != {
            name: digest(ROOT / name) for name in IMPLEMENTATION_FILES
        }:
            raise ValueError("RHI implementation changed during the call")
        snapshot_workspace(args.workspace.resolve(), current)
        if process.returncode:
            raise RuntimeError(
                f"RHI exited {process.returncode}; inspect {log_dir / f'{args.action}-v{args.version}.log'}"
            )
        result = {
            "action": args.action,
            "version": args.version,
            "task": 1001,
            "backend": "hosted-chat",
            "model": args.model,
            "endpoint": ENDPOINT,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "workspace_sha256": workspace_hashes,
            "immutable_sha256": frozen["sha256"],
            "rhi_dir": str(rhi_dir),
            "weight_update": False,
            "acceptance_authority": "independent controller evaluator",
        }
        if args.action == "propose":
            output = (
                rhi_dir / f"updated_queries/query1001_ourTeam-v{args.version + 1}.txt"
            )
            text = output.read_text()
            if (
                text.count(START) != 1
                or text.count(END) != 1
                or text.split(START)[0] != original.split(START)[0]
                or text.split(END)[-1] != original.split(END)[-1]
            ):
                raise ValueError(
                    "RHI output changed immutable task or execution boundary"
                )
            result.update(
                workflow_path=str(output),
                workflow_sha256=digest(output),
                next_version=args.version + 1,
            )
        else:
            result.update(
                retained_workflow_path=str(rhi_dir / "retained_workflow.json"),
                retained=read_json(rhi_dir / "retained_workflow.json"),
            )
        write_json(receipt_path, result)
        return result
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    args = parser().parse_args()
    try:
        print(json.dumps(run(args), indent=2))
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
