import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { DEFAULT_STACK } from "./types";
import type {
  Graph,
  JobEvent,
  JobStatus,
  Options,
  StageName,
  StageState,
  Summary,
  ToolCall,
} from "./types";

export const STAGES: { name: StageName; label: string }[] = [
  { name: "preprocess", label: "Clean up photo" },
  { name: "summarize", label: "Understand architecture" },
  { name: "extract", label: "Read handwriting" },
  { name: "normalize", label: "Normalize graph" },
  { name: "generate", label: "Agent builds repo" },
];

const freshStages = (): Record<StageName, StageState> => ({
  preprocess: { state: "pending" },
  summarize: { state: "pending" },
  extract: { state: "pending" },
  normalize: { state: "pending" },
  generate: { state: "pending" },
});

export interface JobState {
  id: string | null;
  source: "upload" | "sample" | null;
  status: JobStatus | null;
  hasImage: boolean;
  stages: Record<StageName, StageState>;
  summary: Summary | null;
  /** Latest graph from the server; `graphVersion` bumps when it should replace local edits. */
  graph: Graph | null;
  graphVersion: number;
  options: Options;
  files: Record<string, string>;
  tools: ToolCall[];
  warnings: string[];
  agentMessage: string | null;
  error: string | null;
  downloadUrl: string | null;
}

const initial: JobState = {
  id: null,
  source: null,
  status: null,
  hasImage: false,
  stages: freshStages(),
  summary: null,
  graph: null,
  graphVersion: 0,
  options: { license_type: "MIT", author: "Your Name", project_name: null, stack: DEFAULT_STACK },
  files: {},
  tools: [],
  warnings: [],
  agentMessage: null,
  error: null,
  downloadUrl: null,
};

export function useJob() {
  const [job, setJob] = useState<JobState>(initial);
  const closeRef = useRef<(() => void) | null>(null);
  const idRef = useRef<string | null>(null);

  const apply = useCallback((e: JobEvent) => {
    setJob((j) => {
      const d = e.data;
      switch (e.type) {
        case "status":
          return { ...j, status: d.status };
        case "stage_started": {
          const stages = { ...j.stages };
          stages[d.stage as StageName] = { state: "running", model: d.model, startedAt: Date.now() };
          if (d.stage === "normalize") {
            // a regeneration resets the tool log
            return { ...j, stages, tools: [], warnings: [], agentMessage: null, error: null };
          }
          return { ...j, stages };
        }
        case "stage_done": {
          const s = j.stages[d.stage as StageName];
          return {
            ...j,
            stages: { ...j.stages, [d.stage]: { ...s, state: "done", seconds: d.seconds } },
          };
        }
        case "progress": {
          const s = j.stages[d.stage as StageName];
          return { ...j, stages: { ...j.stages, [d.stage]: { ...s, tokens: d.tokens } } };
        }
        case "summary":
          return { ...j, summary: d.summary };
        case "graph":
          return { ...j, graph: d.graph, graphVersion: j.graphVersion + 1 };
        case "tool_call":
          return { ...j, tools: [...j.tools, d as ToolCall] };
        case "agent_message":
          return { ...j, agentMessage: d.text };
        case "warning":
          return j.warnings.includes(d.message) ? j : { ...j, warnings: [...j.warnings, d.message] };
        case "error": {
          const stages = { ...j.stages };
          for (const k of Object.keys(stages) as StageName[]) {
            if (stages[k].state === "running") stages[k] = { ...stages[k], state: "failed" };
          }
          return { ...j, stages, error: d.message };
        }
        default:
          return j;
      }
    });
    if (e.type === "done" && idRef.current) {
      void api.job(idRef.current).then((v) =>
        setJob((j) => ({ ...j, files: v.files, downloadUrl: v.download_url, warnings: v.warnings })),
      );
    }
  }, []);

  const connect = useCallback(
    (id: string, source: "upload" | "sample", options?: Options) => {
      closeRef.current?.();
      idRef.current = id;
      const stages = freshStages();
      if (source === "sample") {
        stages.preprocess.state = stages.summarize.state = stages.extract.state = "skipped";
      }
      setJob({ ...initial, id, source, status: "queued", stages, options: options ?? initial.options });
      closeRef.current = api.events(id, 0, apply);
      void api.job(id).then((v) => setJob((j) => ({ ...j, hasImage: v.has_image })));
    },
    [apply],
  );

  /** Mark the generation stages as pending again before a regenerate request. */
  const resetGeneration = useCallback(() => {
    setJob((j) => ({
      ...j,
      status: "queued",
      stages: { ...j.stages, normalize: { state: "pending" }, generate: { state: "pending" } },
      downloadUrl: null,
    }));
  }, []);

  // Image becomes available once preprocessing finishes.
  useEffect(() => {
    if (job.id && !job.hasImage && job.stages.preprocess.state === "done") {
      setJob((j) => ({ ...j, hasImage: true }));
    }
  }, [job.id, job.hasImage, job.stages.preprocess.state]);

  useEffect(() => () => closeRef.current?.(), []);

  const setOptions = useCallback((options: Options) => setJob((j) => ({ ...j, options })), []);

  return { job, connect, resetGeneration, setOptions };
}
