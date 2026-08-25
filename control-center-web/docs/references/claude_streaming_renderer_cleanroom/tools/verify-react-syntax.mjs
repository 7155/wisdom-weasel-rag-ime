#!/usr/bin/env node
import { createRequire } from "node:module";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const root = path.resolve("src/react");
const names = (await readdir(root)).filter(
  (name) => name.endsWith(".ts") || name.endsWith(".tsx"),
);
let failures = 0;

for (const name of names) {
  const filename = path.join(root, name);
  const source = await readFile(filename, "utf8");
  const result = ts.transpileModule(source, {
    fileName: filename,
    reportDiagnostics: true,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.NodeNext,
      moduleResolution: ts.ModuleResolutionKind.NodeNext,
      jsx: ts.JsxEmit.ReactJSX,
      strict: true,
    },
  });
  for (const diagnostic of result.diagnostics ?? []) {
    if (diagnostic.category !== ts.DiagnosticCategory.Error) continue;
    failures += 1;
    console.error(
      `${name}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`,
    );
  }
}

if (failures > 0) process.exit(1);
console.log(`React/TSX syntax verified for ${names.length} files.`);
