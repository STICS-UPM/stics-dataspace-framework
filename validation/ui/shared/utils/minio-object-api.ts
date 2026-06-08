import { createHash, createHmac } from "crypto";

import { MinioBucketTarget } from "./minio-console-runtime";

type MinioObjectStat = {
  objectName: string;
  bucketName: string;
  status: number;
  size?: number;
  etag?: string;
  lastModified?: string;
};

function hashHex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function hmac(key: Buffer | string, value: string): Buffer {
  return createHmac("sha256", key).update(value, "utf8").digest();
}

function awsDate(now: Date): { shortDate: string; timestamp: string } {
  const timestamp = now.toISOString().replace(/[:-]|\.\d{3}/g, "");
  return {
    shortDate: timestamp.slice(0, 8),
    timestamp,
  };
}

function encodeS3PathPart(value: string): string {
  return encodeURIComponent(value).replace(/[!'()*]/g, (char) =>
    `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function objectPath(bucketApiUrl: string, objectName: string): URL {
  const baseUrl = new URL(bucketApiUrl.endsWith("/") ? bucketApiUrl : `${bucketApiUrl}/`);
  const encodedObject = objectName.split("/").map(encodeS3PathPart).join("/");
  return new URL(encodedObject, baseUrl);
}

function signingKey(secretKey: string, shortDate: string, region: string): Buffer {
  const dateKey = hmac(`AWS4${secretKey}`, shortDate);
  const regionKey = hmac(dateKey, region);
  const serviceKey = hmac(regionKey, "s3");
  return hmac(serviceKey, "aws4_request");
}

function signedHeadHeaders(target: MinioBucketTarget, url: URL, now = new Date()): Record<string, string> {
  const region = target.region || "us-east-1";
  const { shortDate, timestamp } = awsDate(now);
  const signedHeaders = "host;x-amz-content-sha256;x-amz-date";
  const payloadHash = "UNSIGNED-PAYLOAD";
  const canonicalHeaders = [
    `host:${url.host}`,
    `x-amz-content-sha256:${payloadHash}`,
    `x-amz-date:${timestamp}`,
    "",
  ].join("\n");
  const canonicalRequest = [
    "HEAD",
    url.pathname,
    url.searchParams.toString(),
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");
  const credentialScope = `${shortDate}/${region}/s3/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    timestamp,
    credentialScope,
    hashHex(canonicalRequest),
  ].join("\n");
  const signature = createHmac("sha256", signingKey(target.credentials.password, shortDate, region))
    .update(stringToSign, "utf8")
    .digest("hex");

  return {
    Authorization: [
      `AWS4-HMAC-SHA256 Credential=${target.credentials.username}/${credentialScope}`,
      `SignedHeaders=${signedHeaders}`,
      `Signature=${signature}`,
    ].join(", "),
    "x-amz-content-sha256": payloadHash,
    "x-amz-date": timestamp,
  };
}

async function statMinioObject(target: MinioBucketTarget, objectName: string): Promise<MinioObjectStat | null> {
  const url = objectPath(target.bucketApiUrl, objectName);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(url, {
      method: "HEAD",
      headers: signedHeadHeaders(target, url),
      signal: controller.signal,
    });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      const statusText = response.statusText ? ` ${response.statusText}` : "";
      throw new Error(`MinIO HEAD ${url.href} returned HTTP ${response.status}${statusText}`);
    }
    const sizeHeader = response.headers.get("content-length");
    return {
      objectName,
      bucketName: target.bucketName,
      status: response.status,
      size: sizeHeader ? Number.parseInt(sizeHeader, 10) : undefined,
      etag: response.headers.get("etag")?.replace(/^"|"$/g, ""),
      lastModified: response.headers.get("last-modified") || undefined,
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function waitForMinioObjectStat(
  target: MinioBucketTarget,
  objectName: string,
  timeoutMs = 90_000,
): Promise<MinioObjectStat> {
  const startedAt = Date.now();
  let lastError = "";

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const stat = await statMinioObject(target, objectName);
      if (stat) {
        return stat;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }

  throw new Error(
    `MinIO object ${objectName} did not become available through S3 API within ${timeoutMs}ms` +
      (lastError ? `. Last issue: ${lastError}` : ""),
  );
}
