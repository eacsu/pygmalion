import type { Geometry } from "./canvas";

export const circuitKinds = [
  "resistor",
  "capacitor",
  "capacitor_polar",
  "inductor",
  "voltage_source",
  "current_source",
  "ac_source",
  "ground",
  "diode",
  "zener",
  "led",
  "npn",
  "pnp",
  "nmos",
  "pmos",
  "opamp",
  "switch",
  "chip",
] as const;
export const circuitNames: Record<(typeof circuitKinds)[number], string> = {
  resistor: "电阻",
  capacitor: "电容",
  capacitor_polar: "有极性电容",
  inductor: "电感",
  voltage_source: "直流电压源",
  current_source: "电流源",
  ac_source: "交流电源",
  ground: "接地",
  diode: "二极管",
  zener: "稳压二极管",
  led: "发光二极管",
  npn: "NPN 三极管",
  pnp: "PNP 三极管",
  nmos: "N 沟道 MOS 管",
  pmos: "P 沟道 MOS 管",
  opamp: "运算放大器",
  switch: "开关",
  chip: "多引脚芯片",
};
export interface ChipPin {
  name: string;
  side: "left" | "right" | "top" | "bottom";
  label: string;
}
export interface CircuitComponent {
  id: string;
  kind: (typeof circuitKinds)[number];
  reference: string;
  value: string;
  label: string;
  x_mm: number;
  y_mm: number;
  angle: 0 | 90 | 180 | 270;
  length_mm: number;
  label_dx_mm: number;
  label_dy_mm: number;
  chip_pins?: ChipPin[];
}
export interface Endpoint {
  component_id: string | null;
  pin: string | null;
  junction_id: string | null;
}
export interface CircuitElement extends Geometry {
  type: "circuit";
  name: string;
  scale: number;
  font: string;
  label_size_mm: number;
  circuit: {
    standard: "IEC" | "ANSI";
    components: CircuitComponent[];
    junctions: { id: string; x_mm: number; y_mm: number; label: string }[];
    wires: {
      id: string;
      start: Endpoint;
      end: Endpoint;
      waypoints: { x_mm: number; y_mm: number }[];
      first_axis: "horizontal" | "vertical";
    }[];
    uncertainties: { target_id: string; message: string }[];
  };
}
/** 文件导入先校验结构；符号引脚和电路诊断由服务端再次校核。 */
export function validateCircuit(e: CircuitElement) {
  const finite = (v: unknown, min: number, max: number) =>
    typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
  const text = (v: unknown, max: number) =>
    typeof v === "string" && v.length <= max;
  const bad = () => {
    throw new Error("电路图结构或元件参数不正确");
  };
  if (
    !text(e.name, 120) ||
    !finite(e.scale, 0.05, 20) ||
    !text(e.font, 240) ||
    !finite(e.label_size_mm, 1.5, 12) ||
    !e.circuit ||
    !["IEC", "ANSI"].includes(e.circuit.standard)
  )
    bad();
  const s = e.circuit;
  if (
    !Array.isArray(s.components) ||
    !s.components.length ||
    s.components.length > 100 ||
    !Array.isArray(s.junctions) ||
    s.junctions.length > 100 ||
    !Array.isArray(s.wires) ||
    s.wires.length > 300 ||
    !Array.isArray(s.uncertainties) ||
    s.uncertainties.length > 100
  )
    bad();
  const ids = new Set<string>();
  for (const o of [...s.components, ...s.junctions, ...s.wires]) {
    if (!o || !text(o.id, 120) || !o.id || ids.has(o.id)) bad();
    ids.add(o.id);
  }
  for (const c of s.components) {
    if (
      !circuitKinds.includes(c.kind) ||
      !finite(c.x_mm, -10000, 10000) ||
      !finite(c.y_mm, -10000, 10000) ||
      ![0, 90, 180, 270].includes(c.angle) ||
      !finite(c.length_mm, 3, 200) ||
      !text(c.reference, 40) ||
      !text(c.value, 120) ||
      !text(c.label, 120) ||
      !finite(c.label_dx_mm, -200, 200) ||
      !finite(c.label_dy_mm, -200, 200)
      || (c.kind === "chip" && (!Array.isArray(c.chip_pins) || !c.chip_pins.length))
      || (c.chip_pins != null && (!Array.isArray(c.chip_pins) || c.chip_pins.length > 40 || c.chip_pins.some((p) => !text(p.name, 40) || !p.name || !text(p.label, 40) || !["left", "right", "top", "bottom"].includes(p.side)) || new Set(c.chip_pins.map((p) => p.name)).size !== c.chip_pins.length))
    )
      bad();
  }
  for (const j of s.junctions)
    if (
      !finite(j.x_mm, -10000, 10000) ||
      !finite(j.y_mm, -10000, 10000) ||
      !text(j.label, 120)
    )
      bad();
  for (const w of s.wires) {
    if (
      !["horizontal", "vertical"].includes(w.first_axis) ||
      !Array.isArray(w.waypoints) ||
      w.waypoints.length > 30 ||
      w.waypoints.some(
        (p) => !finite(p.x_mm, -10000, 10000) || !finite(p.y_mm, -10000, 10000),
      )
    )
      bad();
    for (const p of [w.start, w.end]) {
      if (
        !p ||
        (p.junction_id
          ? p.component_id != null ||
            p.pin != null ||
            !s.junctions.some((j) => j.id === p.junction_id)
          : !text(p.pin, 120) ||
            !p.pin ||
            !s.components.some((c) => c.id === p.component_id))
      )
        bad();
    }
  }
  for (const u of s.uncertainties)
    if (!ids.has(u.target_id) || !text(u.message, 500) || !u.message) bad();
}
