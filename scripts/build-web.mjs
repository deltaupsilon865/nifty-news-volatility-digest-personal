// Vercel build step: copy the pipeline's JSON output into web/data and write an index of
// available digest dates. No dependencies; runs with plain Node.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const src = join(root, "data");
const out = join(root, "web", "data");

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "digests"), { recursive: true });

const digestDir = join(src, "digests");
const dates = existsSync(digestDir)
  ? readdirSync(digestDir).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).map((f) => f.slice(0, 10)).sort().reverse()
  : [];
for (const d of dates) cpSync(join(digestDir, `${d}.json`), join(out, "digests", `${d}.json`));
writeFileSync(join(out, "digests", "index.json"), JSON.stringify(dates));

for (const f of ["latest.json", "evaluation.csv"]) {
  if (existsSync(join(src, f))) cpSync(join(src, f), join(out, f));
}
console.log(`web/data ready: ${dates.length} digests${existsSync(join(src, "evaluation.csv")) ? " + evaluation.csv" : ""}`);
