from __future__ import annotations

import shlex


def image_ref_from_values(values: dict | None, image_key: str = "image") -> str | None:
    image = (values or {}).get(image_key) or {}
    repository = str(image.get("repository") or "").strip()
    tag_raw = image.get("tag")
    tag = str(tag_raw).strip() if tag_raw is not None else ""
    if not repository or not tag:
        return None
    return f"{repository}:{tag}"


def nested_image_ref_from_values(values: dict | None, parent_key: str, image_key: str = "image") -> str | None:
    parent = (values or {}).get(parent_key) or {}
    return image_ref_from_values(parent, image_key=image_key)


def is_local_image_ref(image_ref: str | None) -> bool:
    return str(image_ref or "").strip().lower().endswith(":local")


def dedupe_image_refs(image_refs) -> list[str]:
    deduped = []
    seen = set()
    for raw_ref in list(image_refs or []):
        image_ref = str(raw_ref or "").strip()
        if not image_ref or image_ref in seen:
            continue
        seen.add(image_ref)
        deduped.append(image_ref)
    return deduped


def k3s_cri_image_ref_alias(image_ref: str) -> str:
    normalized = str(image_ref or "").strip()
    if not normalized:
        return ""
    has_path = "/" in normalized
    first_segment = normalized.split("/", 1)[0]
    if has_path and ("." in first_segment or ":" in first_segment or first_segment == "localhost"):
        return normalized
    if has_path:
        return f"docker.io/{normalized}"
    return f"docker.io/library/{normalized}"


def k3s_image_save_refs(image_ref: str) -> list[str]:
    image_ref = str(image_ref or "").strip()
    if not image_ref:
        return []
    save_refs = [image_ref]
    cri_alias = k3s_cri_image_ref_alias(image_ref)
    if cri_alias and cri_alias != image_ref:
        save_refs.append(cri_alias)
    return save_refs


def rendered_local_image_refs(raw_images) -> list[str]:
    refs = []
    for raw_image in str(raw_images or "").splitlines():
        image_ref = raw_image.strip().strip("'").strip('"')
        if is_local_image_ref(image_ref):
            refs.append(image_ref)
    return dedupe_image_refs(refs)


def docker_build_command(
    docker_cmd: str,
    image_ref: str,
    *,
    dockerfile: str | None = None,
    build_args: dict | None = None,
    context: str = ".",
) -> str:
    cmd = f"{shlex.quote(docker_cmd or 'docker')} build -t {shlex.quote(image_ref)}"
    for key, value in (build_args or {}).items():
        if value is None or str(value).strip() == "":
            continue
        cmd += f" --build-arg {shlex.quote(f'{key}={value}')}"
    if dockerfile:
        cmd += f" -f {shlex.quote(dockerfile)}"
    cmd += f" {shlex.quote(context or '.')}"
    return cmd
