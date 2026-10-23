import { Camera, Check, Copy, ImageUp, Sparkles, X } from "lucide-react";
import { useRef, useState } from "react";

export function CodeView({ path, content }: { path: string; content: string }) {
  const [copied, setCopied] = useState(false);
  const lines = content.replace(/\n$/, "").split("\n");
  return (
    <div className="code-view">
      <div className="code-head">
        <code>{path}</code>
        <button
          className="btn small"
          onClick={() => {
            void navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code">
        {lines.map((l, i) => (
          <div key={i} className={/^\s*(#|--|\/\/)/.test(l) ? "ln comment" : "ln"}>
            <span className="ln-no">{i + 1}</span>
            <span className="ln-text">{l || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

export function PhotoView({ src, scanning }: { src: string; scanning: boolean }) {
  return (
    <div className="photo-view">
      <div className={`photo-frame${scanning ? " scanning" : ""}`}>
        <img src={src} alt="Uploaded whiteboard" />
        {scanning && <div className="scanline" />}
      </div>
      {scanning && <p className="photo-caption">Vision models are reading the board…</p>}
    </div>
  );
}

export function EmptyState({ onUpload, onSample }: { onUpload: (f: File) => void; onSample: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) onUpload(f);
    e.target.value = "";
  };
  return (
    <div
      className={`empty${over ? " over" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files[0];
        if (f && f.type.startsWith("image/")) onUpload(f);
      }}
    >
      <div className="empty-card">
        <svg width="84" height="56" viewBox="0 0 84 56" aria-hidden>
          <rect x="2" y="4" width="30" height="20" rx="3" fill="#dae8fc" stroke="#6c8ebf" strokeWidth="1.5" />
          <rect x="52" y="4" width="30" height="20" rx="3" fill="#fff2cc" stroke="#d6b656" strokeWidth="1.5" />
          <path d="M52 40a15 4 0 0 1 30 0v10a15 4 0 0 1-30 0z" fill="#d5e8d4" stroke="#82b366" strokeWidth="1.5" />
          <path d="M32 14h18M67 24v12" stroke="#333" strokeWidth="1.5" markerEnd="url(#a)" />
          <defs>
            <marker id="a" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 0L6 3L0 6z" fill="#333" />
            </marker>
          </defs>
        </svg>
        <h2>Drop a whiteboard photo here</h2>
        <p>
          A hand-drawn architecture or database schema becomes a starter repo with <code>docker-compose.yml</code>,
          Prisma + SQL schema, README and LICENSE.
        </p>
        <div className="empty-actions">
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={pick} />
          <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={pick} />
          <button className="btn primary" onClick={() => fileRef.current?.click()}>
            <ImageUp size={15} /> Choose photo
          </button>
          <button className="btn mobile-only" onClick={() => camRef.current?.click()}>
            <Camera size={15} /> Take photo
          </button>
          <button className="btn" onClick={onSample}>
            <Sparkles size={15} /> Try a sample
          </button>
        </div>
        <p className="fine">Runs on local models via Ollama: gemma3 · qwen2.5-vl · qwen3</p>
      </div>
    </div>
  );
}

export type PageTab = { id: string; label: string; closable: boolean };

export function PageTabs({
  tabs,
  active,
  onActivate,
  onClose,
}: {
  tabs: PageTab[];
  active: string;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
}) {
  return (
    <nav className="pagetabs">
      {tabs.map((t) => (
        <div key={t.id} className={`pagetab${t.id === active ? " active" : ""}`}>
          <button onClick={() => onActivate(t.id)}>{t.label}</button>
          {t.closable && (
            <button className="tab-close" onClick={() => onClose(t.id)} aria-label={`Close ${t.label}`}>
              <X size={12} />
            </button>
          )}
        </div>
      ))}
    </nav>
  );
}
