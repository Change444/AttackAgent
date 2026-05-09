"""Team CLI — Phase H.

Click-based command-line interface with rich Console output.
All commands delegate to TeamRuntime.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import click
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.json import JSON as RichJSON
except ImportError:
    print("Error: click and rich are required. Run: pip install attack-agent[cli]", file=sys.stderr)
    sys.exit(1)

from attack_agent.team.protocol import HumanDecisionChoice, ReviewRequest, to_dict
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig


console = Console()


def _load_config(config_path: str) -> TeamRuntimeConfig:
    """Load TeamRuntimeConfig from JSON file, falling back to defaults."""
    path = Path(config_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TeamRuntimeConfig(**data)
    return TeamRuntimeConfig()


def _format_status_table(reports: list) -> Table:
    """Render a list of ProjectStatusReport into a rich Table."""
    table = Table(title="Projects", show_header=True, header_style="bold cyan")
    table.add_column("Project ID", style="cyan", no_wrap=True)
    table.add_column("Challenge", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Solvers", justify="right")
    table.add_column("Ideas", justify="right")
    table.add_column("Facts", justify="right")
    table.add_column("Pending Reviews", justify="right")
    for r in reports:
        status_style = "bold green" if r.status == "done" else "bold red" if r.status == "abandoned" else ""
        table.add_row(
            r.project_id, r.challenge_id, f"[{status_style}]{r.status}[/]",
            str(r.solver_count), str(r.idea_count), str(r.fact_count),
            str(r.pending_review_count),
        )
    return table


def _format_reviews_table(reviews: list[ReviewRequest]) -> Table:
    """Render a list of ReviewRequest into a rich Table."""
    table = Table(title="Pending Reviews", show_header=True, header_style="bold cyan")
    table.add_column("Request ID", style="cyan", no_wrap=True)
    table.add_column("Project", style="green")
    table.add_column("Action", style="yellow")
    table.add_column("Risk", style="red")
    table.add_column("Title", style="white")
    table.add_column("Status", style="magenta")
    for r in reviews:
        table.add_row(
            r.request_id, r.project_id, r.action_type,
            r.risk_level, r.title, r.status.value,
        )
    return table


@click.group()
def team():
    """AttackAgent Team Runtime commands."""
    pass


@team.command()
@click.option("--config", "-c", default="config/team_settings.json", help="TeamRuntimeConfig JSON path")
def run(config: str):
    """Run all projects with TeamRuntime."""
    rt_config = _load_config(config)
    runtime = TeamRuntime(rt_config)
    # discover challenge IDs from config or prompt
    challenge_ids = rt_config.__dict__.get("challenge_ids", [])
    if not challenge_ids:
        # fallback: run a single demo challenge
        challenge_ids = ["demo-1"]

    results = runtime.run_all(challenge_ids)
    console.print(_format_status_table([
        r for p in results.values()
        for r in [runtime.get_status(p.project_id)]
        if r is not None
    ]))
    runtime.close()


@team.command()
@click.argument("project_id", required=False)
def status(project_id: str | None):
    """Show project status. Without project_id, lists all projects."""
    runtime = TeamRuntime()
    if project_id:
        report = runtime.get_status(project_id)
        if report is None:
            console.print(f"[bold red]Project {project_id} not found.[/]")
        else:
            panel = Panel(
                f"[bold]Project:[/] {report.project_id}\n"
                f"[bold]Challenge:[/] {report.challenge_id}\n"
                f"[bold]Status:[/] {report.status}\n"
                f"[bold]Solvers:[/] {report.solver_count}\n"
                f"[bold]Ideas:[/] {report.idea_count}\n"
                f"[bold]Facts:[/] {report.fact_count}\n"
                f"[bold]Pending Reviews:[/] {report.pending_review_count}\n"
                f"[bold]Candidate Flags:[/] {', '.join(report.candidate_flags) or 'none'}\n"
                f"[bold]Last Observation:[/] {report.last_observation_severity or 'none'}",
                title=f"Project {report.project_id}",
                border_style="cyan",
            )
            console.print(panel)
    else:
        reports = runtime.list_projects()
        if not reports:
            console.print("[yellow]No projects found.[/]")
        else:
            console.print(_format_status_table(reports))
    runtime.close()


@team.command()
@click.argument("project_id")
def replay(project_id: str):
    """Export and display the full event log for a project."""
    runtime = TeamRuntime()
    log = runtime.replay(project_id)
    if not log:
        console.print(f"[yellow]No events found for project {project_id}.[/]")
    else:
        console.print(Panel(
            RichJSON(json.dumps(log, indent=2)),
            title=f"Event Log: {project_id}",
            border_style="green",
        ))
    runtime.close()


@team.command("reviews")
@click.argument("project_id", required=False)
def reviews_cmd(project_id: str | None):
    """List pending reviews. Optional: filter by project_id."""
    runtime = TeamRuntime()
    reviews = runtime.get_pending_reviews(project_id or "")
    if not reviews:
        console.print("[yellow]No pending reviews.[/]")
    else:
        console.print(_format_reviews_table(reviews))
    runtime.close()


@team.group("review")
def review():
    """Resolve review requests (approve / reject / modify)."""
    pass


@review.command()
@click.argument("request_id")
@click.option("--project-id", "-p", default="", help="Project ID for locating the review")
@click.option("--reason", "-r", default="", help="Reason for approval")
def approve(request_id: str, project_id: str, reason: str):
    """Approve a pending review request."""
    runtime = TeamRuntime()
    result = runtime.resolve_review(
        request_id, HumanDecisionChoice.APPROVED, reason=reason, project_id=project_id
    )
    if result:
        console.print(f"[bold green]Approved:[/] {result.request_id} → status={result.status.value}")
    else:
        console.print(f"[bold red]Review {request_id} not found or already resolved.[/]")
    runtime.close()


@review.command()
@click.argument("request_id")
@click.option("--project-id", "-p", default="", help="Project ID for locating the review")
@click.option("--reason", "-r", default="", help="Reason for rejection")
def reject(request_id: str, project_id: str, reason: str):
    """Reject a pending review request."""
    runtime = TeamRuntime()
    result = runtime.resolve_review(
        request_id, HumanDecisionChoice.REJECTED, reason=reason, project_id=project_id
    )
    if result:
        console.print(f"[bold red]Rejected:[/] {result.request_id} → status={result.status.value}")
    else:
        console.print(f"[bold red]Review {request_id} not found or already resolved.[/]")
    runtime.close()


@review.command()
@click.argument("request_id")
@click.option("--project-id", "-p", default="", help="Project ID for locating the review")
@click.option("--reason", "-r", default="", help="Reason for modification")
def modify(request_id: str, project_id: str, reason: str):
    """Modify a pending review request."""
    runtime = TeamRuntime()
    result = runtime.resolve_review(
        request_id, HumanDecisionChoice.MODIFIED, reason=reason, project_id=project_id
    )
    if result:
        console.print(f"[bold yellow]Modified:[/] {result.request_id} → status={result.status.value}")
    else:
        console.print(f"[bold red]Review {request_id} not found or already resolved.[/]")
    runtime.close()


@team.command()
@click.argument("project_id")
def observe(project_id: str):
    """Run observation detectors and display the report."""
    runtime = TeamRuntime()
    report = runtime.observe(project_id)
    severity_style = {
        "critical": "bold red",
        "warning": "bold yellow",
        "info": "bold blue",
    }.get(report.severity, "white")

    obs_lines = "\n".join(
        f"  [{severity_style}]{n.kind}[/]: {n.description} (solver={n.solver_id})"
        for n in report.observations
    ) or "  None"

    action_lines = "\n".join(
        f"  - {a}" for a in report.suggested_actions
    ) or "  None"

    panel = Panel(
        f"[bold]Severity:[/] [{severity_style}]{report.severity}[/]\n\n"
        f"[bold]Observations:[/]\n{obs_lines}\n\n"
        f"[bold]Suggested Actions:[/]\n{action_lines}",
        title=f"Observation Report: {project_id}",
        border_style="cyan",
    )
    console.print(panel)
    runtime.close()


@team.command()
@click.option("--port", "-p", default=8000, type=int, help="Port for the API server")
def serve(port: int):
    """Start the FastAPI API server."""
    try:
        import uvicorn
        from attack_agent.team.api import create_app
    except ImportError:
        console.print("[bold red]Error: fastapi and uvicorn required. Run: pip install attack-agent[api][/]")
        sys.exit(1)

    runtime = TeamRuntime()
    app = create_app(runtime)
    console.print(f"[bold green]Starting API server on port {port}...[/]")
    uvicorn.run(app, host="0.0.0.0", port=port)


def team_main(argv: list[str] | None = None) -> None:
    """Entry point for `attack-agent team ...` commands."""
    team.main(args=argv or [], standalone_mode=True)