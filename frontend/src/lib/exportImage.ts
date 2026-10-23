import { getNodesBounds, type Node } from "@xyflow/react";
import { toJpeg, toPng } from "html-to-image";

export type ImageFormat = "png" | "jpg";

/**
 * Render the whole diagram (not just the visible part) to an image file and download it.
 * Captures `.react-flow__viewport`, so the dot grid, minimap and controls are left out.
 */
export async function downloadDiagram(nodes: Node[], format: ImageFormat, filename: string): Promise<void> {
  const viewport = document.querySelector<HTMLElement>(".react-flow__viewport");
  if (!viewport || nodes.length === 0) throw new Error("Open the Diagram tab first");

  const bounds = getNodesBounds(nodes);
  const pad = 40;
  const width = Math.ceil(bounds.width + pad * 2);
  const height = Math.ceil(bounds.height + pad * 2);
  // Real size (zoom 1), shifted so the diagram's top-left sits at the padding.
  const x = pad - bounds.x;
  const y = pad - bounds.y;
  const zoom = 1;

  const options = {
    backgroundColor: "#ffffff",
    width,
    height,
    pixelRatio: 2,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${x}px, ${y}px) scale(${zoom})`,
    },
  };
  const dataUrl = format === "png" ? await toPng(viewport, options) : await toJpeg(viewport, { ...options, quality: 0.95 });

  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = `${filename}.${format}`;
  a.click();
}
