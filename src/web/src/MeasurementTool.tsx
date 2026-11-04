import {
  useEffect,
  useRef,
  useState,
  type RefObject,
  type PointerEvent,
} from "react";

type Point = { x: number; y: number };
export function MeasurementTool({
  paper,
  scale,
  view,
  exit,
}: {
  paper: RefObject<HTMLDivElement | null>;
  scale: number;
  view: { x: number; y: number; width: number; height: number };
  exit: () => void;
}) {
  const host = useRef<SVGSVGElement>(null);
  const [points, setPoints] = useState<[Point, Point]>();
  const moving = useRef<0 | 1 | undefined>(undefined);
  useEffect(() => {
    host.current?.focus();
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !document.querySelector('dialog[open],[role="dialog"]')
      ) {
        event.preventDefault();
        event.stopPropagation();
        exit();
      }
    };
    document.addEventListener("keydown", escape, true);
    return () => document.removeEventListener("keydown", escape, true);
  }, [exit]);
  function point(event: PointerEvent<SVGSVGElement>): Point {
    const rect = paper.current!.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / scale,
      y: (event.clientY - rect.top) / scale,
    };
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    const index = moving.current;
    if (index === undefined || !points) return;
    const next = point(event),
      other = points[index === 0 ? 1 : 0];
    if (event.shiftKey) {
      if (Math.abs(next.x - other.x) >= Math.abs(next.y - other.y))
        next.y = other.y;
      else next.x = other.x;
    }
    setPoints(index === 0 ? [next, points[1]] : [points[0], next]);
  }
  const px = (p: Point) => ({
    x: view.x + p.x * scale,
    y: view.y + p.y * scale,
  });
  const a = points && px(points[0]),
    b = points && px(points[1]);
  const dx = points ? points[1].x - points[0].x : 0,
    dy = points ? points[1].y - points[0].y : 0;
  return (
    <svg
      ref={host}
      className="measurement-overlay"
      aria-label="两点测量"
      tabIndex={0}
      data-view-origin={`${view.x},${view.y}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          exit();
        }
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const target =
          event.target instanceof Element
            ? event.target.getAttribute("data-endpoint")
            : null;
        moving.current = target === "0" ? 0 : 1;
        if (target === null) {
          const p = point(event);
          setPoints([p, p]);
        }
        event.currentTarget.setPointerCapture(event.pointerId);
        event.currentTarget.focus();
      }}
      onPointerMove={move}
      onPointerUp={(event) => {
        move(event);
        moving.current = undefined;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        moving.current = undefined;
        setPoints(undefined);
      }}
    >
      <title>拖出两个端点测量；Shift 水平或垂直；Esc 清除并退出</title>
      {points && a && b ? (
        <>
          <path
            d={`M${a.x} ${a.y}L${b.x} ${b.y}`}
            className="measurement-line"
          />
          {[a, b].map((p, i) => (
            <g
              key={i}
              data-endpoint={i}
              aria-label={`测量端点 ${i + 1}`}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                const direction = {
                  ArrowLeft: [-1, 0],
                  ArrowRight: [1, 0],
                  ArrowUp: [0, -1],
                  ArrowDown: [0, 1],
                }[event.key];
                if (!direction) return;
                event.preventDefault();
                event.stopPropagation();
                const next = [...points] as [Point, Point];
                const step = event.shiftKey ? 0.1 : 1;
                next[i] = {
                  x: points[i].x + direction[0] * step,
                  y: points[i].y + direction[1] * step,
                };
                setPoints(next);
              }}
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={14}
                className="measurement-hit"
                data-endpoint={i}
              />
              <circle cx={p.x} cy={p.y} r={6} data-endpoint={i} />
            </g>
          ))}
          <text
            x={Math.max(
              Math.min(150, view.width / 2),
              Math.min(
                view.width - Math.min(150, view.width / 2),
                (a.x + b.x) / 2,
              ),
            )}
            y={Math.max(20, Math.min(a.y, b.y) - 12)}
            textAnchor="middle"
            role="status"
          >
            {Math.hypot(dx, dy).toFixed(2)} mm · 水平 {Math.abs(dx).toFixed(2)}{" "}
            · 垂直 {Math.abs(dy).toFixed(2)}
          </text>
        </>
      ) : (
        <text x={20} y={30}>
          拖动测量 · Shift 水平/垂直 · Esc 退出
        </text>
      )}
    </svg>
  );
}
