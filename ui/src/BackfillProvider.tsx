import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  cancelBackfill,
  createBackfill,
  streamBackfill,
  type BackfillJob,
  type Call,
} from "./api";

type BackfillState = {
  job: BackfillJob | null;
  analyzedCalls: Call[];
  boardsRefreshToken: number;
  start: (agentId: string, options?: Record<string, unknown>) => Promise<void>;
  cancel: () => Promise<void>;
  dismiss: () => void;
};

const Ctx = createContext<BackfillState | null>(null);

// Owns the active backfill job + its SSE subscription at the app root, so the progress
// toast and the live-merged Calls list survive route changes.
export function BackfillProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<BackfillJob | null>(null);
  const [analyzedCalls, setAnalyzedCalls] = useState<Call[]>([]);
  const [boardsRefreshToken, setBoardsRefreshToken] = useState(0);
  const stopRef = useRef<(() => void) | null>(null);

  const stopStream = useCallback(() => {
    stopRef.current?.();
    stopRef.current = null;
  }, []);

  const subscribe = useCallback((id: string) => {
    stopStream();
    stopRef.current = streamBackfill(id, (e) => {
      if (e.type === "progress" || e.type === "done") {
        setJob(e.data);
        // On done, keep the job so the toast can show its summary until dismissed.
        if (e.type === "done") stopStream();
      } else if (e.type === "call-analyzed") {
        setAnalyzedCalls((prev) => {
          const next = prev.filter((c) => c.id !== e.data.id);
          next.unshift(e.data);  // newest first, deduped by id
          return next;
        });
      } else if (e.type === "boards-refresh") {
        setBoardsRefreshToken((n) => n + 1);
      } else if (e.type === "error") {
        setJob((j) => (j ? { ...j, status: "failed", error: e.error } : j));
        stopStream();
      }
    });
  }, [stopStream]);

  const start = useCallback(async (agentId: string, options?: Record<string, unknown>) => {
    setAnalyzedCalls([]);
    const j = await createBackfill({ agent_id: agentId, options });
    setJob(j);
    subscribe(j.id);
  }, [subscribe]);

  const cancel = useCallback(async () => {
    if (!job) return;
    try {
      const j = await cancelBackfill(job.id);
      setJob(j);
    } catch { /* best-effort */ }
    stopStream();
  }, [job, stopStream]);

  const dismiss = useCallback(() => {
    stopStream();
    setJob(null);
  }, [stopStream]);

  const value: BackfillState = {
    job, analyzedCalls, boardsRefreshToken, start, cancel, dismiss,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBackfill(): BackfillState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBackfill must be used within BackfillProvider");
  return v;
}
