from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict
from pathlib import Path

from .models import new_id
from .platform_models import (
    ActionProgram,
    ActionOutcome,
    EpisodeEntry,
    Hypothesis,
    PatternEdge,
    PatternGraph,
    PatternNode,
    PatternNodeKind,
    PrimitiveActionStep,
    ProjectSnapshot,
    RetrievalHit,
    WorkerProfile,
)
from .reasoning import HeuristicReasoner, PlanCandidate, ReasoningContext


FAMILY_KEYWORDS = {
    "identity-boundary": ("login", "token", "cookie", "session", "jwt", "admin", "role", "auth"),
    "input-interpreter-boundary": ("sql", "query", "template", "command", "eval", "parser", "interpreter", "filter"),
    "reflection-render-boundary": ("render", "reflect", "html", "script", "browser", "dom", "comment", "xss"),
    "file-archive-forensics": ("zip", "archive", "file", "upload", "extract", "pcap", "image", "stego", "forensics"),
    "encoding-transform": ("base64", "decode", "encode", "cipher", "hash", "xor", "hex", "transform"),
    "binary-string-extraction": ("binary", "strings", "elf", "byte", "reverse", "symbol", "assembly", "pe"),
}


FAMILY_PROFILES = {
    "identity-boundary": WorkerProfile.NETWORK,
    "input-interpreter-boundary": WorkerProfile.NETWORK,
    "reflection-render-boundary": WorkerProfile.BROWSER,
    "file-archive-forensics": WorkerProfile.ARTIFACT,
    "encoding-transform": WorkerProfile.SOLVER,
    "binary-string-extraction": WorkerProfile.BINARY,
}


FAMILY_PROGRAMS = {
    "identity-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Inspect public routes and auth boundaries", {"required_tags": ["identity-boundary", "observation_gate"]}),
            PrimitiveActionStep("structured-parse", "Normalize tokens, cookies, and role signals", {"required_tags": ["identity-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("session-materialize", "Materialize reusable sessions or claims", {"required_tags": ["identity-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare privilege-sensitive responses", {"required_tags": ["identity-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Use sandboxed parsing or transformation when auth artifacts need analysis", {"required_tags": ["identity-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("http-request", "Re-check privileged paths with current state", {"required_tags": ["identity-boundary", "verification_gate"]}),
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from observations or artifacts", {"required_tags": ["identity-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Re-summarize failures and decide whether to hint or branch", {"required_tags": ["identity-boundary", "fallback"]}),
        ],
    },
    "input-interpreter-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Collect baseline responses for interpreter boundaries", {"required_tags": ["input-interpreter-boundary", "observation_gate"]}),
            PrimitiveActionStep("diff-compare", "Measure response differences across crafted variants", {"required_tags": ["input-interpreter-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Generate or simplify safe probe transformations", {"required_tags": ["input-interpreter-boundary", "action_template"]}),
            PrimitiveActionStep("http-request", "Replay focused probes against promising inputs", {"required_tags": ["input-interpreter-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate secrets or flags from responses", {"required_tags": ["input-interpreter-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record dead ends and branch to adjacent patterns", {"required_tags": ["input-interpreter-boundary", "fallback"]}),
        ],
    },
    "reflection-render-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Collect reflection points and render contexts", {"required_tags": ["reflection-render-boundary", "observation_gate"]}),
            PrimitiveActionStep("browser-inspect", "Observe browser-side rendering and hidden content", {"required_tags": ["reflection-render-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("browser-inspect", "Exercise render paths and stateful views", {"required_tags": ["reflection-render-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare reflected or rendered variants", {"required_tags": ["reflection-render-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Transform reflected artifacts into comparable forms", {"required_tags": ["reflection-render-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from rendered text or comments", {"required_tags": ["reflection-render-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Summarize render-side failures and alternate contexts", {"required_tags": ["reflection-render-boundary", "fallback"]}),
        ],
    },
    "file-archive-forensics": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("artifact-scan", "Enumerate available files and archive containers", {"required_tags": ["file-archive-forensics", "observation_gate"]}),
            PrimitiveActionStep("structured-parse", "Parse file metadata and structure", {"required_tags": ["file-archive-forensics", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("artifact-scan", "Expand or inspect promising file artifacts", {"required_tags": ["file-archive-forensics", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Transform extracted content using sandboxed helpers", {"required_tags": ["file-archive-forensics", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from artifact content", {"required_tags": ["file-archive-forensics", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Capture artifact dead ends for future retrieval", {"required_tags": ["file-archive-forensics", "fallback"]}),
        ],
    },
    "encoding-transform": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("structured-parse", "Detect transform, encoding, or cipher hints", {"required_tags": ["encoding-transform", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Run sandboxed decode or transform helpers", {"required_tags": ["encoding-transform", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare decoded forms and consistency signals", {"required_tags": ["encoding-transform", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from transformed output", {"required_tags": ["encoding-transform", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Persist transform dead ends for retrieval", {"required_tags": ["encoding-transform", "fallback"]}),
        ],
    },
    "binary-string-extraction": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("binary-inspect", "Inspect binary strings, symbols, and metadata", {"required_tags": ["binary-string-extraction", "observation_gate"]}),
            PrimitiveActionStep("structured-parse", "Normalize extracted binary signals", {"required_tags": ["binary-string-extraction", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Run sandboxed extraction or transformation helpers", {"required_tags": ["binary-string-extraction", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare extracted candidates and control signals", {"required_tags": ["binary-string-extraction", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from binary-derived content", {"required_tags": ["binary-string-extraction", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record binary dead ends and alternate strings", {"required_tags": ["binary-string-extraction", "fallback"]}),
        ],
    },
}


class EpisodeMemory:
    def __init__(self, store_path: str | Path | None = None) -> None:
        self.store_path = Path(store_path) if store_path is not None else None
        self.entries: list[EpisodeEntry] = []
        if self.store_path is not None:
            self._load()

    def add(self, entry: EpisodeEntry) -> None:
        self.entries.append(entry)
        if self.store_path is not None:
            self._save()

    def search(self, query: str, limit: int = 3) -> list[RetrievalHit]:
        query_tokens = set(_tokenize(query))
        hits: list[RetrievalHit] = []
        for entry in self.entries:
            entry_tokens = set(_tokenize(entry.feature_text))
            if not entry_tokens:
                continue
            overlap = query_tokens & entry_tokens
            if not overlap:
                continue
            overlap_count = len(overlap)
            precision = overlap_count / max(len(entry_tokens), 1)
            recall = overlap_count / max(len(query_tokens), 1)
            score = overlap_count + recall + (precision / 1000.0)
            hits.append(
                RetrievalHit(
                    episode_id=entry.id,
                    score=score,
                    summary=entry.summary,
                    pattern_families=list(entry.pattern_families),
                    stop_reason=entry.stop_reason,
                )
                )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def _load(self) -> None:
        assert self.store_path is not None
        if not self.store_path.exists():
            self.entries = []
            return
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            self.entries = []
            return
        self.entries = [EpisodeEntry(**item) for item in payload if isinstance(item, dict)]

    def _save(self) -> None:
        assert self.store_path is not None
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(entry) for entry in self.entries]
        self.store_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


class PatternLibrary:
    def build(self, project: ProjectSnapshot) -> PatternGraph:
        text = " ".join([project.challenge.name, project.challenge.description, project.challenge.category, " ".join(project.challenge.metadata.get("signals", []))])
        family_scores = {family: self._score_family(text, family) for family in FAMILY_KEYWORDS}
        ordered = [family for family, _ in sorted(family_scores.items(), key=lambda item: item[1], reverse=True)]
        nodes: dict[str, PatternNode] = {}
        edges: list[PatternEdge] = []
        for family in ordered:
            nodes[f"{family}:goal"] = PatternNode(id=f"{family}:goal", family=family, kind=PatternNodeKind.GOAL, label=f"{family} goal", keywords=FAMILY_KEYWORDS[family])
            nodes[f"{family}:observe"] = PatternNode(id=f"{family}:observe", family=family, kind=PatternNodeKind.OBSERVATION_GATE, label=f"{family} observe", keywords=FAMILY_KEYWORDS[family])
            nodes[f"{family}:act"] = PatternNode(id=f"{family}:act", family=family, kind=PatternNodeKind.ACTION_TEMPLATE, label=f"{family} act", keywords=FAMILY_KEYWORDS[family])
            nodes[f"{family}:verify"] = PatternNode(id=f"{family}:verify", family=family, kind=PatternNodeKind.VERIFICATION_GATE, label=f"{family} verify", keywords=FAMILY_KEYWORDS[family])
            nodes[f"{family}:fallback"] = PatternNode(id=f"{family}:fallback", family=family, kind=PatternNodeKind.FALLBACK, label=f"{family} fallback", keywords=FAMILY_KEYWORDS[family])
            edges.extend(
                [
                    PatternEdge(source=f"{family}:goal", target=f"{family}:observe", condition="start"),
                    PatternEdge(source=f"{family}:observe", target=f"{family}:act", condition="observation_ready"),
                    PatternEdge(source=f"{family}:act", target=f"{family}:verify", condition="action_complete"),
                    PatternEdge(source=f"{family}:verify", target=f"{family}:goal", condition="need_more_work"),
                    PatternEdge(source=f"{family}:verify", target=f"{family}:fallback", condition="verification_failed"),
                ]
            )
        return PatternGraph(graph_id=new_id("pattern_graph"), nodes=nodes, edges=edges, family_priority=ordered, active_family=ordered[0] if ordered else None)

    def _score_family(self, text: str, family: str) -> int:
        tokens = _tokenize(text)
        return 1 + sum(1 for keyword in FAMILY_KEYWORDS[family] if keyword in tokens)


class CodeSandbox:
    SAFE_BUILTINS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "dict": dict,
        "list": list,
        "set": set,
        "tuple": tuple,
        "sorted": sorted,
        "sum": sum,
        "min": min,
        "max": max,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "any": any,
        "all": all,
    }

    def execute(self, program_fragment: str, inputs: dict[str, object]) -> dict[str, object]:
        tree = ast.parse(program_fragment, mode="exec")
        _SafeAstValidator(set(self.SAFE_BUILTINS)).visit(tree)
        globals_scope = {"__builtins__": self.SAFE_BUILTINS, "inputs": inputs, "json": json, "re": re}
        locals_scope: dict[str, object] = {}
        exec(compile(tree, "<sandbox>", "exec"), globals_scope, locals_scope)
        result = locals_scope.get("result", globals_scope.get("result"))
        if isinstance(result, dict):
            return result
        return {"result": result}


class APGPlanner:
    def __init__(self, memory: EpisodeMemory, pattern_library: PatternLibrary | None = None, reasoner: HeuristicReasoner | None = None) -> None:
        self.memory = memory
        self.pattern_library = pattern_library or PatternLibrary()
        self.reasoner = reasoner or HeuristicReasoner()

    def create_graph(self, project: ProjectSnapshot) -> PatternGraph:
        return self.pattern_library.build(project)

    def plan(self, record) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        if record.pattern_graph is None:
            return None, []
        query = " ".join(
            [
                record.snapshot.challenge.name,
                record.snapshot.challenge.description,
                " ".join(record.snapshot.challenge.metadata.get("signals", [])),
                " ".join(hypothesis.statement for hypothesis in record.hypotheses.values()),
                " ".join(observation.kind for observation in record.observations.values()),
            ]
        )
        memory_hits = self.memory.search(query)
        family_scores = self._family_scores(record, memory_hits)
        candidates = self._plan_candidates(record, family_scores)
        context = ReasoningContext(
            challenge_id=record.snapshot.challenge.id,
            challenge_name=record.snapshot.challenge.name,
            category=record.snapshot.challenge.category,
            description=record.snapshot.challenge.description,
            signals=list(record.snapshot.challenge.metadata.get("signals", [])),
            observation_kinds=[observation.kind for observation in record.observations.values()],
            hypothesis_statements=[hypothesis.statement for hypothesis in record.hypotheses.values()],
            artifact_kinds=[artifact.kind for artifact in record.artifacts.values()],
            memory_summaries=[hit.summary for hit in memory_hits],
            family_scores=family_scores,
            candidates=candidates,
        )
        decision = self.reasoner.choose_program(context)
        if decision is None:
            return None, memory_hits
        family = decision.family
        node = record.pattern_graph.nodes.get(decision.node_id)
        if node is None:
            return None, memory_hits
        record.pattern_graph.active_family = family
        steps = list(decision.steps)
        return (
            ActionProgram(
                id=new_id("program"),
                goal=node.label,
                pattern_nodes=[node.id],
                steps=steps,
                allowed_primitives=list(dict.fromkeys(step.primitive for step in steps)),
                verification_rules=["flag_pattern", "novelty_positive"],
                required_profile=FAMILY_PROFILES[family],
                memory_refs=[hit.episode_id for hit in memory_hits],
                rationale=decision.rationale,
                planner_source=decision.source,
            ),
            memory_hits,
        )

    def update_graph(self, record, program: ActionProgram, outcome: ActionOutcome) -> None:
        for node_id in program.pattern_nodes:
            node = record.pattern_graph.nodes[node_id]
            if outcome.status == "ok" and (outcome.novelty > 0.0 or outcome.candidate_flags):
                node.status = "resolved"
            else:
                node.status = "failed"
                fallback_id = f"{node.family}:fallback"
                if fallback_id in record.pattern_graph.nodes and record.pattern_graph.nodes[fallback_id].status == "pending":
                    record.pattern_graph.nodes[fallback_id].status = "active"

    def _family_scores(self, record, memory_hits: list[RetrievalHit]) -> dict[str, float]:
        scores = {family: 0.0 for family in record.pattern_graph.family_priority}
        text = " ".join(
            [
                record.snapshot.challenge.name,
                record.snapshot.challenge.description,
                " ".join(record.snapshot.challenge.metadata.get("signals", [])),
                " ".join(observation.kind for observation in record.observations.values()),
                " ".join(hypothesis.statement for hypothesis in record.hypotheses.values()),
            ]
        )
        tokens = set(_tokenize(text))
        for family, keywords in FAMILY_KEYWORDS.items():
            scores[family] += sum(1.0 for keyword in keywords if keyword in tokens)
        for hit in memory_hits:
            for family in hit.pattern_families:
                if family in scores:
                    scores[family] += hit.score * (1.5 if "abandoned" not in hit.stop_reason else 0.4)
        for family in list(scores):
            if self._next_node(record.pattern_graph, family) is None:
                scores[family] = -1.0
        return scores

    def _plan_candidates(self, record, family_scores: dict[str, float]) -> list[PlanCandidate]:
        candidates: list[PlanCandidate] = []
        for family, score in family_scores.items():
            if score < 0:
                continue
            node = self._next_node(record.pattern_graph, family)
            if node is None:
                continue
            candidates.append(
                PlanCandidate(
                    family=family,
                    node_id=node.id,
                    node_kind=node.kind.value,
                    steps=list(FAMILY_PROGRAMS[family][node.kind]),
                    score=score,
                )
            )
        return candidates

    def _next_node(self, graph: PatternGraph, family: str) -> PatternNode | None:
        for suffix in ("observe", "act", "verify", "fallback"):
            node = graph.nodes.get(f"{family}:{suffix}")
            if node is not None and node.status in {"pending", "active"}:
                return node
        return None


def build_episode_entry(record, program: ActionProgram, outcome: ActionOutcome) -> EpisodeEntry:
    feature_text = " ".join(
        [
            record.snapshot.challenge.name,
            record.snapshot.challenge.description,
            record.snapshot.challenge.category,
            " ".join(record.snapshot.challenge.metadata.get("signals", [])),
            " ".join(hypothesis.statement for hypothesis in outcome.derived_hypotheses),
            " ".join(observation.kind for observation in outcome.observations),
        ]
    )
    stop_reason = outcome.failure_reason or ("candidate_found" if outcome.candidate_flags else "progress")
    return EpisodeEntry(
        id=new_id("episode"),
        feature_text=feature_text,
        pattern_families=list({record.pattern_graph.nodes[node_id].family for node_id in program.pattern_nodes}),
        summary=f"{program.goal} -> {outcome.status}",
        success=bool(outcome.candidate_flags or outcome.novelty > 0.0),
        stop_reason=stop_reason,
        candidate_keys=[candidate.dedupe_key for candidate in outcome.candidate_flags],
    )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_-]+", text.lower())


class _SafeAstValidator(ast.NodeVisitor):
    def __init__(self, allowed_builtins: set[str]) -> None:
        self.allowed_builtins = allowed_builtins

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.With,
                ast.AsyncWith,
                ast.Try,
                ast.Raise,
                ast.Global,
                ast.Nonlocal,
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.Delete,
            ),
        ):
            raise RuntimeError("sandbox_disallowed_syntax")
        super().generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise RuntimeError("sandbox_disallowed_attribute")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise RuntimeError("sandbox_disallowed_name")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id not in self.allowed_builtins:
            raise RuntimeError("sandbox_disallowed_call")
        if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("__"):
            raise RuntimeError("sandbox_disallowed_call")
        self.generic_visit(node)
