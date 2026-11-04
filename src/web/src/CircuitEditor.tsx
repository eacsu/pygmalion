import type { CircuitRender } from "./useCircuitRender";
import { useRef, useState, useLayoutEffect, type PointerEvent } from "react";
import { Button } from "./ui";
import { request } from "./api";
import { NumberField } from "./NumberField";
import {
  circuitNames,
  type CircuitComponent,
  type CircuitElement,
} from "./circuit";

export function CircuitHits({
  element,
  data,
  scale,
  selected,
  select,
  change,
  exit,
}: {
  element: CircuitElement;
  data?: CircuitRender;
  scale: number;
  selected?: string;
  select: (id: string) => void;
  change: (e: CircuitElement) => void;
  exit: () => void;
}) {
  const gesture = useRef<
    | {
        id: string;
        x: number;
        y: number;
        component: CircuitComponent;
        source: CircuitElement;
      }
    | undefined
  >(undefined);
  const [ghost, setGhost] = useState<{ id: string; dx: number; dy: number }>();
  function begin(
    event: PointerEvent<HTMLButtonElement>,
    component: CircuitComponent,
  ) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.focus();
    select(component.id);
    gesture.current = {
      id: component.id,
      x: event.clientX,
      y: event.clientY,
      component,
      source: element,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function finish(event: PointerEvent<HTMLButtonElement>) {
    const g = gesture.current;
    gesture.current = undefined;
    setGhost(undefined);
    if (!g) return;
    const dx = (event.clientX - g.x) / scale / element.scale,
      dy = (event.clientY - g.y) / scale / element.scale;
    if ((dx || dy) && g.source === element)
      change({
        ...element,
        circuit: {
          ...element.circuit,
          components: element.circuit.components.map((c) =>
            c.id === g.id ? { ...c, x_mm: c.x_mm + dx, y_mm: c.y_mm + dy } : c,
          ),
        },
      });
  }
  return (
    <div
      className="circuit-hits"
      role="group"
      aria-label="电路元件编辑"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          exit();
        }
      }}
    >
      {!data && <span className="circuit-loading">正在更新元件位置…</span>}
      <svg className="circuit-target" aria-hidden="true">
        {data?.layout.wires
          .filter((w) => w.id === selected)
          .map((w) => (
            <polyline
              key={w.id}
              points={w.points
                .map(
                  (p) =>
                    `${(p.x_mm - element.x_mm) * scale},${(p.y_mm - element.y_mm) * scale}`,
                )
                .join(" ")}
            />
          ))}
        {element.circuit.junctions
          .filter((j) => j.id === selected)
          .map((j) => (
            <circle
              key={j.id}
              cx={j.x_mm * element.scale * scale}
              cy={j.y_mm * element.scale * scale}
              r={8}
            />
          ))}
      </svg>
      {data?.layout.components.map((box) => {
        const component = element.circuit.components.find(
          (c) => c.id === box.id,
        )!;
        const dx = ghost?.id === box.id ? ghost.dx : 0,
          dy = ghost?.id === box.id ? ghost.dy : 0;
        return (
          <button
            key={box.id}
            className={
              "circuit-component-hit " + (selected === box.id ? "selected" : "")
            }
            aria-label={"电路元件 " + (component.reference || component.id)}
            aria-pressed={selected === box.id}
            style={{
              left: (box.x_mm - element.x_mm) * scale - 4 + dx,
              top: (box.y_mm - element.y_mm) * scale - 4 + dy,
              width: Math.max(20, box.width_mm * scale + 8),
              height: Math.max(20, box.height_mm * scale + 8),
            }}
            onClick={(event) => {
              event.stopPropagation();
              select(box.id);
            }}
            onPointerDown={(event) => begin(event, component)}
            onPointerMove={(event) => {
              const g = gesture.current;
              if (g)
                setGhost({
                  id: g.id,
                  dx: event.clientX - g.x,
                  dy: event.clientY - g.y,
                });
            }}
            onPointerUp={finish}
            onPointerCancel={() => {
              gesture.current = undefined;
              setGhost(undefined);
            }}
            onKeyDown={(event) => {
              const d = {
                ArrowUp: [0, -1],
                ArrowDown: [0, 1],
                ArrowLeft: [-1, 0],
                ArrowRight: [1, 0],
              }[event.key];
              if (!d) return;
              event.preventDefault();
              event.stopPropagation();
              change({
                ...element,
                circuit: {
                  ...element.circuit,
                  components: element.circuit.components.map((c) =>
                    c.id === box.id
                      ? { ...c, x_mm: c.x_mm + d[0], y_mm: c.y_mm + d[1] }
                      : c,
                  ),
                },
              });
            }}
          />
        );
      })}
    </div>
  );
}

export function CircuitInspector({
  element,
  editing,
  selected,
  data,
  error,
  retry,
  change,
  enter,
  exit,
  select,
  begin,
  end,
}: {
  element: CircuitElement;
  editing: boolean;
  selected?: string;
  data?: CircuitRender;
  error?: string;
  retry: () => void;
  change: (e: CircuitElement) => void;
  enter: () => void;
  exit: () => void;
  select: (id: string) => void;
  begin: (key: string) => void;
  end: () => void;
}) {
  const component = element.circuit.components.find((c) => c.id === selected);
  const [arranging, setArranging] = useState(false);
  const [layoutError, setLayoutError] = useState("");
  const latest = useRef<CircuitElement | undefined>(element);
  useLayoutEffect(() => {
    latest.current = element;
    return () => {
      latest.current = undefined;
    };
  }, [element]);
  async function arrange() {
    if (arranging) return;
    const source = element;
    setArranging(true);
    setLayoutError("");
    try {
      const result = await request<{ element: CircuitElement }>(
        "/api/v1/circuits/layout",
        "POST",
        source,
      );
      if (latest.current !== source) {
        setLayoutError("电路已变化，请重新自动排版。");
        return;
      }
      end();
      change(result.element);
    } catch (error) {
      setLayoutError(
        error instanceof Error ? error.message : "自动排版失败，请重试。",
      );
    } finally {
      setArranging(false);
    }
  }
  function patch(values: Partial<CircuitComponent>) {
    if (component)
      change({
        ...element,
        circuit: {
          ...element.circuit,
          components: element.circuit.components.map((c) =>
            c.id === component.id ? { ...c, ...values } : c,
          ),
        },
      });
  }
  return (
    <div className="circuit-inspector">
      <div className="property-heading">
        <h3>电路图</h3>
        <span>{element.circuit.components.length} 个元件</span>
      </div>
      <Button onClick={editing ? exit : enter}>
        {editing ? "退出电路编辑" : "编辑电路"}
      </Button>
      <Button onClick={() => void arrange()} disabled={arranging}>
        {arranging ? "正在自动排版…" : "自动排版"}
      </Button>
      <p className="muted">
        自动整理元件、连线与标注，适配当前尺寸；可撤销后继续微调。
      </p>
      {layoutError && <p role="alert">{layoutError}</p>}
      <label className="compact-field">
        <span>符号标准</span>
        <select
          aria-label="电路符号标准"
          value={element.circuit.standard}
          onChange={(event) =>
            change({
              ...element,
              circuit: {
                ...element.circuit,
                standard: event.target.value as "IEC" | "ANSI",
              },
            })
          }
        >
          <option>IEC</option>
          <option>ANSI</option>
        </select>
      </label>
      <NumberField
        label="电路标注字号"
        value={element.label_size_mm}
        min={1.5}
        max={12}
        change={(value) => change({ ...element, label_size_mm: value })}
      />
      {editing && (
        <>
          <label className="compact-field">
            <span>当前元件</span>
            <select
              aria-label="选择电路元件"
              value={selected ?? ""}
              onChange={(event) => select(event.target.value)}
            >
              <option value="">选择元件</option>
              {element.circuit.components.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.reference || c.id} · {circuitNames[c.kind]}
                </option>
              ))}
            </select>
          </label>
          {component && (
            <fieldset className="circuit-component-properties">
              <legend>{component.reference || component.id}</legend>
              {(["reference", "value", "label"] as const).map((key, i) => (
                <label className="compact-field" key={key}>
                  <span>{["编号", "参数", "说明"][i]}</span>
                  <input
                    aria-label={"元件" + ["编号", "参数", "说明"][i]}
                    value={component[key]}
                    maxLength={key === "reference" ? 40 : 120}
                    onFocus={() =>
                      begin(element.id + ":" + component.id + ":" + key)
                    }
                    onBlur={end}
                    onChange={(event) => patch({ [key]: event.target.value })}
                  />
                </label>
              ))}
              {component.kind === "chip" && (
                <div className="chip-pin-editor">
                  <p>引脚按每侧列表顺序排列；连线引用引脚名称。</p>
                  {(component.chip_pins ?? []).map((pin, index) => (
                    <div className="geometry-fields" key={index}>
                      <input aria-label={`引脚 ${index + 1} 名称`} value={pin.name} onChange={(event) => patch({ chip_pins: component.chip_pins?.map((p, i) => i === index ? { ...p, name: event.target.value } : p) })} />
                      <select aria-label={`引脚 ${index + 1} 方向`} value={pin.side} onChange={(event) => patch({ chip_pins: component.chip_pins?.map((p, i) => i === index ? { ...p, side: event.target.value as typeof p.side } : p) })}>
                        <option value="left">左</option><option value="right">右</option><option value="top">上</option><option value="bottom">下</option>
                      </select>
                      <input aria-label={`引脚 ${index + 1} 标注`} value={pin.label} onChange={(event) => patch({ chip_pins: component.chip_pins?.map((p, i) => i === index ? { ...p, label: event.target.value } : p) })} />
                    </div>
                  ))}
                  <Button onClick={() => patch({ chip_pins: [...(component.chip_pins ?? []), { name: `PIN${(component.chip_pins?.length ?? 0) + 1}`, side: "left", label: "" }] })}>添加引脚</Button>
                </div>
              )}
              <label className="compact-field">
                <span>方向</span>
                <select
                  aria-label="元件方向"
                  value={component.angle}
                  onChange={(event) =>
                    patch({
                      angle: Number(
                        event.target.value,
                      ) as CircuitComponent["angle"],
                    })
                  }
                >
                  {[0, 90, 180, 270].map((angle) => (
                    <option key={angle} value={angle}>
                      {angle}°
                    </option>
                  ))}
                </select>
              </label>
              <div className="geometry-fields">
                {(
                  [
                    "x_mm",
                    "y_mm",
                    "length_mm",
                    "label_dx_mm",
                    "label_dy_mm",
                  ] as const
                ).map((key, i) => (
                  <NumberField
                    key={key}
                    label={
                      [
                        "元件 X",
                        "元件 Y",
                        "元件长度",
                        "标注偏移 X",
                        "标注偏移 Y",
                      ][i]
                    }
                    value={component[key]}
                    min={
                      key === "length_mm"
                        ? 3
                        : key.startsWith("label")
                          ? -200
                          : -10000
                    }
                    max={
                      key === "length_mm" || key.startsWith("label")
                        ? 200
                        : 10000
                    }
                    change={(value) => patch({ [key]: value })}
                  />
                ))}
              </div>
            </fieldset>
          )}
          <p className="muted">
            拖动元件调整位置，导线端点随引脚移动。Esc 返回整体编辑。
          </p>
        </>
      )}
      {element.circuit.uncertainties.map((u, i) => (
        <div className="circuit-confirm" key={u.target_id + ":" + i}>
          <label>
            <input
              type="checkbox"
              aria-label={"已核对：" + u.message}
              checked={false}
              onChange={() =>
                change({
                  ...element,
                  circuit: {
                    ...element.circuit,
                    uncertainties: element.circuit.uncertainties.filter(
                      (_, index) => index !== i,
                    ),
                  },
                })
              }
            />
            待确认 · {u.message}
          </label>
          <Button
            kind="ghost"
            onClick={() => {
              enter();
              select(u.target_id);
            }}
            aria-label={"定位待确认项：" + u.message}
          >
            定位
          </Button>
        </div>
      ))}
      {error && (
        <div role="alert">
          {error}
          <Button onClick={retry}>重试电路预览</Button>
        </div>
      )}
      {data?.diagnostics.map((d, i) => (
        <button
          className={
            "circuit-diagnostic " +
            (d.severity === "error" ? "error-text" : "muted")
          }
          key={d.code + ":" + i}
          onClick={() => {
            enter();
            if (d.details.target_id) select(d.details.target_id);
          }}
        >
          {d.message}
        </button>
      ))}
      <Button
        disabled={!data}
        onClick={() => {
          if (!data) return;
          const url = URL.createObjectURL(
            new Blob([data.svg], { type: "image/svg+xml" }),
          );
          const a = document.createElement("a");
          a.href = url;
          a.download = element.name + ".svg";
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }}
      >
        导出电路 SVG
      </Button>
    </div>
  );
}
