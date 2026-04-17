# tests/eval

Agent evaluation tests that replay sampled agent traces to validate reasoning quality, tool call correctness, and response accuracy. Used to detect regressions in agent behavior across framework or prompt changes.

## Contents

- `agent_traces_sample.jsonl` — sampled agent trace records (inputs, tool calls, outputs) used as eval fixtures

Eval tests load traces from the `.jsonl` file and assert that agent outputs meet defined quality criteria (correct domain routing, expected tool calls, no hallucinated resource IDs, etc.).
