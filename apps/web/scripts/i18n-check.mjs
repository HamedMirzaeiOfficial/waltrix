// Verifies the Persian dictionary covers every translatable string in the dashboard.
//
//   node scripts/i18n-check.mjs            fail if a t()/msg() string has no Persian entry
//   node scripts/i18n-check.mjs --report   also list JSX text and UI attributes not wrapped in t()
//   node scripts/i18n-check.mjs --missing  print missing keys as JSON (to start a translation)
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../src/", import.meta.url).pathname;
const DICT = join(ROOT, "locales/fa.json");

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

const fa = JSON.parse(readFileSync(DICT, "utf8"));
const problems = [];
for (const [key, value] of Object.entries(fa)) {
  // Every entry must actually be Persian; placeholders must survive translation.
  if (!/[؀-ۿ]/.test(value)) problems.push(`entry is not Persian: ${key}`);
  const want = [...key.matchAll(/\{(\w+)\}/g)]
    .map((m) => m[1])
    .sort()
    .join();
  const got = [...value.matchAll(/\{(\w+)\}/g)]
    .map((m) => m[1])
    .sort()
    .join();
  if (want !== got) problems.push(`placeholders differ: ${key}`);
}

const CALL = /\b(?:t|msg)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`$\\]*)`)/g;
const used = new Set();
const missing = [];
const loose = [];
for (const file of walk(ROOT)) {
  const rel = file.slice(ROOT.length);
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(CALL)) {
    const raw = match[1] ?? match[2]?.replace(/\\'/g, "'").replace(/"/g, '\\"') ?? match[3];
    const key = JSON.parse(`"${raw}"`);
    used.add(key);
    if (!(key in fa)) missing.push(`${rel}: ${key}`);
  }
  if (process.argv.includes("--report")) {
    text.split("\n").forEach((line, index) => {
      const jsx = />\s*([A-Za-z][A-Za-z ,.'’!?:;()-]*[A-Za-z.!?)])\s*(?:<|$)/.exec(line);
      const attr =
        /\b(?:label|title|placeholder|aria-label|hint|description|caption|header)=["']([^"']*[A-Za-z]{2}[^"']*)["']/.exec(
          line,
        );
      const hit = jsx?.[1] || attr?.[1];
      if (hit && !/^(?:[a-z]+(?:-[a-z]+)*|[A-Z_]+)$/.test(hit)) loose.push(`${rel}:${index + 1}: ${hit}`);
    });
  }
}

if (process.argv.includes("--missing")) {
  const keys = [...new Set(missing.map((m) => m.slice(m.indexOf(": ") + 2)))];
  console.log(JSON.stringify(Object.fromEntries(keys.map((k) => [k, ""])), null, 2));
  process.exit(0);
}

const unused = Object.keys(fa).filter((key) => !used.has(key));
if (loose.length) console.log(`Possibly untranslated (${loose.length}):\n  ${loose.join("\n  ")}`);
if (unused.length) console.log(`Unused Persian entries (${unused.length}):\n  ${unused.join("\n  ")}`);
if (problems.length || missing.length) {
  if (problems.length) console.error(`Dictionary problems (${problems.length}):\n  ${problems.join("\n  ")}`);
  if (missing.length) console.error(`Missing Persian translations (${missing.length}):\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log(`i18n: ${used.size} strings, all translated.`);
