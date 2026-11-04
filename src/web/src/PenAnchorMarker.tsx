import { useEffect, useRef, useState, type PointerEvent } from "react";

export type PenAnchor = { x_mm: number; y_mm: number };

export function PenAnchorMarker({
  anchor,
  bound = true,
  width,
  height,
  scale,
  selected,
  locked,
  select,
  change,
}: {
  anchor: PenAnchor;
  bound?: boolean;
  width: number;
  height: number;
  scale: number;
  selected: boolean;
  locked: boolean;
  select: () => void;
  change: (point: PenAnchor) => void;
}) {
  const button = useRef<HTMLButtonElement>(null);
  const gesture = useRef<
    | {
        id: number;
        x: number;
        y: number;
        scale: number;
        anchor: PenAnchor;
        next: PenAnchor;
      }
    | undefined
  >(undefined);
  const [draft, setDraft] = useState<PenAnchor>();
  const point = draft ?? anchor;
  // 笔尖朝右上方伸出，原点处的主体位于纸外，不能按尖端坐标选纸面墨色。
  const bodyInside =
    point.x_mm * scale + 9 >= 0 &&
    point.y_mm * scale - 9 >= 0 &&
    point.x_mm * scale + 9 <= width * scale &&
    point.y_mm * scale - 9 <= height * scale;
  function cancel() {
    const old = gesture.current;
    gesture.current = undefined;
    setDraft(undefined);
    if (old && button.current?.hasPointerCapture(old.id))
      button.current.releasePointerCapture(old.id);
  }
  useEffect(() => {
    const blur = () => cancel();
    window.addEventListener("blur", blur);
    return () => window.removeEventListener("blur", blur);
  }, []);
  const rounded = (x: number, y: number) => ({
    x_mm: Math.round(x * 100) / 100,
    y_mm: Math.round(y * 100) / 100,
  });
  function move(event: PointerEvent<HTMLButtonElement>) {
    const drag = gesture.current;
    if (!drag || drag.id !== event.pointerId || locked) return;
    drag.next = rounded(
      drag.anchor.x_mm + (event.clientX - drag.x) / drag.scale,
      drag.anchor.y_mm + (event.clientY - drag.y) / drag.scale,
    );
    setDraft(drag.next);
  }
  return (
    <button
      ref={button}
      type="button"
      className={`pen-anchor-marker${selected ? " selected" : ""}`}
      aria-label="笔头定位点"
      aria-pressed={selected}
      title={
        bound
          ? `笔头定位：X ${point.x_mm} / Y ${point.y_mm} mm；拖动不会移动机器`
          : "尚未绑定笔头；标记暂显示纸面原点，拖动或输入坐标设置定位"
      }
      disabled={locked}
      style={{
        left: point.x_mm * scale,
        top: point.y_mm * scale,
        color: bodyInside ? "var(--paper-ink)" : "var(--text)",
      }}
      onClick={(event) => {
        event.stopPropagation();
        select();
      }}
      onPointerDown={(event) => {
        if (locked || event.button !== 0 || gesture.current) return;
        event.preventDefault();
        event.stopPropagation();
        select();
        event.currentTarget.focus({ preventScroll: true });
        gesture.current = {
          id: event.pointerId,
          x: event.clientX,
          y: event.clientY,
          scale,
          anchor,
          next: anchor,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={move}
      onPointerUp={(event) => {
        const drag = gesture.current;
        if (!drag || drag.id !== event.pointerId) return;
        move(event);
        if (
          !locked &&
          (drag.next.x_mm !== anchor.x_mm || drag.next.y_mm !== anchor.y_mm)
        )
          change(drag.next);
        cancel();
      }}
      onPointerCancel={(event) => {
        if (gesture.current?.id === event.pointerId) cancel();
      }}
      onLostPointerCapture={cancel}
      onKeyDown={(event) => {
        const directions: Record<string, [number, number]> = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        };
        const delta = directions[event.key];
        if (locked || !delta) return;
        event.preventDefault();
        event.stopPropagation();
        const step = event.shiftKey ? 10 : event.altKey ? 0.1 : 1;
        change(
          rounded(anchor.x_mm + delta[0] * step, anchor.y_mm + delta[1] * step),
        );
      }}
    >
      <svg
        viewBox="0 0 32 32"
        width="32"
        height="32"
        aria-hidden="true"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <path
          fill={bodyInside ? "var(--paper-bg)" : "var(--background)"}
          d="M16 16 25-2 34 7ZM25-2 34 7M16 16 27 5"
        />
      </svg>
    </button>
  );
}
