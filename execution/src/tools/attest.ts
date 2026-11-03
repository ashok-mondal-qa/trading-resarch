import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { sourceHash, type Attestation } from "../config/liveGate.js";

/**
 * `npm run safety:attest` — runs the unit, integration (real PostgreSQL required) and end-to-end paper suites
 * and writes safety-attestation.json tied to a hash of src/ and db/. The live gate refuses LIVE_APPROVAL if any
 * suite failed or was skipped, or if the code changed since. Run it on the machine and commit you deploy.
 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

interface VitestJson {
  numTotalTests: number;
  numFailedTests: number;
  numPendingTests: number;
  numTodoTests: number;
  success: boolean;
}

function runSuite(name: string): Attestation["suites"][number] {
  const out = join(mkdtempSync(join(tmpdir(), "attest-")), `${name}.json`);
  const r = spawnSync("npx", ["vitest", "run", `test/${name}`, "--reporter=json", `--outputFile=${out}`], { cwd: ROOT, stdio: "inherit", env: process.env });
  let j: VitestJson;
  try {
    j = JSON.parse(readFileSync(out, "utf8")) as VitestJson;
  } catch {
    return { name, passed: false, tests: 0, failures: 1 };
  }
  const skipped = j.numPendingTests + j.numTodoTests;
  if (skipped > 0) console.error(`${name}: ${skipped} skipped tests (is TEST_DATABASE_URL set?)`);
  return { name, passed: r.status === 0 && j.success && skipped === 0, tests: j.numTotalTests - skipped, failures: j.numFailedTests + skipped };
}

if (!process.env.TEST_DATABASE_URL) {
  console.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database; the integration suite may not be skipped.");
  process.exit(1);
}
const suites = ["unit", "integration", "e2e"].map(runSuite);
const att: Attestation = { createdAt: new Date().toISOString(), sourceHash: sourceHash(ROOT), suites };
const path = process.env.SAFETY_ATTESTATION_PATH ?? join(ROOT, "safety-attestation.json");
writeFileSync(path, `${JSON.stringify(att, null, 2)}\n`);
const ok = suites.every((s) => s.passed);
console.log(`${ok ? "PASS" : "FAIL"}: attestation written to ${path}`);
process.exit(ok ? 0 : 1);
