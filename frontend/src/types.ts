// Mirrors backend/app/schemas.py

export type NodeKind =
  | "service"
  | "database"
  | "cache"
  | "queue"
  | "gateway"
  | "frontend"
  | "external"
  | "unknown";

export const NODE_KINDS: NodeKind[] = [
  "service",
  "database",
  "cache",
  "queue",
  "gateway",
  "frontend",
  "external",
  "unknown",
];

export type LicenseType = "MIT" | "Apache-2.0" | "BSD-3-Clause";
export const LICENSES: LicenseType[] = ["MIT", "Apache-2.0", "BSD-3-Clause"];

export interface GNode {
  id: string;
  label: string;
  kind: NodeKind;
  ports: number[];
  tech: string | null;
}

export interface GEdge {
  source: string;
  target: string;
  label: string | null;
  protocol: string | null;
}

export interface Column {
  name: string;
  type: string;
  pk: boolean;
  fk: string | null;
  nullable: boolean;
  unique: boolean;
}

export interface Table {
  name: string;
  columns: Column[];
}

export interface Graph {
  nodes: GNode[];
  edges: GEdge[];
  tables: Table[];
}

export interface Summary {
  title: string;
  description: string;
  data_flow: string;
  recommended_stack: Record<string, string>;
}

export interface StackChoice {
  backend: "auto" | "node" | "python" | "go";
  frontend: "auto" | "react" | "static";
  database: "auto" | "postgres" | "mysql";
}

export const DEFAULT_STACK: StackChoice = { backend: "auto", frontend: "auto", database: "auto" };

export interface Options {
  license_type: LicenseType;
  author: string;
  project_name: string | null;
  stack: StackChoice;
}

export type JobStatus =
  | "queued"
  | "preprocessing"
  | "summarizing"
  | "extracting"
  | "normalizing"
  | "generating"
  | "done"
  | "failed";

export interface JobView {
  id: string;
  status: JobStatus;
  source: "upload" | "sample";
  has_image: boolean;
  summary: Summary | null;
  graph: Graph | null;
  options: Options;
  files: Record<string, string>;
  warnings: string[];
  error: string | null;
  download_url: string | null;
  last_seq: number;
}

export interface JobEvent {
  seq: number;
  type: string;
  data: Record<string, any>;
  ts: number;
}

export interface Health {
  provider: "ollama" | "hosted";
  reachable: boolean;
  models: Record<string, { name: string; installed: boolean }>;
}

export interface ToolCall {
  name: string;
  ok: boolean;
  by: "agent" | "fallback";
  files: string[];
  error: string | null;
}

export type StageName = "preprocess" | "summarize" | "extract" | "normalize" | "generate";

export interface StageState {
  state: "pending" | "running" | "done" | "skipped" | "failed";
  model?: string | null;
  startedAt?: number;
  seconds?: number;
  tokens?: number;
}

export type Selection = { type: "node" | "edge" | "table"; id: string } | null;
