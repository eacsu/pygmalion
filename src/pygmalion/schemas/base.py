"""严格、有限数值的公共模型基类。"""

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Element(Model):
    id: str = Field(min_length=1, max_length=120)
    x_mm: float = 20
    y_mm: float = 20
    width_mm: float = Field(default=100, gt=0)
    height_mm: float = Field(default=50, gt=0)
