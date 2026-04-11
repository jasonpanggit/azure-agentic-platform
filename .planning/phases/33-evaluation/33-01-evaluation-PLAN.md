---
id: "33-01"
phase: 33
plan: 1
wave: 1
title: "Foundry Evaluation + Quality Gates — All Chunks"
objective: "Instrument every agent with azure-ai-evaluation agentic evaluators, build 4 custom AIOps evaluators (SopAdherence, DiagnosisGrounding, RemediationSafety, TriageCompleteness), create a CI eval pipeline that gates on quality scores, and add sample traces + GitHub Actions workflow."
autonomous: true
gap_closure: false
files_modified:
  - "services/api-gateway/evaluation/__init__.py"
  - "services/api-gateway/evaluation/custom_evaluators.py"
  - "services/api-gateway/evaluation/agent_evaluators.py"
  - "services/api-gateway/evaluation/eval_pipeline.py"
  - "services/api-gateway/tests/evaluation/__init__.py"
  - "services/api-gateway/tests/evaluation/test_custom_evaluators.py"
  - "services/api-gateway/tests/evaluation/test_agent_evaluators.py"
  - "services/api-gateway/tests/evaluation/test_eval_pipeline.py"
  - "services/api-gateway/tests/evaluation/test_phase33_smoke.py"
  - "tests/eval/agent_traces_sample.jsonl"
  - ".github/workflows/agent-eval.yml"
task_count: 8
key_links: []
---

# Phase 33: Foundry Evaluation + Quality Gates — Implementation Plan

> **IMPORTANT**: This is a GSD wrapper plan. The full detailed implementation plan is at:
> `docs/superpowers/plans/2026-04-11-phase-33-evaluation.md`
>
> **Read that file first.** Execute all 5 chunks in order:
> 1. Chunk 1: Custom AIOps Evaluators
> 2. Chunk 2: Standard Agentic Evaluator Wrappers
> 3. Chunk 3: CI Eval Pipeline
> 4. Chunk 4: Sample Traces + GitHub Actions Workflow
> 5. Chunk 5: Final Verification

## Goal

Instrument every agent with `azure-ai-evaluation` agentic evaluators, build 4 custom AIOps evaluators, create a CI eval pipeline that gates on quality scores, and configure continuous evaluation rules in the Foundry portal.

## Architecture

A new `services/api-gateway/evaluation/` package holds all evaluator classes. `agent_evaluators.py` wraps the standard `azure-ai-evaluation` evaluators. Four custom evaluators (`SopAdherenceEvaluator`, `DiagnosisGroundingEvaluator`, `RemediationSafetyEvaluator`, `TriageCompletenessEvaluator`) extend the base pattern. A new GitHub Actions workflow (`.github/workflows/agent-eval.yml`) runs weekly + on PR to main.

**Tech Stack:** `azure-ai-evaluation` (agentic evaluators), `azure-ai-projects>=2.0.1`, `pytest`, GitHub Actions, Python

**Prerequisite:** Phase 29 (OTel traces in App Insights), Phase 30 (SOP metadata available).

## Tasks

### Chunk 1: Custom AIOps Evaluators
- Task 1: Write failing tests for custom evaluators
- Task 2: Create the evaluation package and custom evaluators

### Chunk 2: Standard Agentic Evaluator Wrappers
- Task 3: Write failing tests for standard evaluator wrappers
- Task 4: Implement `agent_evaluators.py`

### Chunk 3: CI Eval Pipeline
- Task 5: Write failing tests for eval pipeline script
- Task 6: Implement `eval_pipeline.py`

### Chunk 4: Sample Traces + GitHub Actions Workflow
- Task 7: Create sample trace data and eval workflow

### Chunk 5: Final Verification
- Task 8: Phase 33 smoke test

## Done Checklist

- [ ] `services/api-gateway/evaluation/` package created
- [ ] `custom_evaluators.py` with 4 AIOps evaluators
- [ ] `agent_evaluators.py` wrapping standard evaluators + safe score extraction
- [ ] `eval_pipeline.py` with 4 quality gates (TaskAdherence ≥4.0, TriageCompleteness ≥0.95, RemediationSafety ≥1.0, SopAdherence ≥3.5)
- [ ] `tests/eval/agent_traces_sample.jsonl` with 3 representative traces
- [ ] `.github/workflows/agent-eval.yml` weekly + on PR to main
- [ ] All evaluator tests pass
- [ ] Phase 33 smoke tests pass
