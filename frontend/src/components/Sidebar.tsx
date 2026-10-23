import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  FileCode2,
  FileText,
  Loader2,
  MinusCircle,
  Table2,
  XCircle,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { NodeKind, StageState } from "../types";
import { KIND_STYLE } from "../lib/graph";
import { STAGES, type JobState } from "../useJob";
import { DND_KIND } from "./DiagramCanvas";
import { ShapeSvg } from "./Shapes";

function Section({ title, children, defaultOpen = true }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="panel-section">
      <button className="section-head" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {title}
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}

const PALETTE: NodeKind[] = ["service", "database", "cache", "queue", "gateway", "frontend", "external"];

export function ShapePalette({ onAdd, disabled }: { onAdd: (k: NodeKind | "table") => void; disabled: boolean }) {
  const drag = (kind: string) => (e: React.DragEvent) => {
    e.dataTransfer.setData(DND_KIND, kind);
    e.dataTransfer.effectAllowed = "copy";
  };
  return (
    <div className={`palette${disabled ? " disabled" : ""}`}>
      {PALETTE.map((k) => (
        <button
          key={k}
          className="palette-item"
          title={`Add ${KIND_STYLE[k].label} (click or drag onto canvas)`}
          draggable={!disabled}
          onDragStart={drag(k)}
          onClick={() => onAdd(k)}
          disabled={disabled}
        >
          <ShapeSvg kind={k} w={44} h={28} />
          <span>{KIND_STYLE[k].label}</span>
        </button>
      ))}
      <button
        className="palette-item"
        title="Add table (click or drag onto canvas)"
        draggable={!disabled}
        onDragStart={drag("table")}
        onClick={() => onAdd("table")}
        disabled={disabled}
      >
        <Table2 size={26} strokeWidth={1.3} color="#6c8ebf" />
        <span>Table</span>
      </button>
    </div>
  );
}

function useTick(active: boolean) {
  const [, setT] = useState(0);
  useEffect(() => {
    if (!active) return;
    const h = setInterval(() => setT((t) => t + 1), 1000);
    return () => clearInterval(h);
  }, [active]);
}

function StageIcon({ s }: { s: StageState }) {
  switch (s.state) {
    case "running":
      return <Loader2 size={15} className="spin accent" />;
    case "done":
      return <CheckCircle2 size={15} className="ok" />;
    case "failed":
      return <XCircle size={15} className="bad" />;
    case "skipped":
      return <MinusCircle size={15} className="muted" />;
    default:
      return <CircleDashed size={15} className="muted" />;
  }
}

export function PipelineView({ job }: { job: JobState }) {
  const running = Object.values(job.stages).some((s) => s.state === "running");
  useTick(running);
  if (!job.id) return <p className="hint">Upload a whiteboard photo or try a sample to start.</p>;

  return (
    <ol className="stages">
      {STAGES.map(({ name, label }) => {
        const s = job.stages[name];
        const secs =
          s.state === "running" && s.startedAt ? Math.round((Date.now() - s.startedAt) / 1000) : s.seconds;
        return (
          <li key={name} className={`stage ${s.state}`}>
            <StageIcon s={s} />
            <div className="stage-body">
              <div className="stage-title">
                {label}
                {secs != null && s.state !== "skipped" && <span className="stage-time">{secs}s</span>}
              </div>
              {s.model && <div className="stage-model">{s.model}</div>}
              {s.state === "running" && s.tokens ? <div className="stage-model">{s.tokens} tokens…</div> : null}
              {name === "generate" && job.tools.length > 0 && (
                <ul className="tool-log">
                  {job.tools.map((t, i) => (
                    <li key={i} className={t.ok ? "" : "failed"} title={t.error ?? t.files.join("\n")}>
                      <code>{t.name}</code>
                      <span className={`by ${t.by}`}>{t.by === "agent" ? "agent" : "auto"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function fileIcon(path: string) {
  return /\.(md|txt)$|LICENSE$/.test(path) ? <FileText size={14} /> : <FileCode2 size={14} />;
}

export function FileList({
  files,
  active,
  onOpen,
}: {
  files: string[];
  active: string | null;
  onOpen: (p: string) => void;
}) {
  if (!files.length) return <p className="hint">Generated files appear here.</p>;
  const sorted = [...files].sort((a, b) => a.split("/").length - b.split("/").length || a.localeCompare(b));
  return (
    <ul className="files">
      {sorted.map((p) => (
        <li key={p}>
          <button className={p === active ? "active" : ""} onClick={() => onOpen(p)} title={p}>
            {fileIcon(p)}
            <span>{p}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Sidebar({
  job,
  onAdd,
  canEdit,
  activeFile,
  onOpenFile,
}: {
  job: JobState;
  onAdd: (k: NodeKind | "table") => void;
  canEdit: boolean;
  activeFile: string | null;
  onOpenFile: (p: string) => void;
}) {
  return (
    <aside className="sidebar left">
      <Section title="Shapes">
        <ShapePalette onAdd={onAdd} disabled={!canEdit} />
      </Section>
      <Section title="Pipeline">
        <PipelineView job={job} />
      </Section>
      <Section title={`Files${Object.keys(job.files).length ? ` (${Object.keys(job.files).length})` : ""}`}>
        <FileList files={Object.keys(job.files)} active={activeFile} onOpen={onOpenFile} />
      </Section>
    </aside>
  );
}
