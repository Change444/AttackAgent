"""platform.py — legacy CompetitionPlatform removed (Phase K-2).

All entry-point wiring now lives in factory.py (build_team_runtime)
and team/runtime.py (TeamRuntime.solve_all). This file is kept as
a stub so existing imports of the module don't break, but exports
nothing. Use `from attack_agent.factory import build_team_runtime`
or `from attack_agent.team.runtime import TeamRuntime` instead.
"""