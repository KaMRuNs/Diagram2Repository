import { Download, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Graph, Options, StackChoice } from "../types";

type Category = keyof StackChoice;

const CHOICES: Record<Category, { value: string; label: string; hint: string }[]> = {
  backend: [
    { value: "node", label: "Node.js + Express", hint: "package.json, src/index.js" },
    { value: "python", label: "Python + FastAPI", hint: "requirements.txt, main.py" },
    { value: "go", label: "Go", hint: "go.mod, main.go (net/http)" },
  ],
  frontend: [
    { value: "react", label: "React + Vite", hint: "Vite dev server, src/App.jsx" },
    { value: "static", label: "Static HTML", hint: "index.html served by nginx" },
  ],
  database: [
    { value: "postgres", label: "PostgreSQL 16", hint: "init.sql + Prisma (postgresql)" },
    { value: "mysql", label: "MySQL 8.4", hint: "init.sql + Prisma (mysql)" },
  ],
};

const TITLES: Record<Category, string> = {
  backend: "Backend services",
  frontend: "Frontends",
  database: "Database",
};

/** Components each category would rewrite. Mirrors backend/app/tools/stack.py closely enough to preview. */
function members(graph: Graph, cat: Category): string[] {
  const infra = /postgres|mysql|maria|mongo|redis|kafka|rabbit|minio|nginx/i;
  return graph.nodes
    .filter((n) => {
      if (cat === "frontend") return n.kind === "frontend";
      if (cat === "database") return n.kind === "database" && !/mongo|minio|s3/i.test(n.tech ?? "");
      return (n.kind === "service" || n.kind === "unknown") && !infra.test(n.tech ?? "");
    })
    .map((n) => n.label);
}

export function StackDialog({
  graph,
  options,
  busy,
  onCancel,
  onConfirm,
}: {
  graph: Graph;
  options: Options;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (stack: StackChoice) => void;
}) {
  const [stack, setStack] = useState<StackChoice>(options.stack);
  const groups = (Object.keys(CHOICES) as Category[])
    .map((cat) => ({ cat, names: members(graph, cat) }))
    .filter((g) => g.names.length > 0 || (g.cat === "database" && graph.tables.length > 0));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="stack-title">
        <header className="modal-head">
          <h2 id="stack-title">Download repository</h2>
          <button className="icon-btn" onClick={onCancel} disabled={busy} aria-label="Close">
            <X size={16} />
          </button>
        </header>
        <p className="modal-sub">
          Pick a tech stack. Each component gets a small working starter app in that stack, wired to the
          services it connects to on your diagram.
        </p>

        {groups.length === 0 && <p className="hint">Nothing in this diagram needs a stack choice.</p>}

        {groups.map(({ cat, names }) => (
          <fieldset key={cat} className="stack-group">
            <legend>
              {TITLES[cat]}
              {names.length > 0 && <span className="stack-members">{names.join(", ")}</span>}
            </legend>
            <div className="stack-options">
              {[{ value: "auto", label: "As drawn", hint: "Keep what the board says" }, ...CHOICES[cat]].map((o) => (
                <label key={o.value} className={`stack-option${stack[cat] === o.value ? " on" : ""}`}>
                  <input
                    type="radio"
                    name={cat}
                    value={o.value}
                    checked={stack[cat] === o.value}
                    onChange={() => setStack({ ...stack, [cat]: o.value })}
                    disabled={busy}
                  />
                  <span className="stack-label">{o.label}</span>
                  <span className="stack-hint">{o.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}

        <footer className="modal-foot">
          <span className="hint">
            {options.license_type} license · {options.author}
          </span>
          <div className="modal-actions">
            <button className="btn" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button className="btn primary" onClick={() => onConfirm(stack)} disabled={busy}>
              {busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />}
              {busy ? "Generating…" : "Generate & download"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
