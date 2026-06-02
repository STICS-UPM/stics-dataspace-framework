from __future__ import annotations

import base64
import os


BRANDING_DEFAULT_ASSETS_DIR = "identity"
BRANDING_DEFAULT_CONNECTOR_ASSET_BASE_URL = "/inesdata-connector-interface/assets/branding"
BRANDING_DEFAULT_PORTAL_ASSET_BASE_URL = "/assets/branding"
BRANDING_MAX_TOTAL_ASSET_BYTES = 900 * 1024


class BrandingAssetsError(Exception):
    """Raised when INESData branding assets are invalid."""


def split_config_list(raw_value):
    return [
        item.strip()
        for item in str(raw_value or "").split(",")
        if item.strip()
    ]


def safe_branding_asset_filename(raw_name):
    name = str(raw_name or "").strip()
    if not name or name in {".", ".."}:
        raise BrandingAssetsError("Branding asset filename cannot be empty.")
    normalized = name.replace("\\", "/")
    if "/" in normalized or normalized != os.path.basename(normalized):
        raise BrandingAssetsError(
            f"Branding asset '{name}' must be a filename inside the configured identity directory."
        )
    return normalized


def branding_assets_dir(config, root_dir):
    raw_dir = str(config.get("INESDATA_BRAND_ASSETS_DIR") or BRANDING_DEFAULT_ASSETS_DIR).strip()
    if not raw_dir:
        raw_dir = BRANDING_DEFAULT_ASSETS_DIR
    root = os.path.abspath(root_dir)
    path = os.path.abspath(os.path.join(root, raw_dir))
    if not (path == root or path.startswith(root + os.sep)):
        raise BrandingAssetsError(
            "INESDATA_BRAND_ASSETS_DIR must point to a directory inside the repository."
        )
    return path


def branding_asset_url(base_url, filename):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return filename
    return f"{base}/{filename}"


def load_branding_assets(config, selected_files, root_dir):
    asset_dir = branding_assets_dir(config, root_dir)
    assets = []
    total_bytes = 0
    for raw_name in selected_files:
        filename = safe_branding_asset_filename(raw_name)
        path = os.path.abspath(os.path.join(asset_dir, filename))
        if not path.startswith(asset_dir + os.sep):
            raise BrandingAssetsError(
                f"Branding asset '{filename}' must stay inside {asset_dir}."
            )
        if not os.path.isfile(path):
            raise BrandingAssetsError(
                f"Branding asset '{filename}' was not found in {asset_dir}."
            )
        with open(path, "rb") as handle:
            payload = handle.read()
        total_bytes += len(payload)
        if total_bytes > BRANDING_MAX_TOTAL_ASSET_BYTES:
            raise BrandingAssetsError(
                "Selected branding assets exceed the safe ConfigMap payload size. "
                "Use smaller optimized logo files or fewer assets."
            )
        encoded = base64.b64encode(payload).decode("ascii")
        assets.append({"name": filename, "contentBase64": encoded})
    return assets


def inesdata_branding_template_keys(config, target):
    target_name = str(target or "").strip().lower()
    if target_name == "connector":
        base_url = str(
            config.get("INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL")
            or BRANDING_DEFAULT_CONNECTOR_ASSET_BASE_URL
        ).strip()
    elif target_name == "portal":
        base_url = str(
            config.get("INESDATA_BRAND_PORTAL_ASSET_BASE_URL")
            or BRANDING_DEFAULT_PORTAL_ASSET_BASE_URL
        ).strip()
    else:
        raise BrandingAssetsError(f"Unknown branding target: {target}")

    logo_files = split_config_list(config.get("INESDATA_BRAND_LOGO_FILES"))
    footer_logo_files = split_config_list(config.get("INESDATA_BRAND_FOOTER_LOGO_FILES"))
    powered_by_logo_files = split_config_list(config.get("INESDATA_BRAND_POWERED_BY_LOGO_FILES"))
    explicit_logo_urls = str(config.get("INESDATA_BRAND_LOGO_URLS") or "").strip()
    explicit_footer_logo_urls = str(config.get("INESDATA_BRAND_FOOTER_LOGO_URLS") or "").strip()
    explicit_powered_by_logo_urls = str(config.get("INESDATA_BRAND_POWERED_BY_LOGO_URLS") or "").strip()

    selected_files = []
    for filename in logo_files + footer_logo_files + powered_by_logo_files:
        safe_name = safe_branding_asset_filename(filename)
        if safe_name not in selected_files:
            selected_files.append(safe_name)

    logo_urls = explicit_logo_urls or ",".join(
        branding_asset_url(base_url, safe_branding_asset_filename(filename))
        for filename in logo_files
    )
    footer_logo_urls = explicit_footer_logo_urls or ",".join(
        branding_asset_url(base_url, safe_branding_asset_filename(filename))
        for filename in footer_logo_files
    )
    powered_by_logo_urls = explicit_powered_by_logo_urls or ",".join(
        branding_asset_url(base_url, safe_branding_asset_filename(filename))
        for filename in powered_by_logo_files
    )

    return {
        "inesdata_brand_asset_base_url": base_url,
        "inesdata_brand_show_menu_text": str(
            config.get("INESDATA_BRAND_SHOW_MENU_TEXT") or "true"
        ).strip(),
        "inesdata_brand_logo_files": ",".join(logo_files),
        "inesdata_brand_footer_logo_files": ",".join(footer_logo_files),
        "inesdata_brand_powered_by_logo_files": ",".join(powered_by_logo_files),
        "inesdata_brand_logo_urls": logo_urls,
        "inesdata_brand_footer_logo_urls": footer_logo_urls,
        "inesdata_brand_powered_by_logo_urls": powered_by_logo_urls,
        "inesdata_brand_asset_files": selected_files,
        "inesdata_brand_assets": [],
    }
