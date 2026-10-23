import dagre from "@dagrejs/dagre";
import type { GNode, Graph, NodeKind, Table } from "../types";

// draw.io's classic palette, one swatch per component kind.
export const KIND_STYLE: Record<NodeKind, { fill: string; stroke: string; label: string }> = {
  service: { fill: "#dae8fc", stroke: "#6c8ebf", label: "Service" },
  database: { fill: "#d5e8d4", stroke: "#82b366", label: "Database" },
  cache: { fill: "#f8cecc", stroke: "#b85450", label: "Cache" },
  queue: { fill: "#ffe6cc", stroke: "#d79b00", label: "Queue" },
  gateway: { fill: "#e1d5e7", stroke: "#9673a6", label: "Gateway" },
  frontend: { fill: "#fff2cc", stroke: "#d6b656", label: "Frontend" },
  external: { fill: "#f5f5f5", stroke: "#666666", label: "External" },
  unknown: { fill: "#ffffff", stroke: "#999999", label: "Unknown" },
};

export const NODE_W = 170;
export const NODE_H = 64;
export const TABLE_W = 220;

export const tableId = (name: string) => `table:${name}`;

export function tableHeight(t: Table): number {
  return 34 + Math.max(1, t.columns.length) * 24 + 6;
}

export function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "node"
  );
}

export function uniqueId(base: string, taken: Set<string>): string {
  let id = base;
  let i = 2;
  while (taken.has(id)) id = `${base}-${i++}`;
  return id;
}

export type Positions = Record<string, { x: number; y: number }>;

/** Left-to-right layout for components, tables in a row underneath. */
export function layoutGraph(graph: Graph): Positions {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  graph.edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  const pos: Positions = {};
  let maxY = 0;
  graph.nodes.forEach((n) => {
    const p = g.node(n.id);
    pos[n.id] = { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 };
    maxY = Math.max(maxY, p.y + NODE_H / 2);
  });

  // Tables get their own LR layout (referenced table left of the referencing one), below the components.
  if (graph.tables.length) {
    const tg = new dagre.graphlib.Graph();
    tg.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 70 });
    tg.setDefaultEdgeLabel(() => ({}));
    const names = new Set(graph.tables.map((t) => t.name));
    graph.tables.forEach((t) => tg.setNode(t.name, { width: TABLE_W, height: tableHeight(t) }));
    graph.tables.forEach((t) =>
      t.columns.forEach((c) => {
        const ref = c.fk?.split(".")[0];
        if (ref && ref !== t.name && names.has(ref)) tg.setEdge(ref, t.name);
      }),
    );
    dagre.layout(tg);
    const top = graph.nodes.length ? maxY + 80 : 40;
    let minTop = Infinity;
    graph.tables.forEach((t) => (minTop = Math.min(minTop, tg.node(t.name).y - tableHeight(t) / 2)));
    graph.tables.forEach((t) => {
      const p = tg.node(t.name);
      pos[tableId(t.name)] = { x: 40 + p.x - TABLE_W / 2, y: top + p.y - tableHeight(t) / 2 - minTop };
    });
  }
  return pos;
}

export function newNode(kind: NodeKind, taken: Set<string>): GNode {
  const label = `New ${kind}`;
  return { id: uniqueId(slugify(label), taken), label, kind, ports: [], tech: null };
}

export function newTable(taken: Set<string>): Table {
  const name = uniqueId("new_table", taken).replace(/-/g, "_");
  return {
    name,
    columns: [{ name: "id", type: "Int", pk: true, fk: null, nullable: false, unique: false }],
  };
}
