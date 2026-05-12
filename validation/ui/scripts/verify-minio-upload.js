const fs = require("fs");
const path = require("path");
const { Client } = require("minio");

function requiredEnv(name) {
  const value = process.env[name];
  if (!value || value.trim().length === 0) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function asBool(value, defaultValue = false) {
  if (!value) {
    return defaultValue;
  }
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function walkFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(fullPath));
    } else {
      files.push(fullPath);
    }
  }

  return files;
}

function findLatestReport() {
  const root = process.cwd();
  const testResultsDir = path.join(root, "test-results");

  if (!fs.existsSync(testResultsDir)) {
    throw new Error(`Missing directory: ${testResultsDir}`);
  }

  const reportFiles = walkFiles(testResultsDir)
    .filter((file) => path.basename(file).startsWith("asset-upload-report-"))
    .filter((file) => file.endsWith(".json"));

  if (reportFiles.length === 0) {
    throw new Error("No asset-upload-report JSON file was found under test-results");
  }

  reportFiles.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return reportFiles[0];
}

async function main() {
  const reportPath = process.env.UPLOAD_REPORT_PATH || findLatestReport();
  const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));

  const endpoint = process.env.MINIO_ENDPOINT || "minio.dev.ed.dataspaceunit.upm";
  const port = Number.parseInt(process.env.MINIO_PORT || "80", 10);
  const useSSL = asBool(process.env.MINIO_USE_SSL, false);

  const accessKey = requiredEnv("MINIO_ACCESS_KEY");
  const secretKey = requiredEnv("MINIO_SECRET_KEY");
  const bucket = requiredEnv("MINIO_BUCKET");

  const client = new Client({
    endPoint: endpoint,
    port,
    useSSL,
    accessKey,
    secretKey,
  });

  const defaultObjectKey = `${process.env.PORTAL_TEST_OBJECT_PREFIX || "playwright-e2e"}/${path.basename(report.filePath || "")}`;
  const objectKey = process.env.MINIO_OBJECT_KEY || report.expectedObjectKey || defaultObjectKey;

  if (!objectKey || objectKey.endsWith("/")) {
    throw new Error(`Cannot determine uploaded object key from report: ${reportPath}`);
  }

  const expectedSize = Number.isFinite(report.expectedFileSizeBytes)
    ? report.expectedFileSizeBytes
    : Math.trunc((report.fileSizeMB || 0) * 1024 * 1024);

  if (!Number.isFinite(expectedSize) || expectedSize <= 0) {
    throw new Error("Report does not contain a valid expected file size");
  }

  const stat = await client.statObject(bucket, objectKey);

  if (stat.size !== expectedSize) {
    throw new Error(
      [
        "Object size mismatch detected",
        `- report: ${reportPath}`,
        `- bucket: ${bucket}`,
        `- object: ${objectKey}`,
        `- expected bytes: ${expectedSize}`,
        `- actual bytes: ${stat.size}`,
      ].join("\n")
    );
  }

  console.log(
    [
      "MinIO persistence check passed",
      `- report: ${reportPath}`,
      `- bucket: ${bucket}`,
      `- object: ${objectKey}`,
      `- size bytes: ${stat.size}`,
    ].join("\n")
  );
}

main().catch((error) => {
  const message = error && error.stack ? error.stack : String(error);
  console.error(message);
  process.exit(1);
});
