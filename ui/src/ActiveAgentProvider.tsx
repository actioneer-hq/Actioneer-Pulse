import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { type Agent, listAgents, setApiAgent } from "./api";
import { useAuth } from "./auth";

// The selected project (agent). Everything in the main UI scopes to it. Mirrors the activeOrg pattern
// in auth.tsx: seeded from localStorage, kept in sync with the api layer, re-pinned to a valid agent.
const AGENT_KEY = "voiceobs.activeAgent";

type State = {
  agents: Agent[];
  activeAgent: string | null;
  active: Agent | null;
  setActiveAgent: (id: string) => void;
  loading: boolean;
  reload: () => void;
};

const Ctx = createContext<State | null>(null);

export function ActiveAgentProvider({ children }: { children: ReactNode }) {
  const { activeOrg } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeAgent, setActiveAgentState] = useState<string | null>(
    () => localStorage.getItem(AGENT_KEY),
  );

  useEffect(() => { setApiAgent(activeAgent); }, [activeAgent]);
  useEffect(() => {
    if (activeAgent) localStorage.setItem(AGENT_KEY, activeAgent);
    else localStorage.removeItem(AGENT_KEY);
  }, [activeAgent]);

  const reload = useCallback(() => {
    if (!activeOrg) { setAgents([]); return; }
    setLoading(true);
    listAgents()
      .then((list) => {
        setAgents(list);
        // Pin to the stored agent if it still exists in this org, else the first one.
        setActiveAgentState((cur) => (list.some((a) => a.id === cur) ? cur : (list[0]?.id ?? null)));
      })
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, [activeOrg]);

  useEffect(() => { reload(); }, [reload]);

  const setActiveAgent = useCallback((id: string) => {
    setApiAgent(id);
    setActiveAgentState(id);
  }, []);

  const active = agents.find((a) => a.id === activeAgent) ?? null;
  return (
    <Ctx.Provider value={{ agents, activeAgent, active, setActiveAgent, loading, reload }}>
      {children}
    </Ctx.Provider>
  );
}

export function useActiveAgent(): State {
  const v = useContext(Ctx);
  if (!v) throw new Error("useActiveAgent must be used within ActiveAgentProvider");
  return v;
}
