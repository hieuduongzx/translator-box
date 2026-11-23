#!/usr/bin/env node
// Đưa thành phần OCR (ONNX Runtime của Microsoft) lên R2 với key có phiên bản, KHÔNG ghi đè.
//
//   node packaging/upload-ocr-runtime.mjs --file <onnxruntime.dll> --key builds/translator2k/runtime/onnxruntime-1.24.4-directml/onnxruntime.dll
//
// - Dừng nếu key đã tồn tại (bất biến phiên bản).
// - In SHA-256 và cỡ file để ghim cứng vào src-tauri/src/ocr/ort_runtime.rs.
// - Sau khi tải lên, tải ngược từ địa chỉ công khai để đối chiếu SHA-256.
// Credentials R2 đọc từ biến môi trường hoặc file .env giống publish-release.mjs (không commit).
import { createHash, createHmac } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";

const DEFAULT_ENV_FILES = [
  "C:/Users/Amrita/.orca/secrets/2k-updater/r2.env",
  "K:/Web/Amri2k/.env.local",
];
const PUBLIC_BASE = "https://builds.amri2k.com";

function loadEnvFile(p) {
  if (!existsSync(p)) return;
  for (const raw of readFileSync(p, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const k = line.slice(0, eq).trim();
    let v = line.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    if (!process.env[k] && v) process.env[k] = v;
  }
}

const sha256Hex = (d) => createHash("sha256").update(d).digest("hex");
const hmac = (k, d) => createHmac("sha256", k).update(d).digest();
const enc = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());

function args() {
  const a = process.argv.slice(2);
  const out = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i] === "--file") out.file = a[++i];
    else if (a[i] === "--key") out.key = a[++i];
    else if (a[i] === "--dry-run") out.dryRun = true;
  }
  if (!out.file || !out.key) {
    console.error("Cách dùng: node upload-ocr-runtime.mjs --file <dll> --key <builds/.../file> [--dry-run]");
    process.exit(1);
  }
  if (!/^builds\/[a-z0-9-]+\/runtime\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(out.key)) {
    console.error("Key phải có dạng builds/<app>/runtime/<ten-phien-ban>/<file>.");
    process.exit(1);
  }
  return out;
}

async function r2(method, key, body = null, headers = {}) {
  const accountId = process.env.R2_ACCOUNT_ID?.trim();
  const accessKeyId = process.env.R2_ACCESS_KEY_ID?.trim();
  const secret = process.env.R2_SECRET_ACCESS_KEY?.trim();
  const bucket = process.env.R2_BUCKET?.trim() || "amri2k-builds";
  if (!accountId || !accessKeyId || !secret) throw new Error("Thiếu biến môi trường R2.");
  const host = `${accountId}.r2.cloudflarestorage.com`;
  const amzDate = new Date().toISOString().replace(/[:-]|\.\d{3}/g, "");
  const day = amzDate.slice(0, 8);
  const uri = `/${enc(bucket)}/${key.split("/").map(enc).join("/")}`;
  const payloadHash = body ? sha256Hex(body) : sha256Hex("");
  const signed = new Map([["host", host], ["x-amz-content-sha256", payloadHash], ["x-amz-date", amzDate]]);
  for (const [k, v] of Object.entries(headers)) signed.set(k.toLowerCase(), String(v));
  const names = [...signed.keys()].sort();
  const canonical = [method, uri, "", names.map((k) => `${k}:${signed.get(k)}\n`).join(""), names.join(";"), payloadHash].join("\n");
  const scope = `${day}/auto/s3/aws4_request`;
  const toSign = ["AWS4-HMAC-SHA256", amzDate, scope, sha256Hex(canonical)].join("\n");
  const kSign = hmac(hmac(hmac(hmac("AWS4" + secret, day), "auto"), "s3"), "aws4_request");
  const sig = createHmac("sha256", kSign).update(toSign).digest("hex");
  const h = { ...headers, "x-amz-content-sha256": payloadHash, "x-amz-date": amzDate,
    Authorization: `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${scope}, SignedHeaders=${names.join(";")}, Signature=${sig}` };
  return fetch(`https://${host}${uri}`, { method, headers: h, body: body ?? undefined });
}

async function main() {
  const a = args();
  for (const p of DEFAULT_ENV_FILES) loadEnvFile(p);
  const body = readFileSync(a.file);
  const sha = sha256Hex(body);
  console.log(`File:    ${a.file}\nCỡ:      ${statSync(a.file).size} byte\nSHA-256: ${sha}\nKey:     ${a.key}`);

  const head = await r2("HEAD", a.key);
  if (head.status === 200) {
    console.error("Key đã tồn tại trên R2 — dừng, không ghi đè. Hãy dùng key phiên bản mới.");
    process.exit(3);
  }
  if (head.status !== 404) throw new Error(`Không kiểm tra được key (HTTP ${head.status}).`);
  if (a.dryRun) return console.log("Dry-run: chưa tải lên.");

  const put = await r2("PUT", a.key, body, {
    "content-type": "application/octet-stream",
    "cache-control": "public, max-age=31536000, immutable",
  });
  if (!put.ok) throw new Error(`Tải lên thất bại (HTTP ${put.status}): ${await put.text()}`);

  const pub = await fetch(`${PUBLIC_BASE}/${a.key}`);
  const back = Buffer.from(await pub.arrayBuffer());
  if (!pub.ok || sha256Hex(back) !== sha) throw new Error("Tải ngược không khớp SHA-256.");
  console.log(`Đã tải lên và đối chiếu: ${PUBLIC_BASE}/${a.key}`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
