This directory stores the local source references used by the generic EDC adapter.

Current convention:

- `dashboard/`: local clone or synchronized working copy of `https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard`
- `dashboard/asset-filter-template/`: benchmark connector source used by the EDC adapter

Recommended workflow:

- Keep a prepared local working copy in `dashboard/` when working offline.
- The framework can synchronize the public upstream repository automatically when the default benchmark connector source is missing.
- If a local source directory is passed explicitly to `scripts/sync_sources.sh --source <path>`, the synchronization keeps the existing `build/` outputs so the adapter can reuse a previously built `connector.jar`.
- `scripts/build_image.sh --apply` builds the connector from `dashboard/asset-filter-template/final-connector`.
- `scripts/build_image.sh --apply --sync-source <path>` can synchronize from an explicit local source before the image build.
- `scripts/build_image.sh --apply` reuses `final-connector/build/libs/connector.jar` only when it is already present and still newer than its Gradle/runtime inputs.
- If the jar is missing or outdated, `scripts/build_image.sh --apply` rebuilds it through Gradle using a local `GRADLE_USER_HOME` inside `dashboard/asset-filter-template/`.
- `scripts/build_image.sh --apply --force-build` still forces a rebuild even when the existing jar looks up to date.
