from __future__ import annotations

from .state_graph import StateGraphService


class WebConsoleView:
    def __init__(self, state_graph: StateGraphService) -> None:
        self.state_graph = state_graph

    def project_overview(self) -> list[dict[str, object]]:
        return [self.state_graph.query_graph(project_id, view="summary") for project_id in self.state_graph.projects]

    def render_text(self) -> str:
        lines: list[str] = []
        for project in self.project_overview():
            active_family = project["pattern_graph"]["active_family"] if project["pattern_graph"] else "n/a"
            lines.append(f"{project['project_id']} | {project['stage']} | {project['status']} | family={active_family} | flags={len(project['candidate_flags'])}")
        return "\n".join(lines)

    def render_pattern_graph_text(self, project_id: str) -> str:
        pattern = self.state_graph.query_graph(project_id, view="pattern")
        lines = [f"{project_id} | active_family={pattern['active_family'] or 'n/a'}"]
        for node in pattern["nodes"]:
            lines.append(f"{node['id']} | family={node['family']} | status={node['status']}")
        return "\n".join(lines)

    def render_run_journal_text(self, project_id: str) -> str:
        journal = self.state_graph.query_graph(project_id, view="events")
        events = journal["events"]
        lines = [f"{project_id} | events={len(events)}"]
        for event in events:
            lines.append(f"{event['type']} | {event['source']} | {event['run_id']}")
        return "\n".join(lines)
