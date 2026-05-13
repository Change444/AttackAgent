import type { ProjectStatusReport } from '../../api/types';

export default function GlobalStats({ projects }: { projects: ProjectStatusReport[] }) {
  const totalSolvers = projects.reduce((s, p) => s + p.solver_count, 0);
  const totalIdeas = projects.reduce((s, p) => s + p.idea_count, 0);
  const totalFacts = projects.reduce((s, p) => s + p.fact_count, 0);
  const totalReviews = projects.reduce((s, p) => s + p.pending_review_count, 0);
  const totalFlags = projects.reduce((s, p) => s + p.candidate_flags.length, 0);
  const runningCount = projects.filter((p) => p.status === 'running').length;

  return (
    <div className="grid grid-cols-6 gap-3">
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4 text-center">
        <p className="text-xs text-slate-dark mb-1">Projects</p>
        <p className="text-xl font-mono font-bold text-base-50">{projects.length}</p>
        <p className="text-xs text-cyan mt-1">{runningCount} running</p>
      </div>
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4 text-center">
        <p className="text-xs text-slate-dark mb-1">Solvers</p>
        <p className="text-xl font-mono font-bold text-base-50">{totalSolvers}</p>
      </div>
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4 text-center">
        <p className="text-xs text-slate-dark mb-1">Ideas</p>
        <p className="text-xl font-mono font-bold text-base-50">{totalIdeas}</p>
      </div>
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4 text-center">
        <p className="text-xs text-slate-dark mb-1">Facts</p>
        <p className="text-xl font-mono font-bold text-base-50">{totalFacts}</p>
      </div>
      <div className="bg-base-800 rounded-lg border border-amber/30 p-4 text-center">
        <p className="text-xs text-amber-dark mb-1">Pending Reviews</p>
        <p className="text-xl font-mono font-bold text-amber">{totalReviews}</p>
      </div>
      <div className="bg-base-800 rounded-lg border border-cyan/30 p-4 text-center">
        <p className="text-xs text-cyan-dark mb-1">Candidate Flags</p>
        <p className="text-xl font-mono font-bold text-cyan">{totalFlags}</p>
      </div>
    </div>
  );
}