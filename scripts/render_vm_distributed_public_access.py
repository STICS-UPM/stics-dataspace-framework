#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from deployers.shared.lib.vm_distributed_public_access import (  # noqa: E402
    build_vm_distributed_public_access_plan,
    load_vm_distributed_public_access_config,
    render_public_access_summary,
    render_role_http_entrypoint_nginx,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render vm-distributed public access artifacts from framework configuration."
    )
    parser.add_argument("--adapter", default="inesdata", help="Adapter config to use. Default: inesdata")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(ROOT_DIR, "context", "deliverables", "generated-public-access"),
        help="Output directory for rendered artifacts.",
    )
    args = parser.parse_args()

    config = load_vm_distributed_public_access_config(ROOT_DIR, adapter=args.adapter)
    plan = build_vm_distributed_public_access_plan(config)

    os.makedirs(args.out_dir, exist_ok=True)
    outputs = {
        "vm_distributed_public_access_plan.md": render_public_access_summary(plan),
        "pionera20_provider_http_entrypoint.conf": render_role_http_entrypoint_nginx(plan.provider),
        "pionera3_consumer_http_entrypoint.conf": render_role_http_entrypoint_nginx(plan.consumer),
    }
    for filename, content in outputs.items():
        path = os.path.join(args.out_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    print(f"Rendered {len(outputs)} vm-distributed public access artifacts in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
