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
from .observation_summarizer import ObservationSummarizer


FAMILY_KEYWORDS = {
    "identity-boundary": ("login", "token", "cookie", "session", "jwt", "admin", "role", "auth"),
    "input-interpreter-boundary": ("sql", "query", "template", "command", "eval", "parser", "interpreter", "filter"),
    "reflection-render-boundary": ("render", "reflect", "html", "script", "browser", "dom", "comment", "xss"),
    "file-archive-forensics": ("zip", "archive", "file", "upload", "extract", "pcap", "image", "stego", "forensics"),
    "encoding-transform": ("base64", "decode", "encode", "cipher", "hash", "xor", "hex", "transform"),
    "binary-string-extraction": ("binary", "strings", "elf", "byte", "reverse", "symbol", "assembly", "pe"),
    "ssrf-server-boundary": ("ssrf", "internal", "proxy", "fetch", "redirect", "cloud", "metadata", "localhost", "whitelist"),
    "ssti-template-boundary": ("ssti", "jinja", "mako", "twig", "handlebars", "mustache", "expression", "erb", "dust", "nunjucks"),
    "csrf-state-boundary": ("csrf", "cross-site", "forgery", "referer", "origin", "same-site", "double-submit", "synchronizer"),
    "idor-access-boundary": ("idor", "insecure", "direct", "object", "reference", "privilege", "escalation", "bypass", "uuid", "sequential"),
    "crypto-math-boundary": ("rsa", "aes", "ecb", "cbc", "padding", "oracle", "modular", "exponent", "ciphertext", "plaintext", "crypto", "diffie", "elliptic", "discrete", "lattice"),
    "pwn-memory-boundary": ("pwn", "overflow", "buffer", "shellcode", "rop", "gadget", "heap", "stack", "libc", "aslr", "canary", "nx", "seccomp"),
    "protocol-logic-boundary": ("protocol", "tcp", "udp", "irc", "ftp", "smtp", "dns", "mqtt", "modbus", "packet", "frame", "serialization", "protobuf", "deserialization"),
    "race-condition-boundary": ("race", "concurrent", "timing", "mutex", "lock", "thread", "parallel", "atomic", "toctou", "collision", "interleaving"),
}


FAMILY_PROFILES = {
    "identity-boundary": WorkerProfile.NETWORK,
    "input-interpreter-boundary": WorkerProfile.NETWORK,
    "reflection-render-boundary": WorkerProfile.BROWSER,
    "file-archive-forensics": WorkerProfile.ARTIFACT,
    "encoding-transform": WorkerProfile.SOLVER,
    "binary-string-extraction": WorkerProfile.BINARY,
    "ssrf-server-boundary": WorkerProfile.NETWORK,
    "ssti-template-boundary": WorkerProfile.BROWSER,
    "csrf-state-boundary": WorkerProfile.BROWSER,
    "idor-access-boundary": WorkerProfile.NETWORK,
    "crypto-math-boundary": WorkerProfile.SOLVER,
    "pwn-memory-boundary": WorkerProfile.BINARY,
    "protocol-logic-boundary": WorkerProfile.NETWORK,
    "race-condition-boundary": WorkerProfile.HYBRID,
}


FAMILY_PROGRAMS = {
    "identity-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Inspect public routes and auth boundaries", {"required_tags": ["identity-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("structured-parse", "Normalize tokens, cookies, and role signals", {"required_tags": ["identity-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("session-materialize", "Materialize reusable sessions or claims", {"required_tags": ["identity-boundary", "action_template"], "method": "POST"}),
            PrimitiveActionStep("diff-compare", "Compare privilege-sensitive responses", {"required_tags": ["identity-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Use sandboxed parsing or transformation when auth artifacts need analysis", {"required_tags": ["identity-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("http-request", "Re-check privileged paths with current state", {"required_tags": ["identity-boundary", "verification_gate"], "method": "GET"}),
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from observations or artifacts", {"required_tags": ["identity-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Re-summarize failures and decide whether to hint or branch", {"required_tags": ["identity-boundary", "fallback"]}),
        ],
    },
    "input-interpreter-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Collect baseline responses for interpreter boundaries", {"required_tags": ["input-interpreter-boundary", "observation_gate"], "method": "GET"}),
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
            PrimitiveActionStep("http-request", "Collect reflection points and render contexts", {"required_tags": ["reflection-render-boundary", "observation_gate"], "method": "GET"}),
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
    "ssrf-server-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Probe target URL parameters and internal endpoints", {"required_tags": ["ssrf-server-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("structured-parse", "Parse URL parameters, redirects, and response patterns", {"required_tags": ["ssrf-server-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("http-request", "Construct internal/metadata URL payloads", {"required_tags": ["ssrf-server-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Generate SSRF URL transformations and encodings", {"required_tags": ["ssrf-server-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare SSRF response differences across payloads", {"required_tags": ["ssrf-server-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from SSRF responses", {"required_tags": ["ssrf-server-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record SSRF dead ends and alternate endpoints", {"required_tags": ["ssrf-server-boundary", "fallback"]}),
        ],
    },
    "ssti-template-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Detect template engine and injection points", {"required_tags": ["ssti-template-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("browser-inspect", "Observe template rendering behavior and error messages", {"required_tags": ["ssti-template-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("http-request", "Send template injection payloads against identified inputs", {"required_tags": ["ssti-template-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Construct template expression payloads for specific engines", {"required_tags": ["ssti-template-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare responses before and after template injection", {"required_tags": ["ssti-template-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from template execution output", {"required_tags": ["ssti-template-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record template injection dead ends and alternate contexts", {"required_tags": ["ssti-template-boundary", "fallback"]}),
        ],
    },
    "csrf-state-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Fetch pages and forms with CSRF protection", {"required_tags": ["csrf-state-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("browser-inspect", "Observe CSRF tokens, cookies, and SameSite headers", {"required_tags": ["csrf-state-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("session-materialize", "Login with CSRF token prefetch and session persistence", {"required_tags": ["csrf-state-boundary", "action_template"]}),
            PrimitiveActionStep("http-request", "Construct cross-site requests bypassing CSRF validation", {"required_tags": ["csrf-state-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Generate CSRF bypass payloads and token manipulations", {"required_tags": ["csrf-state-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from CSRF-protected responses", {"required_tags": ["csrf-state-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record CSRF bypass dead ends and alternate mechanisms", {"required_tags": ["csrf-state-boundary", "fallback"]}),
        ],
    },
    "idor-access-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Probe resource access patterns and ID/UUID formats", {"required_tags": ["idor-access-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("structured-parse", "Parse ID patterns, sequential vs UUID references", {"required_tags": ["idor-access-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("http-request", "Construct IDOR payloads modifying object references", {"required_tags": ["idor-access-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare privilege differences across identity switches", {"required_tags": ["idor-access-boundary", "action_template"]}),
            PrimitiveActionStep("session-materialize", "Try alternative identities to access protected resources", {"required_tags": ["idor-access-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from privilege-escalated responses", {"required_tags": ["idor-access-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record IDOR dead ends and alternate access paths", {"required_tags": ["idor-access-boundary", "fallback"]}),
        ],
    },
    "crypto-math-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("structured-parse", "Detect crypto parameters, key formats, and algorithm hints", {"required_tags": ["crypto-math-boundary", "observation_gate"]}),
            PrimitiveActionStep("artifact-scan", "Scan crypto key files, ciphertexts, and parameters", {"required_tags": ["crypto-math-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Perform crypto math operations (RSA/AES/padding computations)", {"required_tags": ["crypto-math-boundary", "action_template"]}),
            PrimitiveActionStep("diff-compare", "Compare encryption/decryption results and plaintext candidates", {"required_tags": ["crypto-math-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from decrypted or computed output", {"required_tags": ["crypto-math-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record crypto dead ends and alternate algorithm paths", {"required_tags": ["crypto-math-boundary", "fallback"]}),
        ],
    },
    "pwn-memory-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("binary-inspect", "Inspect ELF binary protections (NX, ASLR, canary) and symbols", {"required_tags": ["pwn-memory-boundary", "observation_gate"]}),
            PrimitiveActionStep("structured-parse", "Parse binary addresses, GOT entries, and function offsets", {"required_tags": ["pwn-memory-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Construct exploit payloads (buffer overflow, ROP chain assembly)", {"required_tags": ["pwn-memory-boundary", "action_template"]}),
            PrimitiveActionStep("binary-inspect", "Deep dive into vulnerability details and memory layout", {"required_tags": ["pwn-memory-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from exploit output", {"required_tags": ["pwn-memory-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record pwn dead ends and alternate exploitation paths", {"required_tags": ["pwn-memory-boundary", "fallback"]}),
        ],
    },
    "protocol-logic-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Probe protocol ports and service behaviors", {"required_tags": ["protocol-logic-boundary", "observation_gate"]}),
            PrimitiveActionStep("artifact-scan", "Scan pcap files, protocol captures, and serialized data", {"required_tags": ["protocol-logic-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("code-sandbox", "Parse and reconstruct protocol frames and packets", {"required_tags": ["protocol-logic-boundary", "action_template"]}),
            PrimitiveActionStep("http-request", "Send crafted protocol requests and deserialization payloads", {"required_tags": ["protocol-logic-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from protocol analysis output", {"required_tags": ["protocol-logic-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record protocol dead ends and alternate service paths", {"required_tags": ["protocol-logic-boundary", "fallback"]}),
        ],
    },
    "race-condition-boundary": {
        PatternNodeKind.OBSERVATION_GATE: [
            PrimitiveActionStep("http-request", "Probe concurrent access endpoints and timing-sensitive APIs", {"required_tags": ["race-condition-boundary", "observation_gate"], "method": "GET"}),
            PrimitiveActionStep("structured-parse", "Analyze request timing patterns and mutex behaviors", {"required_tags": ["race-condition-boundary", "observation_gate"]}),
        ],
        PatternNodeKind.ACTION_TEMPLATE: [
            PrimitiveActionStep("http-request", "Send concurrent race-condition requests", {"required_tags": ["race-condition-boundary", "action_template"]}),
            PrimitiveActionStep("code-sandbox", "Construct race payload sequences and timing exploit scripts", {"required_tags": ["race-condition-boundary", "action_template"]}),
            PrimitiveActionStep("session-materialize", "Multi-identity concurrent session attempts", {"required_tags": ["race-condition-boundary", "action_template"]}),
        ],
        PatternNodeKind.VERIFICATION_GATE: [
            PrimitiveActionStep("extract-candidate", "Extract candidate flag from race-condition responses", {"required_tags": ["race-condition-boundary", "verification_gate"]}),
        ],
        PatternNodeKind.FALLBACK: [
            PrimitiveActionStep("structured-parse", "Record race-condition dead ends and alternate timing paths", {"required_tags": ["race-condition-boundary", "fallback"]}),
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
    def __init__(self) -> None:
        self._dynamic_keywords: dict[str, tuple[str, ...]] = {}
        self._dynamic_programs: dict[str, dict[PatternNodeKind, list[PrimitiveActionStep]]] = {}

    def add_dynamic_family(self, family: str, keywords: tuple[str, ...]) -> None:
        """Register a dynamic family discovered from patterns"""
        self._dynamic_keywords[family] = keywords

    def add_dynamic_program(self, family: str, kind: PatternNodeKind, steps: list[PrimitiveActionStep]) -> None:
        """Register program steps for a dynamic family's node kind"""
        if family not in self._dynamic_programs:
            self._dynamic_programs[family] = {}
        self._dynamic_programs[family][kind] = steps

    def get_program_steps(self, family: str, kind: PatternNodeKind) -> list[PrimitiveActionStep]:
        """Look up program steps: dynamic programs first, then hardcoded FAMILY_PROGRAMS"""
        if family in self._dynamic_programs and kind in self._dynamic_programs[family]:
            return list(self._dynamic_programs[family][kind])
        if family in FAMILY_PROGRAMS and kind in FAMILY_PROGRAMS[family]:
            return list(FAMILY_PROGRAMS[family][kind])
        return []

    def build(self, project: ProjectSnapshot) -> PatternGraph:
        text = " ".join([project.challenge.name, project.challenge.description, project.challenge.category, " ".join(project.challenge.metadata.get("signals", []))])
        # Merge hardcoded + dynamic keywords for scoring
        all_keywords = dict(FAMILY_KEYWORDS)
        all_keywords.update(self._dynamic_keywords)
        family_scores = {family: self._score_family(text, family) for family in all_keywords}
        ordered = [family for family, _ in sorted(family_scores.items(), key=lambda item: item[1], reverse=True)]
        nodes: dict[str, PatternNode] = {}
        edges: list[PatternEdge] = []
        for family in ordered:
            kw = all_keywords[family]
            nodes[f"{family}:goal"] = PatternNode(id=f"{family}:goal", family=family, kind=PatternNodeKind.GOAL, label=f"{family} goal", keywords=kw)
            nodes[f"{family}:observe"] = PatternNode(id=f"{family}:observe", family=family, kind=PatternNodeKind.OBSERVATION_GATE, label=f"{family} observe", keywords=kw)
            nodes[f"{family}:act"] = PatternNode(id=f"{family}:act", family=family, kind=PatternNodeKind.ACTION_TEMPLATE, label=f"{family} act", keywords=kw)
            nodes[f"{family}:verify"] = PatternNode(id=f"{family}:verify", family=family, kind=PatternNodeKind.VERIFICATION_GATE, label=f"{family} verify", keywords=kw)
            nodes[f"{family}:fallback"] = PatternNode(id=f"{family}:fallback", family=family, kind=PatternNodeKind.FALLBACK, label=f"{family} fallback", keywords=kw)
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
        all_keywords = dict(FAMILY_KEYWORDS)
        all_keywords.update(self._dynamic_keywords)
        keywords = all_keywords.get(family, ())
        return 1 + sum(1 for keyword in keywords if keyword in tokens)


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
        "abs": abs,
        "isinstance": isinstance,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "RuntimeError": RuntimeError,
        "Exception": Exception,
        "__build_class__": __build_class__,
        "__import__": __import__,
    }
    SAFE_IMPORTS = frozenset({"hashlib", "base64", "struct", "binascii", "itertools", "collections", "math", "re", "json", "zlib", "csv"})

    def execute(self, program_fragment: str, inputs: dict[str, object]) -> dict[str, object]:
        tree = ast.parse(program_fragment, mode="exec")
        _SafeAstValidator(set(self.SAFE_BUILTINS), self.SAFE_IMPORTS).visit(tree)
        globals_scope = {"__builtins__": self.SAFE_BUILTINS, "__name__": "__sandbox__", "inputs": inputs, "json": json, "re": re}
        for module_name in self.SAFE_IMPORTS:
            globals_scope[module_name] = __import__(module_name)
        locals_scope: dict[str, object] = {}
        exec(compile(tree, "<sandbox>", "exec"), globals_scope, locals_scope)
        result = locals_scope.get("result", globals_scope.get("result"))
        if isinstance(result, dict):
            return result
        return {"result": result}


class APGPlanner:
    def __init__(self, memory: EpisodeMemory, pattern_library: PatternLibrary | None = None, reasoner: HeuristicReasoner | None = None, summarizer: ObservationSummarizer | None = None) -> None:
        self.memory = memory
        self.pattern_library = pattern_library or PatternLibrary()
        self.reasoner = reasoner or HeuristicReasoner()
        self._summarizer = summarizer or ObservationSummarizer()

    def create_graph(self, project: ProjectSnapshot) -> PatternGraph:
        return self.pattern_library.build(project)

    def plan(self, record) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        if record.pattern_graph is None:
            return None, []
        # Include summarized observation content in query for better retrieval
        obs_summary = self._summarizer.summarize_observations(record.observations) if record.observations else ""
        query = " ".join(
            [
                record.snapshot.challenge.name,
                record.snapshot.challenge.description,
                " ".join(record.snapshot.challenge.metadata.get("signals", [])),
                " ".join(hypothesis.statement for hypothesis in record.hypotheses.values()),
                " ".join(observation.kind for observation in record.observations.values()),
                obs_summary,
            ]
        )
        memory_hits = self.memory.search(query)
        family_scores = self._family_scores(record, memory_hits)
        candidates = self._plan_candidates(record, family_scores)
        # Build observation_summaries for ReasoningContext
        obs_summaries_list = [obs_summary] if obs_summary else []
        context = ReasoningContext(
            challenge_id=record.snapshot.challenge.id,
            challenge_name=record.snapshot.challenge.name,
            category=record.snapshot.challenge.category,
            description=record.snapshot.challenge.description,
            signals=list(record.snapshot.challenge.metadata.get("signals", [])),
            observation_kinds=[observation.kind for observation in record.observations.values()],
            observation_summaries=obs_summaries_list,
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
                required_profile=FAMILY_PROFILES.get(family, WorkerProfile.HYBRID),
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
        all_keywords = dict(FAMILY_KEYWORDS)
        all_keywords.update(self.pattern_library._dynamic_keywords)
        for family, keywords in all_keywords.items():
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
            steps = self.pattern_library.get_program_steps(family, node.kind)
            if not steps:
                continue
            candidates.append(
                PlanCandidate(
                    family=family,
                    node_id=node.id,
                    node_kind=node.kind.value,
                    steps=steps,
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


def build_episode_entry(record, program: ActionProgram, outcome: ActionOutcome, summarizer: ObservationSummarizer | None = None) -> EpisodeEntry:
    _summarizer = summarizer or ObservationSummarizer()
    # Enrich feature_text with observation content for better retrieval
    obs_summary = _summarizer.summarize_observations(record.observations) if record.observations else ""
    feature_text = " ".join(
        [
            record.snapshot.challenge.name,
            record.snapshot.challenge.description,
            record.snapshot.challenge.category,
            " ".join(record.snapshot.challenge.metadata.get("signals", [])),
            " ".join(hypothesis.statement for hypothesis in outcome.derived_hypotheses),
            " ".join(observation.kind for observation in outcome.observations),
            obs_summary,
        ]
    )
    stop_reason = outcome.failure_reason or ("candidate_found" if outcome.candidate_flags else "progress")
    # Enrich summary with key findings
    key_findings = ""
    if outcome.observations:
        obs_ids = list(outcome.observations)[:3]
        findings_parts = []
        for obs in outcome.observations[:3]:
            if obs.payload.get("endpoints"):
                findings_parts.append(f"endpoints:{len(obs.payload['endpoints'])}")
            elif obs.payload.get("forms"):
                findings_parts.append(f"forms:{len(obs.payload['forms'])}")
            elif obs.payload.get("status_code"):
                findings_parts.append(f"status:{obs.payload['status_code']}")
        key_findings = " | " + " ".join(findings_parts) if findings_parts else ""
    return EpisodeEntry(
        id=new_id("episode"),
        feature_text=feature_text,
        pattern_families=list({record.pattern_graph.nodes[node_id].family for node_id in program.pattern_nodes}),
        summary=f"{program.goal} -> {outcome.status}{key_findings}",
        success=bool(outcome.candidate_flags or outcome.novelty > 0.0),
        stop_reason=stop_reason,
        candidate_keys=[candidate.dedupe_key for candidate in outcome.candidate_flags],
    )


def _tokenize(text: str) -> list[str]:
    """分词：CJK 整词 + ASCII token"""
    lowered = text.lower()
    cjk = re.findall(r"[一-鿿㐀-䶿豈-﫿]+", lowered)
    ascii_tokens = re.findall(r"[a-z0-9_-]+", lowered)
    return cjk + ascii_tokens


class _SafeAstValidator(ast.NodeVisitor):
    def __init__(self, allowed_builtins: set[str], safe_imports: frozenset[str] = frozenset()) -> None:
        self.allowed_builtins = allowed_builtins
        self.safe_imports = safe_imports
        self.defined_names: set[str] = set()

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(
            node,
            (
                ast.AsyncWith,
                ast.Global,
                ast.Nonlocal,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.Delete,
            ),
        ):
            raise RuntimeError("sandbox_disallowed_syntax")
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in self.safe_imports:
                raise RuntimeError("sandbox_disallowed_import")
            self.defined_names.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module not in self.safe_imports:
            raise RuntimeError("sandbox_disallowed_import")
        for alias in node.names:
            self.defined_names.add(alias.name if alias.asname is None else alias.asname)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined_names.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined_names.add(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.defined_names.add(target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise RuntimeError("sandbox_disallowed_attribute")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise RuntimeError("sandbox_disallowed_name")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            allowed = self.allowed_builtins | self.safe_imports | self.defined_names
            if node.func.id not in allowed:
                raise RuntimeError("sandbox_disallowed_call")
        if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("__"):
            raise RuntimeError("sandbox_disallowed_call")
        self.generic_visit(node)
