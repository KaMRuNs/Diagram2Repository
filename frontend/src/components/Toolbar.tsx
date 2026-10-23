import { ChevronDown, Download, FileImage, FolderDown, ImageUp, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ImageFormat } from "../lib/exportImage";
import type { Health } from "../types";

function HealthChip({ health }: { health: Health | null | "error" }) {
  if (health === null) return <span className="chip">Checking models…</span>;
  const hosted = health !== "error" && health.provider === "hosted";
  if (health === "error" || !health.reachable)
    return (
      <span className="chip bad" title={hosted ? "Check HOSTED_API_KEY and HOSTED_BASE_URL" : "Start the Ollama app, then reload"}>
        ● {hosted ? "Inference provider unreachable" : "Ollama offline"}
      </span>
    );
  const missing = Object.values(health.models).filter((m) => !m.installed);
  if (missing.length)
    return (
      <span
        className="chip warn"
        title={missing.map((m) => (hosted ? `${m.name} not offered by provider` : `ollama pull ${m.name}`)).join("\n")}
      >
        ● Missing {missing.map((m) => m.name).join(", ")}
      </span>
    );
  return (
    <span className="chip ok" title={Object.values(health.models).map((m) => m.name).join(" · ")}>
      ● {hosted ? "Hosted models ready" : "Local models ready"}
    </span>
  );
}

export function Toolbar({
  title,
  busy,
  dirty,
  canRegenerate,
  canExport,
  downloadUrl,
  onUpload,
  onSample,
  onRegenerate,
  onExportImage,
  onDownloadRepo,
}: {
  title: string;
  busy: boolean;
  dirty: boolean;
  canRegenerate: boolean;
  canExport: boolean;
  downloadUrl: string | null;
  onUpload: (f: File) => void;
  onSample: (name: string) => void;
  onRegenerate: () => void;
  onExportImage: (format: ImageFormat) => void;
  onDownloadRepo: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [health, setHealth] = useState<Health | null | "error">(null);
  const [samples, setSamples] = useState<{ name: string; title: string }[]>([]);
  const [menu, setMenu] = useState(false);
  const [dlMenu, setDlMenu] = useState(false);
  const ready = !!downloadUrl && !dirty;

  useEffect(() => {
    api.health().then(setHealth, () => setHealth("error"));
    api.samples().then(setSamples, () => setSamples([]));
  }, []);

  useEffect(() => {
    if (!menu && !dlMenu) return;
    const close = () => {
      setMenu(false);
      setDlMenu(false);
    };
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu, dlMenu]);

  return (
    <header className="menubar">
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
          <rect x="3" y="6" width="12" height="9" rx="2" fill="#dae8fc" stroke="#6c8ebf" strokeWidth="2" />
          <rect x="17" y="17" width="12" height="9" rx="2" fill="#d5e8d4" stroke="#82b366" strokeWidth="2" />
          <path d="M15 11h5v6" fill="none" stroke="#333" strokeWidth="2" />
        </svg>
        <span className="brand-name">Diagram2Repo</span>
      </div>
      <span className="doc-title" title={title}>
        {title}
      </span>

      <div className="menubar-actions">
        <HealthChip health={health} />
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
            e.target.value = "";
          }}
        />
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy}>
          <ImageUp size={15} /> <span className="lbl">Upload photo</span>
        </button>
        <div className="menu-wrap">
          <button
            className="btn"
            disabled={busy || !samples.length}
            onClick={(e) => {
              e.stopPropagation();
              setMenu(!menu);
              setDlMenu(false);
            }}
          >
            <Sparkles size={15} /> <span className="lbl">Samples</span> <ChevronDown size={13} />
          </button>
          {menu && (
            <ul className="menu">
              {samples.map((s) => (
                <li key={s.name}>
                  <button onClick={() => onSample(s.name)}>{s.title}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button
          className={`btn${dirty ? " primary" : ""}`}
          onClick={onRegenerate}
          disabled={busy || !canRegenerate}
          title="Regenerate the repository from the edited diagram"
        >
          <RefreshCw size={15} className={busy ? "spin" : ""} /> <span className="lbl">Regenerate</span>
        </button>
        <div className="menu-wrap">
          <button
            className={`btn${ready ? " primary" : ""}`}
            disabled={busy || !canExport}
            onClick={(e) => {
              e.stopPropagation();
              setDlMenu(!dlMenu);
              setMenu(false);
            }}
          >
            <Download size={15} /> <span className="lbl">Download</span> <ChevronDown size={13} />
          </button>
          {dlMenu && (
            <ul className="menu">
              <li>
                <button onClick={() => onExportImage("png")}>
                  <FileImage size={14} /> Diagram as PNG
                </button>
              </li>
              <li>
                <button onClick={() => onExportImage("jpg")}>
                  <FileImage size={14} /> Diagram as JPG
                </button>
              </li>
              <li className="menu-sep" />
              <li>
                <button onClick={onDownloadRepo}>
                  <FolderDown size={14} /> Repository (.zip)…
                </button>
              </li>
            </ul>
          )}
        </div>
      </div>
    </header>
  );
}
