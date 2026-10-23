import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Graph, NodeKind, Selection } from "../types";
import { KIND_STYLE, layoutGraph, tableId, type Positions } from "../lib/graph";
import { nodeTypes } from "./FlowNodes";

export const DND_KIND = "application/x-d2r-kind";

interface Props {
  graph: Graph;
  /** Changes when a fresh server graph should be auto-laid-out. */
  layoutKey: number;
  /** False while another view covers the canvas: keyboard deletes are disabled. */
  active: boolean;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onChange: (g: Graph) => void;
  /** Add a component or table; returns the new flow-node id. */
  onAdd: (kind: NodeKind | "table") => string;
}

const edgeId = (s: string, t: string) => `e:${s}->${t}`;

export function DiagramCanvas({ graph, layoutKey, active, selection, onSelect, onChange, onAdd }: Props) {
  const rf = useReactFlow();
  const wrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const pending = useRef<Positions>({});
  const laidOut = useRef<number>(-1);
  const needsFit = useRef(false);
  const initialized = useNodesInitialized();

  const viewportCenter = useCallback(() => {
    const box = wrapper.current?.getBoundingClientRect();
    if (!box) return { x: 100, y: 100 };
    const p = rf.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
    return { x: p.x - 80 + Math.random() * 40, y: p.y - 30 + Math.random() * 40 };
  }, [rf]);

  // Rebuild flow nodes from the graph, keeping positions/measurements of existing ones.
  useEffect(() => {
    const fresh = laidOut.current !== layoutKey;
    const auto = fresh ? layoutGraph(graph) : {};
    laidOut.current = layoutKey;

    setNodes((prev) => {
      const prevById = new Map((fresh ? [] : prev).map((n) => [n.id, n]));
      const wanted = new Set([...graph.nodes.map((n) => n.id), ...graph.tables.map((t) => tableId(t.name))]);
      // A renamed table gets a new id; let it inherit the orphaned table's position.
      const orphanTables = (fresh ? [] : prev).filter((n) => n.type === "table" && !wanted.has(n.id));

      const place = (id: string, isTable: boolean) => {
        const old = prevById.get(id);
        if (old) return { position: old.position, measured: old.measured };
        if (isTable && orphanTables.length) {
          const o = orphanTables.shift()!;
          return { position: o.position, measured: o.measured };
        }
        const p = auto[id] ?? pending.current[id] ?? viewportCenter();
        delete pending.current[id];
        return { position: p };
      };

      return [
        ...graph.nodes.map((n) => ({
          id: n.id,
          type: "component",
          data: { node: n },
          ...place(n.id, false),
        })),
        ...graph.tables.map((t) => ({
          id: tableId(t.name),
          type: "table",
          data: { table: t },
          ...place(tableId(t.name), true),
        })),
      ];
    });
    if (fresh) needsFit.current = true;
  }, [graph, layoutKey, rf, viewportCenter]);

  // Fit only once React Flow has measured the freshly laid-out nodes.
  useEffect(() => {
    if (initialized && needsFit.current) {
      needsFit.current = false;
      requestAnimationFrame(() => rf.fitView({ padding: 0.15, duration: 250 }));
    }
  }, [initialized, nodes, rf]);

  const selectedNodes = useMemo(
    () => nodes.map((n) => ({ ...n, selected: selection?.id === n.id })),
    [nodes, selection],
  );

  const edges: Edge[] = useMemo(() => {
    const drawn = graph.edges.map((e) => {
      const id = edgeId(e.source, e.target);
      return {
        id,
        source: e.source,
        target: e.target,
        label: e.label ?? undefined,
        type: "smoothstep",
        selected: selection?.id === id,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#333" },
        style: { stroke: selection?.id === id ? "var(--accent)" : "#333", strokeWidth: 1.4 },
        labelBgPadding: [4, 2] as [number, number],
        labelStyle: { fontSize: 11 },
      };
    });
    const names = new Set(graph.tables.map((t) => t.name));
    const fks = graph.tables.flatMap((t) =>
      t.columns
        .filter((c) => c.fk && names.has(c.fk.split(".")[0]))
        .map((c) => ({
          // Drawn parent -> child so lines run left to right; the arrow sits on the referenced table.
          id: `fk:${t.name}.${c.name}`,
          source: tableId(c.fk!.split(".")[0]),
          target: tableId(t.name),
          type: "smoothstep",
          selectable: false,
          deletable: false,
          label: c.name,
          markerStart: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#82b366" },
          style: { stroke: "#82b366", strokeDasharray: "5 4" },
          labelStyle: { fontSize: 10, fill: "#4d7a3a" },
        })),
    );
    return [...drawn, ...fks];
  }, [graph, selection]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((ns) => applyNodeChanges(changes.filter((c) => c.type !== "select"), ns)),
    [],
  );

  // Selection lives in the parent (it drives the format panel), so React Flow's own
  // select changes are ignored above and clicks are mapped here instead.
  const selectNode = useCallback(
    (_: unknown, n: Node) => onSelect({ type: n.type === "table" ? "table" : "node", id: n.id }),
    [onSelect],
  );
  const selectEdge = useCallback(
    (_: unknown, e: Edge) => {
      if (e.id.startsWith("e:")) onSelect({ type: "edge", id: e.id });
    },
    [onSelect],
  );

  const onDelete = useCallback(
    ({ nodes: dn, edges: de }: { nodes: Node[]; edges: Edge[] }) => {
      const goneNodes = new Set(dn.map((n) => n.id));
      const goneEdges = new Set(de.map((e) => e.id));
      onChange({
        nodes: graph.nodes.filter((n) => !goneNodes.has(n.id)),
        edges: graph.edges.filter(
          (e) =>
            !goneEdges.has(edgeId(e.source, e.target)) && !goneNodes.has(e.source) && !goneNodes.has(e.target),
        ),
        tables: graph.tables.filter((t) => !goneNodes.has(tableId(t.name))),
      });
      onSelect(null);
    },
    [graph, onChange, onSelect],
  );

  const onConnect = useCallback(
    ({ source, target }: Connection) => {
      const isComponent = (id: string) => graph.nodes.some((n) => n.id === id);
      if (!source || !target || source === target || !isComponent(source) || !isComponent(target)) return;
      if (graph.edges.some((e) => e.source === source && e.target === target)) return;
      onChange({ ...graph, edges: [...graph.edges, { source, target, label: null, protocol: null }] });
      onSelect({ type: "edge", id: edgeId(source, target) });
    },
    [graph, onChange, onSelect],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      const kind = e.dataTransfer.getData(DND_KIND) as NodeKind | "table";
      if (!kind) return;
      e.preventDefault();
      const p = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      // Register the position under the id the parent will create.
      const id = onAdd(kind);
      pending.current[id] = { x: p.x - 80, y: p.y - 30 };
    },
    [onAdd, rf],
  );

  return (
    <div className="canvas" ref={wrapper} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <ReactFlow
        nodes={selectedNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={selectNode}
        onNodeDragStart={selectNode}
        onEdgeClick={selectEdge}
        onDelete={onDelete}
        onConnect={onConnect}
        onPaneClick={() => onSelect(null)}
        deleteKeyCode={active ? ["Backspace", "Delete"] : null}
        minZoom={0.2}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1.2} color="#c8ccd2" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) =>
            n.type === "table" ? "#dae8fc" : KIND_STYLE[(n.data as { node: { kind: NodeKind } }).node.kind].fill
          }
          nodeStrokeColor="#999"
        />
      </ReactFlow>
    </div>
  );
}
