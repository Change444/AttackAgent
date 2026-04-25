from __future__ import annotations

import unittest
from datetime import timedelta

from attack_agent.models import AgentStage, Asset, Evidence, Finding, utc_now
from attack_agent.world_state import WorldState


class WorldStateTests(unittest.TestCase):
    def test_evidence_priority_overrides_lower_confidence_state(self) -> None:
        state = WorldState()
        weak = Evidence(id="e1", description="weak", source="a", confidence=0.4)
        strong = Evidence(id="e2", description="strong", source="b", confidence=0.9)
        state.add_evidence(weak)
        state.add_evidence(strong)
        state.upsert_finding(Finding(id="f1", asset_id="a1", title="x", source="a", confidence=0.5, evidence_ref="e1"))
        state.upsert_finding(Finding(id="f1", asset_id="a1", title="x", source="b", confidence=0.4, evidence_ref="e2"))
        self.assertEqual(state.findings["f1"].source, "b")

    def test_expire_entities_removes_old_records(self) -> None:
        state = WorldState()
        old = utc_now() - timedelta(seconds=20)
        state.upsert_asset(Asset(id="a1", hostname="demo", source="t", timestamp=old, ttl_seconds=5))
        state.expire_entities(now=utc_now())
        self.assertEqual({}, state.assets)

    def test_unlock_stage_appends_history(self) -> None:
        state = WorldState()
        state.unlock_stage(AgentStage.MAPPING, source="unit", notes="unlock")
        self.assertEqual(AgentStage.MAPPING, state.stage)
        self.assertEqual(2, len(state.stage_history))


if __name__ == "__main__":
    unittest.main()
