import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { FormatPanel } from "./components/FormatPanel";
import { Sidebar } from "./components/Sidebar";
import { StackDialog } from "./components/StackDialog";
import { Toolbar } from "./components/Toolbar";
import { CodeView, EmptyState, PageTabs, PhotoView, type PageTab } from "./components/Views";
import { downloadDiagram, type ImageFormat } from "./lib/exportImage";
import { newNode, newTable, slugify, tableId } from "./lib/graph";
import type { Graph, NodeKind, Selection, StackChoice } from "./types";
import { useJob } from "./useJob";

const FILE = "file:";

function saveUrl(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  a.click();
}

export default function Root() {
  return (
    <ReactFlowProvider>
      <App />
    </ReactFlowProvider>
  );
}

function App() {
  const rf = useReactFlow();
  const { job, connect, resetGeneration, setOptions } = useJob();
  const [stackOpen, setStackOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const pendingDownload = useRef(false);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [layoutKey, setLayoutKey] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [view, setView] = useState("diagram");
  const [openFiles, setOpenFiles] = useState<string[]>([]);
  const [useAgent, setUseAgent] = useState(true);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);
  const regenerating = useRef(false);

  const busy = job.status !== null && job.status !== "done" && job.status !== "failed";
  const visionRunning = ["preprocess", "summarize", "extract"].some((s) => job.stages[s as "extract"].state === "running");

  const notify = useCallback((text: string, bad = false) => {
    setToast({ text, bad });
    setTimeout(() => setToast(null), bad ? 6000 : 3000);
  }, []);

  // A graph from the server replaces local edits. Only fresh extractions get auto-laid-out;
  // regenerations keep the user's manual positions.
  useEffect(() => {
    if (!job.graph) return;
    setGraph(job.graph);
    setDirty(false);
    if (!regenerating.current) {
      setLayoutKey((k) => k + 1);
      setSelection(null);
      setView("diagram");
    }
  }, [job.graphVersion]);

  useEffect(() => {
    if (job.status === "done") {
      regenerating.current = false;
      if (!pendingDownload.current) notify("Repository ready. Use Download to get the zip or the diagram.");
    } else if (job.status === "failed") {
      regenerating.current = false;
      pendingDownload.current = false;
      setDownloading(false);
      notify(job.error ?? "Pipeline failed", true);
    }
  }, [job.status]);

  // The stack dialog regenerates first; the zip downloads as soon as the new bundle exists.
  useEffect(() => {
    if (pendingDownload.current && job.downloadUrl) {
      pendingDownload.current = false;
      setDownloading(false);
      setStackOpen(false);
      saveUrl(job.downloadUrl);
      notify("Repository downloaded.");
    }
  }, [job.downloadUrl]);

  const downloadRepo = async (stack: StackChoice) => {
    if (!job.id || !graph) return;
    const options = { ...job.options, stack };
    setOptions(options);
    pendingDownload.current = true;
    setDownloading(true);
    regenerating.current = true;
    resetGeneration();
    try {
      // Deterministic tools only: the agent already ran once, and the stack swap needs no model.
      await api.regenerate(job.id, graph, options, false);
    } catch (e) {
      pendingDownload.current = false;
      regenerating.current = false;
      setDownloading(false);
      notify(`Download failed: ${(e as Error).message}`, true);
    }
  };

  const exportImage = async (format: ImageFormat) => {
    if (!graph) return;
    try {
      const name = slugify(job.options.project_name ?? job.summary?.title ?? "diagram");
      await downloadDiagram(rf.getNodes(), format, `${name}-diagram`);
    } catch (e) {
      notify(`Image export failed: ${(e as Error).message}`, true);
    }
  };

  const reset = () => {
    setGraph(null);
    setSelection(null);
    setOpenFiles([]);
    setView("diagram");
    setDirty(false);
    regenerating.current = false;
  };

  const upload = async (file: File) => {
    try {
      const { job_id } = await api.upload(file, job.options.license_type, job.options.author);
      reset();
      connect(job_id, "upload", job.options);
    } catch (e) {
      notify(`Upload failed: ${(e as Error).message}`, true);
    }
  };

  const sample = async (name?: string) => {
    try {
      const pick = name ?? (await api.samples())[0]?.name;
      if (!pick) return notify("No samples found in /samples", true);
      const { job_id } = await api.startSample(pick);
      reset();
      connect(job_id, "sample", job.options);
    } catch (e) {
      notify(`Could not start sample: ${(e as Error).message}`, true);
    }
  };

  // Demo shortcut: /?sample=ecommerce opens a sample straight away.
  useEffect(() => {
    const name = new URLSearchParams(window.location.search).get("sample");
    if (name) void sample(name);
  }, []);

  const regenerate = async () => {
    if (!job.id || !graph) return;
    regenerating.current = true;
    resetGeneration();
    try {
      await api.regenerate(job.id, graph, job.options, useAgent);
    } catch (e) {
      regenerating.current = false;
      notify(`Regenerate failed: ${(e as Error).message}`, true);
    }
  };

  const editGraph = useCallback((g: Graph) => {
    setGraph(g);
    setDirty(true);
  }, []);

  const addShape = useCallback(
    (kind: NodeKind | "table"): string => {
      const g = graph ?? { nodes: [], edges: [], tables: [] };
      if (kind === "table") {
        const t = newTable(new Set(g.tables.map((x) => x.name)));
        editGraph({ ...g, tables: [...g.tables, t] });
        setSelection({ type: "table", id: tableId(t.name) });
        return tableId(t.name);
      }
      const n = newNode(kind, new Set(g.nodes.map((x) => x.id)));
      editGraph({ ...g, nodes: [...g.nodes, n] });
      setSelection({ type: "node", id: n.id });
      return n.id;
    },
    [graph, editGraph],
  );

  const openFile = (path: string) => {
    setOpenFiles((f) => (f.includes(path) ? f : [...f, path]));
    setView(FILE + path);
  };

  const closeTab = (id: string) => {
    const path = id.slice(FILE.length);
    setOpenFiles((f) => f.filter((p) => p !== path));
    if (view === id) setView("diagram");
  };

  const tabs: PageTab[] = [
    { id: "diagram", label: "Diagram", closable: false },
    ...(job.hasImage && job.id ? [{ id: "photo", label: "Photo", closable: false }] : []),
    ...openFiles.filter((p) => p in job.files).map((p) => ({ id: FILE + p, label: p.split("/").pop()!, closable: true })),
  ];
  const activeTab = tabs.some((t) => t.id === view) ? view : "diagram";
  const activeFile = activeTab.startsWith(FILE) ? activeTab.slice(FILE.length) : null;

  // The canvas stays mounted underneath other views so hand-placed positions survive tab switches
  // (and the image export can always reach it); other views are drawn on top.
  let overlay: JSX.Element | null = null;
  if (!job.id) {
    overlay = <EmptyState onUpload={upload} onSample={() => void sample()} />;
  } else if (activeTab === "photo" || (activeTab === "diagram" && !graph && job.hasImage)) {
    overlay = <PhotoView src={api.imageUrl(job.id)} scanning={visionRunning} />;
  } else if (activeFile) {
    overlay = <CodeView path={activeFile} content={job.files[activeFile] ?? ""} />;
  } else if (!graph) {
    overlay = (
      <div className="waiting">
        {job.status === "failed" ? job.error : "Waiting for the pipeline to start…"}
      </div>
    );
  }
  const center = (
    <>
      {graph && job.id && (
        <DiagramCanvas
          graph={graph}
          layoutKey={layoutKey}
          active={!overlay}
          selection={selection}
          onSelect={setSelection}
          onChange={editGraph}
          onAdd={addShape}
        />
      )}
      {overlay}
    </>
  );

  const title = job.options.project_name ?? job.summary?.title ?? (job.id ? "Untitled diagram" : "No diagram");

  return (
    <>
      <div className="app">
        <Toolbar
          title={dirty ? `${title} •` : title}
          busy={busy}
          dirty={dirty}
          canRegenerate={!!graph && !!job.id}
          canExport={!!graph && !!job.id}
          downloadUrl={job.downloadUrl}
          onUpload={upload}
          onSample={(n) => void sample(n)}
          onRegenerate={() => void regenerate()}
          onExportImage={(f) => void exportImage(f)}
          onDownloadRepo={() => setStackOpen(true)}
        />
        <div className="workspace">
          <Sidebar job={job} onAdd={addShape} canEdit={!!job.id && !busy} activeFile={activeFile} onOpenFile={openFile} />
          <main className="center">
            <div className="view">{center}</div>
            {job.id && <PageTabs tabs={tabs} active={activeTab} onActivate={setView} onClose={closeTab} />}
          </main>
          <FormatPanel
            graph={graph}
            selection={selection}
            onGraph={editGraph}
            onSelect={setSelection}
            summary={job.summary}
            options={job.options}
            onOptions={(o) => {
              setOptions(o);
              setDirty(true);
            }}
            useAgent={useAgent}
            onUseAgent={setUseAgent}
            warnings={job.warnings}
            error={job.error}
            agentMessage={job.agentMessage}
          />
        </div>
        {toast && <div className={`toast${toast.bad ? " bad" : ""}`}>{toast.text}</div>}
      </div>
      {stackOpen && graph && (
        <StackDialog
          graph={graph}
          options={job.options}
          busy={downloading}
          onCancel={() => setStackOpen(false)}
          onConfirm={(s) => void downloadRepo(s)}
        />
      )}
    </>
  );
}
