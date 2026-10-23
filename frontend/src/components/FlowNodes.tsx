import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { KeyRound, Link2 } from "lucide-react";
import { memo } from "react";
import type { GNode, Table } from "../types";
import { NODE_H, NODE_W, TABLE_W } from "../lib/graph";
import { ShapeSvg } from "./Shapes";

export type ComponentFlowNode = Node<{ node: GNode; port?: number }, "component">;
export type TableFlowNode = Node<{ table: Table }, "table">;

export const ComponentNode = memo(function ComponentNode({ data, selected }: NodeProps<ComponentFlowNode>) {
  const { node, port } = data;
  const shownPort = port ?? node.ports[0];
  const meta = [node.tech, shownPort ? `:${shownPort}` : null].filter(Boolean).join(" · ");
  return (
    <div className="cnode" style={{ width: NODE_W, height: NODE_H }}>
      <ShapeSvg kind={node.kind} w={NODE_W} h={NODE_H} selected={selected} />
      <Handle type="target" position={Position.Left} />
      <div className={`cnode-text kind-${node.kind}`}>
        <div className="cnode-label">{node.label}</div>
        {meta && <div className="cnode-meta">{meta}</div>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});

export const TableNode = memo(function TableNode({ data, selected }: NodeProps<TableFlowNode>) {
  const { table } = data;
  return (
    <div className={`tnode${selected ? " selected" : ""}`} style={{ width: TABLE_W }}>
      <Handle type="target" position={Position.Left} className="thandle" />
      <div className="tnode-head">{table.name}</div>
      {table.columns.map((c) => (
        <div className="tnode-row" key={c.name}>
          <span className="tnode-icon">
            {c.pk ? <KeyRound size={11} /> : c.fk ? <Link2 size={11} /> : null}
          </span>
          <span className={`tnode-col${c.pk ? " pk" : ""}`}>{c.name}</span>
          <span className="tnode-type">
            {c.type}
            {c.nullable || c.pk ? "" : "!"}
          </span>
        </div>
      ))}
      <Handle type="source" position={Position.Right} className="thandle" />
    </div>
  );
});

export const nodeTypes = { component: ComponentNode, table: TableNode };
