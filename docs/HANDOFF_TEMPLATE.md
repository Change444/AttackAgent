# Handoff Template

Use this as the first message in the next conversation.

## Minimal Resume Prompt

```text
Project: AttackAgent
Repo: E:\AI相关\ai安全\AttackAgent

Long-term context:
- Build a legally authorized CTF competition platform.
- Current architecture: Controller + Dispatcher + StateGraph + APGPlanner + Primitive Runtime.
- Solving core is generalized through primitive actions, pattern graphs, retrieval memory, and a restricted code sandbox.

Mid-term context:
- Provider, controller, dispatcher, state graph, APG, runtime, strategy, platform, console, demo, and tests are already present.
- Current baseline: python -m unittest discover -s tests -v => 27/27 OK.
- Current limitation: primitives are still mainly metadata-driven and not fully connected to real local targets.
- Real EpisodeMemory persistence and PatternGraph visualization are still missing.

Short-term goal:
- [WRITE ONLY ONE GOAL HERE]

Acceptance criteria:
- [WRITE ONLY ONE CLEAR ACCEPTANCE CHECK HERE]
```

## Good Example

```text
Project: AttackAgent
Repo: E:\AI相关\ai安全\AttackAgent

Long-term context:
- Build a legally authorized CTF competition platform.
- Current architecture: Controller + Dispatcher + StateGraph + APGPlanner + Primitive Runtime.
- Solving core is generalized through primitive actions, pattern graphs, retrieval memory, and a restricted code sandbox.

Mid-term context:
- Provider, controller, dispatcher, state graph, APG, runtime, strategy, platform, console, demo, and tests are already present.
- Current baseline: python -m unittest discover -s tests -v => 27/27 OK.
- Current limitation: primitives are still mainly metadata-driven and not fully connected to real local targets.
- Real EpisodeMemory persistence and PatternGraph visualization are still missing.

Short-term goal:
- Replace the metadata-driven http-request primitive with a real requests/httpx-backed local-range adapter.

Acceptance criteria:
- Add an integration-style test that performs real recon plus extract-candidate against a local or stubbed web target without regressing the current baseline.
```

## Resume Checklist

Before starting new implementation in a new conversation:

1. Read [CURRENT_STATE.md](CURRENT_STATE.md).
2. Open [ARCHITECTURE.md](ARCHITECTURE.md).
3. Pick only one item from [NEXT_STEPS.md](NEXT_STEPS.md).
4. Run:

```powershell
python -m unittest discover -s tests -v
python -m attack_agent.platform_demo
```
