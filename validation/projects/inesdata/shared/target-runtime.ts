import fs from "fs";

export type InesdataConnectorRuntime = {
  name?: string;
  role?: string;
  portal_url?: string;
  management_api_url?: string;
  protocol_url?: string;
};

export type InesdataDataspaceRuntime = {
  name?: string;
  public_portal_url?: string;
  connectors?: InesdataConnectorRuntime[];
};

export type InesdataTargetRuntime = {
  target?: string;
  project?: string;
  mode?: string;
  environment?: string;
  dataspaces?: InesdataDataspaceRuntime[];
};

function sanitizeEnvToken(value: string): string {
  return value
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function readTargetRuntime(): InesdataTargetRuntime {
  const runtimeFile = process.env.INESDATA_TARGET_RUNTIME_FILE;
  if (!runtimeFile) {
    throw new Error("Missing INESDATA_TARGET_RUNTIME_FILE");
  }
  return JSON.parse(fs.readFileSync(runtimeFile, "utf-8")) as InesdataTargetRuntime;
}

export function findDataspace(name: string, runtime = readTargetRuntime()): InesdataDataspaceRuntime {
  const dataspace = (runtime.dataspaces || []).find((item) => item.name === name);
  if (!dataspace) {
    throw new Error(`Target dataspace not found: ${name}`);
  }
  return dataspace;
}

export function portalUrlForDataspace(name: string, runtime = readTargetRuntime()): string {
  const envName = `INESDATA_${sanitizeEnvToken(name)}_PORTAL_URL`;
  const fromEnv = process.env[envName];
  if (fromEnv) {
    return fromEnv;
  }
  const fromRuntime = findDataspace(name, runtime).public_portal_url;
  if (!fromRuntime) {
    throw new Error(`Portal URL not configured for dataspace: ${name}`);
  }
  return fromRuntime;
}
