import { Routes, Route, Navigate } from 'react-router-dom';
import { SSEProvider } from './context/SSEContext';
import { ProjectProvider } from './context/ProjectContext';
import Layout from './components/layout/Layout';
import DashboardView from './views/Dashboard/DashboardView';
import ProjectWorkspaceView from './views/ProjectWorkspace/ProjectWorkspaceView';
import GraphView from './views/GraphView/GraphView';
import TeamBoardView from './views/TeamBoard/TeamBoardView';
import IdeaBoardView from './views/IdeaBoard/IdeaBoardView';
import MemoryBoardView from './views/MemoryBoard/MemoryBoardView';
import ObserverPanelView from './views/ObserverPanel/ObserverPanelView';
import ReviewQueueView from './views/ReviewQueue/ReviewQueueView';
import CandidateFlagPanelView from './views/CandidateFlagPanel/CandidateFlagPanelView';
import ArtifactViewerView from './views/ArtifactViewer/ArtifactViewerView';
import ReplayTimelineView from './views/ReplayTimeline/ReplayTimelineView';

export default function App() {
  return (
    <SSEProvider>
      <ProjectProvider>
        <Layout>
          <Routes>
            <Route path="/dashboard" element={<DashboardView />} />
            <Route path="/projects/:id" element={<ProjectWorkspaceView />} />
            <Route path="/projects/:id/graph" element={<GraphView />} />
            <Route path="/projects/:id/team" element={<TeamBoardView />} />
            <Route path="/projects/:id/ideas" element={<IdeaBoardView />} />
            <Route path="/projects/:id/memory" element={<MemoryBoardView />} />
            <Route path="/projects/:id/observer" element={<ObserverPanelView />} />
            <Route path="/projects/:id/flags" element={<CandidateFlagPanelView />} />
            <Route path="/projects/:id/artifacts" element={<ArtifactViewerView />} />
            <Route path="/projects/:id/replay" element={<ReplayTimelineView />} />
            <Route path="/reviews" element={<ReviewQueueView />} />
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Layout>
      </ProjectProvider>
    </SSEProvider>
  );
}