from __future__ import annotations

import unittest

from attack_agent.platform_models import ChallengeDefinition, Event, EventType, ProjectSnapshot
from attack_agent.state_graph import StateGraphService


class StateGraphTests(unittest.TestCase):
    def test_candidate_flag_is_deduped_by_key(self) -> None:
        state = StateGraphService()
        project = ProjectSnapshot(
            project_id="project:web-1",
            challenge=ChallengeDefinition(id="web-1", name="x", category="web", difficulty="easy", target="http://demo"),
        )
        state.upsert_project(project)
        state.append_event(
            Event(
                type=EventType.CANDIDATE_FLAG,
                project_id=project.project_id,
                run_id="run1",
                payload={"value": "flag{a}", "source_chain": ["x"], "confidence": 0.8, "format_match": True, "dedupe_key": "same", "evidence_refs": [], "submitted": False},
            )
        )
        state.append_event(
            Event(
                type=EventType.CANDIDATE_FLAG,
                project_id=project.project_id,
                run_id="run2",
                payload={"value": "flag{a}", "source_chain": ["x"], "confidence": 0.95, "format_match": True, "dedupe_key": "same", "evidence_refs": [], "submitted": False},
            )
        )
        self.assertEqual(1, len(state.projects[project.project_id].candidate_flags))
        self.assertEqual(0.95, state.projects[project.project_id].candidate_flags["same"].confidence)

    def test_export_handoff_and_reopen_preserve_memory(self) -> None:
        state = StateGraphService()
        project = ProjectSnapshot(
            project_id="project:web-2",
            challenge=ChallengeDefinition(id="web-2", name="x", category="web", difficulty="easy", target="http://demo"),
        )
        state.upsert_project(project)
        state.append_event(
            Event(
                type=EventType.OBSERVATION,
                project_id=project.project_id,
                run_id="run1",
                payload={"description": "found debug", "source": "unit", "findings": [{"title": "debug", "severity": "medium"}]},
            )
        )
        handoff = state.export_handoff(project.project_id)
        self.assertIn("finding-confirmed", handoff.summary)
        state.reopen_project(project.project_id)
        self.assertEqual("reopened", state.projects[project.project_id].snapshot.status)


if __name__ == "__main__":
    unittest.main()
