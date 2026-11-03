"""生成或检查提交的 OpenAPI 和 TypeScript 类型；不启动应用生命周期。"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from pygmalion.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = (
        json.dumps(
            create_app(serve_frontend=False).openapi(), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "openapi.json"
        output = Path(directory) / "api.d.ts"
        source.write_text(schema, encoding="utf-8")
        subprocess.run(
            ["pnpm", "exec", "openapi-typescript", str(source), "-o", str(output)],
            cwd=ROOT / "src/web",
            check=True,
        )
        for target, content in [
            (ROOT / "src/web/openapi.json", schema),
            (
                ROOT / "src/web/src/generated/api.d.ts",
                output.read_text(encoding="utf-8"),
            ),
        ]:
            if args.check:
                if not target.exists() or target.read_text(encoding="utf-8") != content:
                    raise SystemExit(
                        f"契约已变化，请运行 pnpm --dir src/web api:types：{target.relative_to(ROOT)}"
                    )
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
