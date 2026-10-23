import type { NodeKind } from "../types";
import { KIND_STYLE } from "../lib/graph";

/** SVG outline for a component kind, drawn to fill a w x h box (draw.io-like shapes). */
export function ShapeSvg({
  kind,
  w,
  h,
  selected = false,
}: {
  kind: NodeKind;
  w: number;
  h: number;
  selected?: boolean;
}) {
  const { fill, stroke } = KIND_STYLE[kind];
  const sw = selected ? 2 : 1.3;
  const s = selected ? "var(--accent)" : stroke;
  const common = { fill, stroke: s, strokeWidth: sw };
  const i = sw; // inset so strokes are not clipped
  let shape: JSX.Element;

  switch (kind) {
    case "database":
    case "cache": {
      const ry = Math.min(10, h * 0.16);
      shape = (
        <>
          <path
            d={`M${i},${ry} A${w / 2 - i},${ry - i / 2} 0 0 1 ${w - i},${ry} V${h - ry} A${w / 2 - i},${ry - i / 2} 0 0 1 ${i},${h - ry} Z`}
            {...common}
          />
          <path d={`M${i},${ry} A${w / 2 - i},${ry - i / 2} 0 0 0 ${w - i},${ry}`} fill="none" stroke={s} strokeWidth={sw} />
        </>
      );
      break;
    }
    case "gateway": {
      const c = Math.min(18, w * 0.12);
      shape = (
        <polygon
          points={`${c},${i} ${w - c},${i} ${w - i},${h / 2} ${w - c},${h - i} ${c},${h - i} ${i},${h / 2}`}
          {...common}
        />
      );
      break;
    }
    case "queue": {
      const rx = Math.min(12, w * 0.08);
      shape = (
        <>
          <path
            d={`M${rx},${i} H${w - rx} A${rx - i},${h / 2 - i} 0 0 1 ${w - rx},${h - i} H${rx} A${rx - i},${h / 2 - i} 0 0 1 ${rx},${i} Z`}
            {...common}
          />
          <path d={`M${w - rx},${i} A${rx - i},${h / 2 - i} 0 0 0 ${w - rx},${h - i}`} fill="none" stroke={s} strokeWidth={sw} />
        </>
      );
      break;
    }
    case "frontend":
      shape = (
        <>
          <rect x={i} y={i} width={w - 2 * i} height={h - 2 * i} rx={4} {...common} />
          <line x1={i} y1={13} x2={w - i} y2={13} stroke={s} strokeWidth={sw} />
          {[8, 15, 22].map((cx) => (
            <circle key={cx} cx={cx} cy={7} r={2} fill={s} />
          ))}
        </>
      );
      break;
    case "external":
      shape = (
        <rect x={i} y={i} width={w - 2 * i} height={h - 2 * i} rx={h / 2} {...common} strokeDasharray="5 3" />
      );
      break;
    default:
      shape = <rect x={i} y={i} width={w - 2 * i} height={h - 2 * i} rx={6} {...common} />;
  }

  return (
    <svg className="shape-svg" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      {shape}
    </svg>
  );
}
