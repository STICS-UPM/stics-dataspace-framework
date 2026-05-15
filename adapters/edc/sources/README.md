This directory stores the source references used by the generic EDC adapter.

Current convention:

- `connector/`: versioned EDC connector source used by the framework. It was imported from `asset-filter-template` in `https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard` with filtered history that keeps the connector source and removes generated build artifacts.
- `dashboard/`: optional local clone or synchronized working copy of `https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard`, used only when dashboard sources must be refreshed locally.

Recommended workflow:

- Keep `connector/` under version control so a fresh framework clone can build the generic EDC connector without cloning upstream sources first.
- Keep a prepared local working copy in `dashboard/` only when working on dashboard image sources.
- If a local source directory is passed explicitly to `scripts/sync_sources.sh --source <path>`, the synchronization copies the connector source and excludes generated build outputs.
- `scripts/build_image.sh --apply` builds the connector from `connector/final-connector`.
- `scripts/build_image.sh --apply --sync-source <path>` can synchronize from an explicit local source before the image build.
- `scripts/build_image.sh --apply` reuses `final-connector/build/libs/connector.jar` only when it is already present and still newer than its Gradle/runtime inputs.
- If the jar is missing or outdated, `scripts/build_image.sh --apply` rebuilds it through Gradle using a local `GRADLE_USER_HOME` inside `connector/`.
- `scripts/build_image.sh --apply --force-build` still forces a rebuild even when the existing jar looks up to date.
