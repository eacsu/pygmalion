"""Pygmalion 命令行入口。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

import typer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
app = typer.Typer(help="Pygmalion · 诗词自动书写", no_args_is_help=True)


@app.callback()
def entry():
    """Pygmalion · 诗词自动书写工作区。"""


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(envvar="PYGMALION_HOST", help="监听地址")
    ] = "0.0.0.0",
    port: Annotated[
        int, typer.Option(envvar="PYGMALION_PORT", min=1, max=65535, help="监听端口")
    ] = 8080,
    dry_run: Annotated[
        bool,
        typer.Option(
            envvar="PYGMALION_DRY_RUN", help="演练书写任务；手动控制仍操作真实设备"
        ),
    ] = False,
    api_only: Annotated[
        bool,
        typer.Option(envvar="PYGMALION_API_ONLY", help="只启动 API，不要求前端构建"),
    ] = False,
    fonts_dir: Annotated[
        Path | None,
        typer.Option(
            envvar="PYGMALION_FONTS_DIR",
            help="字体数据集父目录；相对路径基于运行数据根目录",
        ),
    ] = None,
    data_home: Annotated[
        Path | None,
        typer.Option(envvar="PYGMALION_HOME", help="配置、字库和运行数据根目录"),
    ] = None,
    tls_cert: Annotated[
        Path | None,
        typer.Option(envvar="PYGMALION_TLS_CERT", help="HTTPS 证书路径"),
    ] = None,
    tls_key: Annotated[
        Path | None,
        typer.Option(envvar="PYGMALION_TLS_KEY", help="HTTPS 私钥路径"),
    ] = None,
):
    """启动 Web 工作区。"""
    import uvicorn

    if (tls_cert is None) != (tls_key is None):
        raise typer.BadParameter("HTTPS 证书和私钥必须同时配置")
    for path in (tls_cert, tls_key):
        if path is not None and not path.is_file():
            raise typer.BadParameter(f"HTTPS 文件不存在：{path}")

    os.environ["PYGMALION_API_ONLY"] = "1" if api_only else "0"
    os.environ["PYGMALION_DRY_RUN"] = "1" if dry_run else "0"
    os.environ["PYGMALION_PORT"] = str(port)
    if data_home is not None:
        os.environ["PYGMALION_HOME"] = str(data_home.resolve())
    if fonts_dir is not None:
        os.environ["PYGMALION_FONTS_DIR"] = str(fonts_dir)
    logger.info(
        "%s：%s://%s:%s%s",
        "API" if api_only else "工作区",
        "https" if tls_cert else "http",
        host,
        port,
        "/docs" if api_only else "/",
    )
    uvicorn.run(
        "pygmalion.api.app:app",
        host=host,
        port=port,
        ssl_certfile=str(tls_cert) if tls_cert else None,
        ssl_keyfile=str(tls_key) if tls_key else None,
    )


@app.command()
def build_font(
    base: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="基础 train.parquet")
    ],
    output: Annotated[Path, typer.Option(help="新字体目录；必须尚不存在")],
):
    """离线扩充数字、字母、标点并生成 OpenCV 字样图。"""
    from ..fonts.build import build_font as generate

    try:
        report = generate(base, output)
    except (ValueError, OSError) as error:
        logger.error("字体生成失败：%s", error)
        raise typer.Exit(1) from error
    logger.info(
        "字体已生成：%s，原有 %s 字，新增 %s 字，共 %s 字",
        output,
        report["base_chars"],
        report["added_chars"],
        report["total_chars"],
    )


@app.command()
def import_stroke2font(
    source: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="上游行楷轨迹 JSON")
    ],
    license_file: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="上游完整 MIT LICENSE")
    ],
    output: Annotated[Path, typer.Option(help="新的 Parquet 字库目录")],
):
    """离线转换 Stroke2Font 分笔坐标，不操作机器或修改默认字体。"""
    from ..fonts.stroke2font import convert

    try:
        report = convert(source, license_file, output)
    except (ValueError, OSError) as error:
        logger.error("行楷导入失败：%s", error)
        raise typer.Exit(1) from error
    logger.info(
        "已导入 %s 个唯一字符；重复记录 %s 条：%s",
        report["characters"],
        len(report["duplicates"]),
        output,
    )


@app.command()
def convert_outline_font(
    source: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="OFL 轮廓字体文件")
    ],
    license_file: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="原字体完整 OFL 文件")
    ],
    output: Annotated[Path, typer.Option(help="新的实验字库目录")],
    characters: Annotated[
        str, typer.Option(help="限定字符；留空转换字体覆盖的汉字、西文和常用标点")
    ] = "",
    pixels: Annotated[int, typer.Option(min=96, max=512, help="栅格采样尺寸")] = 256,
    optimize: Annotated[
        bool, typer.Option(help="有限骨架回描、字内路径排序与简化")
    ] = False,
):
    """离线将 OFL 轮廓字形转为实验中心线；不操作设备，不恢复真实笔顺。"""
    from ..fonts.outline import convert_outline

    try:
        report = convert_outline(
            source, license_file, output, characters, pixels, optimize
        )
    except (ValueError, OSError) as error:
        logger.error("轮廓转换失败：%s", error)
        raise typer.Exit(1) from error
    logger.info(
        "中心线转换完成：%s 字形，跳过 %s 字符：%s",
        report["characters"],
        len(report["skipped"]),
        output,
    )


@app.command()
def export_openapi(output: Annotated[Path, typer.Option(help="OpenAPI JSON 输出文件")]):
    """离线导出公开契约，不初始化设备或数据库。"""
    import json

    from ..api.app import create_app

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            create_app(serve_frontend=False).openapi(), ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    app()
