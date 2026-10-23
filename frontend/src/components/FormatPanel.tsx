import { AlertTriangle, ArrowLeftRight, KeyRound, Plus, Trash2, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { Column, GEdge, GNode, Graph, Options, Selection, Summary, Table } from "../types";
import { LICENSES, NODE_KINDS } from "../types";
import { KIND_STYLE, tableId } from "../lib/graph";

const COLUMN_TYPES = ["String", "Int", "BigInt", "Float", "Decimal", "Boolean", "DateTime", "Json", "Uuid"];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

/** Text input that commits on blur/Enter so typing doesn't rebuild the canvas per keystroke. */
function LazyInput({
  value,
  onCommit,
  placeholder,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input
      className={className}
      value={v}
      placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => v !== value && onCommit(v)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

function NodeForm({ node, onPatch, onDelete }: { node: GNode; onPatch: (p: Partial<GNode>) => void; onDelete: () => void }) {
  return (
    <>
      <h3 className="panel-title">
        <span className="swatch" style={{ background: KIND_STYLE[node.kind].fill, borderColor: KIND_STYLE[node.kind].stroke }} />
        Component
      </h3>
      <Field label="Label">
        <LazyInput value={node.label} onCommit={(label) => onPatch({ label })} />
      </Field>
      <Field label="Kind">
        <select value={node.kind} onChange={(e) => onPatch({ kind: e.target.value as GNode["kind"] })}>
          {NODE_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_STYLE[k].label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Technology">
        <LazyInput value={node.tech ?? ""} placeholder="postgres, redis, fastapi…" onCommit={(t) => onPatch({ tech: t.trim() || null })} />
      </Field>
      <Field label="Ports">
        <LazyInput
          value={node.ports.join(", ")}
          placeholder="8080"
          onCommit={(v) =>
            onPatch({
              ports: v
                .split(/[,\s]+/)
                .map((p) => parseInt(p.replace(":", ""), 10))
                .filter((p) => p > 0 && p < 65536),
            })
          }
        />
      </Field>
      <div className="field-static">
        <span className="field-label">Service id</span>
        <code>{node.id}</code>
      </div>
      <button className="btn danger block" onClick={onDelete}>
        <Trash2 size={14} /> Delete component
      </button>
    </>
  );
}

function EdgeForm({
  edge,
  labels,
  onPatch,
  onReverse,
  onDelete,
}: {
  edge: GEdge;
  labels: Record<string, string>;
  onPatch: (p: Partial<GEdge>) => void;
  onReverse: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <h3 className="panel-title">Connection</h3>
      <p className="edge-ends">
        <strong>{labels[edge.source] ?? edge.source}</strong> → <strong>{labels[edge.target] ?? edge.target}</strong>
      </p>
      <Field label="Label">
        <LazyInput value={edge.label ?? ""} placeholder="REST, publishes order.created…" onCommit={(l) => onPatch({ label: l || null })} />
      </Field>
      <Field label="Protocol">
        <select value={edge.protocol ?? ""} onChange={(e) => onPatch({ protocol: e.target.value || null })}>
          <option value="">—</option>
          {["http", "grpc", "tcp", "sql", "amqp", "kafka", "websocket"].map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </Field>
      <div className="row-buttons">
        <button className="btn block" onClick={onReverse}>
          <ArrowLeftRight size={14} /> Reverse
        </button>
        <button className="btn danger block" onClick={onDelete}>
          <Trash2 size={14} /> Delete
        </button>
      </div>
    </>
  );
}

function TableForm({
  table,
  tableNames,
  onPatch,
  onDelete,
}: {
  table: Table;
  tableNames: string[];
  onPatch: (t: Table) => void;
  onDelete: () => void;
}) {
  const setCol = (i: number, p: Partial<Column>) =>
    onPatch({ ...table, columns: table.columns.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  return (
    <>
      <h3 className="panel-title">Table</h3>
      <Field label="Name">
        <LazyInput value={table.name} onCommit={(name) => name.trim() && onPatch({ ...table, name: name.trim() })} />
      </Field>
      <div className="field-label cols-head">Columns</div>
      <div className="cols">
        {table.columns.map((c, i) => (
          <div className="col-row" key={i}>
            <div className="col-line">
              <LazyInput className="col-name" value={c.name} onCommit={(name) => setCol(i, { name })} />
              <select className="col-type" value={c.type} onChange={(e) => setCol(i, { type: e.target.value })}>
                {(COLUMN_TYPES.includes(c.type) ? COLUMN_TYPES : [c.type, ...COLUMN_TYPES]).map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              <button
                className={`icon-btn toggle${c.pk ? " on" : ""}`}
                title="Primary key"
                onClick={() => setCol(i, { pk: !c.pk })}
              >
                <KeyRound size={13} />
              </button>
              <button
                className="icon-btn"
                title="Remove column"
                onClick={() => onPatch({ ...table, columns: table.columns.filter((_, j) => j !== i) })}
              >
                <X size={13} />
              </button>
            </div>
            <div className="col-line sub">
              <select
                className="col-fk"
                value={c.fk?.split(".")[0] ?? ""}
                onChange={(e) => setCol(i, { fk: e.target.value ? `${e.target.value}.id` : null })}
                title="Foreign key"
              >
                <option value="">no FK</option>
                {tableNames
                  .filter((n) => n !== table.name)
                  .map((n) => (
                    <option key={n} value={n}>
                      FK → {n}
                    </option>
                  ))}
              </select>
              <label className="check">
                <input type="checkbox" checked={!c.nullable} onChange={(e) => setCol(i, { nullable: !e.target.checked })} />
                required
              </label>
              <label className="check">
                <input type="checkbox" checked={c.unique} onChange={(e) => setCol(i, { unique: e.target.checked })} />
                unique
              </label>
            </div>
          </div>
        ))}
      </div>
      <button
        className="btn block"
        onClick={() =>
          onPatch({
            ...table,
            columns: [...table.columns, { name: `column_${table.columns.length + 1}`, type: "String", pk: false, fk: null, nullable: true, unique: false }],
          })
        }
      >
        <Plus size={14} /> Add column
      </button>
      <button className="btn danger block" onClick={onDelete}>
        <Trash2 size={14} /> Delete table
      </button>
    </>
  );
}

function ProjectForm({
  summary,
  options,
  onOptions,
  useAgent,
  onUseAgent,
  warnings,
  error,
  agentMessage,
}: {
  summary: Summary | null;
  options: Options;
  onOptions: (o: Options) => void;
  useAgent: boolean;
  onUseAgent: (v: boolean) => void;
  warnings: string[];
  error: string | null;
  agentMessage: string | null;
}) {
  return (
    <>
      <h3 className="panel-title">Project</h3>
      {error && (
        <div className="callout bad">
          <AlertTriangle size={14} /> {error}
        </div>
      )}
      {summary ? (
        <div className="summary">
          <div className="summary-title">{summary.title}</div>
          <p>{summary.description}</p>
          {summary.data_flow && <p className="flow">{summary.data_flow}</p>}
          {Object.keys(summary.recommended_stack).length > 0 && (
            <dl className="stack">
              {Object.entries(summary.recommended_stack).map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ) : (
        <p className="hint">The architecture summary from the vision model appears here.</p>
      )}
      {agentMessage && <p className="agent-msg">“{agentMessage}”</p>}

      <h3 className="panel-title">Generate</h3>
      <Field label="Project name">
        <LazyInput
          value={options.project_name ?? ""}
          placeholder={summary?.title ?? "from summary"}
          onCommit={(v) => onOptions({ ...options, project_name: v.trim() || null })}
        />
      </Field>
      <Field label="License">
        <select value={options.license_type} onChange={(e) => onOptions({ ...options, license_type: e.target.value as Options["license_type"] })}>
          {LICENSES.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </Field>
      <Field label="Author">
        <LazyInput value={options.author} onCommit={(author) => onOptions({ ...options, author })} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={useAgent} onChange={(e) => onUseAgent(e.target.checked)} />
        Use the AI agent when regenerating (slower)
      </label>

      {warnings.length > 0 && (
        <>
          <h3 className="panel-title">Notes ({warnings.length})</h3>
          <ul className="warnings">
            {warnings.map((w) => (
              <li key={w}>
                <AlertTriangle size={12} /> {w}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

export function FormatPanel(props: {
  graph: Graph | null;
  selection: Selection;
  onGraph: (g: Graph) => void;
  onSelect: (s: Selection) => void;
  summary: Summary | null;
  options: Options;
  onOptions: (o: Options) => void;
  useAgent: boolean;
  onUseAgent: (v: boolean) => void;
  warnings: string[];
  error: string | null;
  agentMessage: string | null;
}) {
  const { graph, selection, onGraph, onSelect } = props;
  let body: ReactNode = null;

  if (graph && selection?.type === "node") {
    const node = graph.nodes.find((n) => n.id === selection.id);
    if (node)
      body = (
        <NodeForm
          node={node}
          onPatch={(p) => onGraph({ ...graph, nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, ...p } : n)) })}
          onDelete={() => {
            onGraph({
              ...graph,
              nodes: graph.nodes.filter((n) => n.id !== node.id),
              edges: graph.edges.filter((e) => e.source !== node.id && e.target !== node.id),
            });
            onSelect(null);
          }}
        />
      );
  } else if (graph && selection?.type === "edge") {
    const idx = graph.edges.findIndex((e) => `e:${e.source}->${e.target}` === selection.id);
    const edge = graph.edges[idx];
    if (edge) {
      const labels = Object.fromEntries(graph.nodes.map((n) => [n.id, n.label]));
      const replace = (next: GEdge | null) =>
        onGraph({ ...graph, edges: graph.edges.flatMap((e, i) => (i === idx ? (next ? [next] : []) : [e])) });
      body = (
        <EdgeForm
          edge={edge}
          labels={labels}
          onPatch={(p) => replace({ ...edge, ...p })}
          onReverse={() => {
            replace({ ...edge, source: edge.target, target: edge.source });
            onSelect({ type: "edge", id: `e:${edge.target}->${edge.source}` });
          }}
          onDelete={() => {
            replace(null);
            onSelect(null);
          }}
        />
      );
    }
  } else if (graph && selection?.type === "table") {
    const table = graph.tables.find((t) => tableId(t.name) === selection.id);
    if (table)
      body = (
        <TableForm
          table={table}
          tableNames={graph.tables.map((t) => t.name)}
          onPatch={(next) => {
            const renamed = next.name !== table.name;
            onGraph({
              ...graph,
              tables: graph.tables.map((t) => {
                if (t === table) return next;
                if (!renamed) return t;
                // keep FKs pointing at the renamed table
                return {
                  ...t,
                  columns: t.columns.map((c) =>
                    c.fk?.split(".")[0] === table.name ? { ...c, fk: `${next.name}.${c.fk.split(".")[1]}` } : c,
                  ),
                };
              }),
            });
            if (renamed) onSelect({ type: "table", id: tableId(next.name) });
          }}
          onDelete={() => {
            onGraph({ ...graph, tables: graph.tables.filter((t) => t !== table) });
            onSelect(null);
          }}
        />
      );
  }

  return (
    <aside className="sidebar right">
      <div className="format">
        {body ?? (
          <ProjectForm
            summary={props.summary}
            options={props.options}
            onOptions={props.onOptions}
            useAgent={props.useAgent}
            onUseAgent={props.onUseAgent}
            warnings={props.warnings}
            error={props.error}
            agentMessage={props.agentMessage}
          />
        )}
      </div>
    </aside>
  );
}
