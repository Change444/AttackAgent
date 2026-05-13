import { createContext, useContext, useState, type ReactNode } from 'react';

const ProjectContext = createContext<{
  projectId: string | null;
  setProjectId: (id: string | null) => void;
}>({ projectId: null, setProjectId: () => {} });

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState<string | null>(null);
  return (
    <ProjectContext.Provider value={{ projectId, setProjectId }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProjectContext() {
  return useContext(ProjectContext);
}