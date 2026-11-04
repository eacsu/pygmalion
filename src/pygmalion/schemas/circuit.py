"""可编辑电路结构；不保存派生的 SVG 或笔迹。"""

from typing import Literal

from pydantic import Field, model_validator

from .base import Element, Model

Symbol = Literal[
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
]


class Point(Model):
    x_mm: float = Field(ge=-10000, le=10000)
    y_mm: float = Field(ge=-10000, le=10000)


class ChipPin(Model):
    name: str = Field(min_length=1, max_length=40)
    side: Literal["left", "right", "top", "bottom"]
    label: str = Field(default="", max_length=40)


class Component(Point):
    id: str = Field(min_length=1, max_length=120)
    kind: Symbol
    reference: str = Field(default="", max_length=40)
    value: str = Field(default="", max_length=120)
    label: str = Field(default="", max_length=120)
    angle: Literal[0, 90, 180, 270] = 0
    length_mm: float = Field(default=15, ge=3, le=200)
    label_dx_mm: float = Field(default=0, ge=-200, le=200)
    label_dy_mm: float = Field(default=-5, ge=-200, le=200)
    chip_pins: list[ChipPin] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def valid_chip_pins(self):
        names = [p.name for p in self.chip_pins]
        if len(names) != len(set(names)):
            raise ValueError("芯片引脚名称不能重复")
        if self.kind == "chip" and not names:
            raise ValueError("多引脚芯片至少需要一个引脚")
        if self.kind != "chip" and names:
            raise ValueError("仅多引脚芯片可以定义引脚")
        return self


class Junction(Point):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)


class Endpoint(Model):
    component_id: str | None = None
    pin: str | None = None
    junction_id: str | None = None

    @model_validator(mode="after")
    def valid_endpoint(self):
        if bool(self.component_id and self.pin) == bool(self.junction_id):
            raise ValueError("端点必须指定元件和引脚，或连接点 ID")
        if self.junction_id and (self.component_id is not None or self.pin is not None):
            raise ValueError("连接点不能同时指定元件引脚")
        return self


class Wire(Model):
    id: str = Field(min_length=1, max_length=120)
    start: Endpoint
    end: Endpoint
    waypoints: list[Point] = Field(default_factory=list, max_length=30)
    first_axis: Literal["horizontal", "vertical"] = "horizontal"


class Uncertainty(Model):
    target_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class CircuitSpec(Model):
    standard: Literal["IEC", "ANSI"] = "IEC"
    components: list[Component] = Field(min_length=1, max_length=100)
    junctions: list[Junction] = Field(default_factory=list, max_length=100)
    wires: list[Wire] = Field(default_factory=list, max_length=300)
    uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        objects = [*self.components, *self.junctions, *self.wires]
        ids = [item.id for item in objects]
        if len(set(ids)) != len(ids):
            raise ValueError("电路元件、连接点和导线 ID 不能重复")
        components = {c.id for c in self.components}
        junctions = {j.id for j in self.junctions}
        for wire in self.wires:
            for point in (wire.start, wire.end):
                if point.component_id and point.component_id not in components:
                    raise ValueError("导线引用了不存在的元件")
                if point.junction_id and point.junction_id not in junctions:
                    raise ValueError("导线引用了不存在的连接点")
        if any(u.target_id not in ids for u in self.uncertainties):
            raise ValueError("待确认项引用了不存在的电路对象")
        return self


class CircuitElement(Element):
    type: Literal["circuit"] = "circuit"
    name: str = Field(default="电路图", max_length=120)
    width_mm: float = Field(default=120, gt=0)
    height_mm: float = Field(default=80, gt=0)
    scale: float = Field(default=1, ge=0.05, le=20)
    font: str = Field(default="", max_length=240)
    label_size_mm: float = Field(default=3, ge=1.5, le=12)
    circuit: CircuitSpec
