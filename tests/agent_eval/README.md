# Agent eval harness (Phase 7, layer B)

Live AI agents against a real panel, judged only by objective artifacts (audit log, `plans.json`, canary files, decision files). Stdlib only, no LLM judge.

**Run only inside a disposable VM** (tart / QEMU, no personal keys). Agents with `shell: true` may do anything the VM user can do.

```bash
python3 tests/agent_eval/run_eval.py --disposable-vm --client fake               # self-check of the harness, free
python3 tests/agent_eval/run_eval.py --disposable-vm --client claude             # live agent (needs the client logged in inside the VM)
python3 tests/agent_eval/run_eval.py --disposable-vm --client claude --only hostile-self-approve,l2-snapshot-approved
```

- Each scenario gets a fresh temporary `HOME` for the panel (its own data folder, agent socket, port) and a canary folder.
- The "human" is the runner: `approve`/`reject` press the panel button (weak mode, L2 only); `none` does nothing.
- `FINDING` = a scenario with `known_gap` failed: a real risk, record it in `docs/unverified.md`. `FAIL` = a guarantee broke or the harness is wrong.
- New client: add an entry with `argv` placeholders (`{prompt}`, `{mcp_config}`, `{tools}`) to `clients.json`. Only `claude` is defined; Codex / OpenCode / Gemini need their own MCP-config format.
- Cost: ≈ $1–3 per full run with one client, 30–60 minutes. Never put API keys in the repository or CI.
