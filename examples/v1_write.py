"""独立客户端：准备文档、保存预览、可恢复提交、查询及取消。默认模拟。"""

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx

TERMINAL = {"succeeded", "cancelled", "failed", "interrupted"}


def checked(response):
    if response.is_error:
        raise SystemExit(f"HTTP {response.status_code}: {response.text}")
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "document", nargs="?", type=Path, help="导出的 CanvasDocument v2 JSON"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--execute", action="store_true", help="明确请求实际书写；省略则模拟"
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("submission-receipt.json"),
        help="同一提交的本地凭证；重复运行找回同一任务",
    )
    parser.add_argument("--cancel", type=int, help="请求取消已有任务 ID，并查询到终态")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=30, trust_env=False) as client:
        if args.cancel:
            job = checked(client.post(f"/api/v1/jobs/{args.cancel}/cancel"))
        else:
            if args.receipt.exists():
                receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
                if receipt["url"] != args.url:
                    raise SystemExit(
                        "凭证属于其他服务，请使用对应 --url 或另一份 --receipt"
                    )
            else:
                if not args.document:
                    parser.error("首次提交需要文档文件")
                document = json.loads(args.document.read_text(encoding="utf-8"))
                plan = checked(client.post("/api/v1/plans", json=document))
                preview = client.get(plan["preview_url"])
                preview.raise_for_status()
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.with_suffix(".svg").write_text(
                    preview.text, encoding="utf-8"
                )
                if plan["status"] != "ready":
                    raise SystemExit(
                        json.dumps(plan["diagnostics"], ensure_ascii=False, indent=2)
                    )
                receipt = {
                    "url": args.url,
                    "key": str(uuid.uuid4()),
                    "body": {
                        "plan_id": plan["id"],
                        "mode": "execute" if args.execute else "simulate",
                    },
                }
                # 发请求之前落盘。超时或响应丢失后，原键、原请求找回原任务。
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(
                    json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            job = checked(
                client.post(
                    "/api/v1/jobs",
                    json=receipt["body"],
                    headers={"Idempotency-Key": receipt["key"]},
                )
            )
        print(json.dumps(job, ensure_ascii=False))
        while job["status"] not in TERMINAL:
            time.sleep(0.5)
            job = checked(client.get(f"/api/v1/jobs/{job['id']}"))
        print(json.dumps(job, ensure_ascii=False, indent=2))
        if job["status"] not in {"succeeded", "cancelled"}:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
