#!/usr/bin/env node

import { createRequire } from 'node:module';
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const webRoot = path.join(repositoryRoot, 'control-center-web');
const schemaRoot = path.join(repositoryRoot, 'rag_ime', 'contracts', 'json');
const contractsRoot = path.join(webRoot, 'src', 'contracts');
const generatedRoot = path.join(contractsRoot, 'generated');
const checkOnly = process.argv.includes('--check');
const requireFromWeb = createRequire(path.join(webRoot, 'package.json'));

let compile;
try {
  ({ compile } = requireFromWeb('json-schema-to-typescript'));
} catch (error) {
  console.error(
    'json-schema-to-typescript is unavailable. Run pnpm --dir control-center-web install --frozen-lockfile first.',
  );
  throw error;
}

const schemaFiles = (await readdir(schemaRoot))
  .filter((fileName) => fileName.endsWith('.json'))
  .sort((left, right) => left.localeCompare(right));

const artifacts = new Map();
const contractRows = [];
const schemaRows = [];

for (const fileName of schemaFiles) {
  const schemaName = fileName.slice(0, -'.json'.length);
  const typeName = toPascalCase(schemaName);
  const schema = JSON.parse(await readFile(path.join(schemaRoot, fileName), 'utf8'));
  // Most wire schemas intentionally use $id rather than title. Injecting a
  // title only into the compiler input keeps predictable public TS names
  // without modifying the source-of-truth JSON.
  const compiled = await compile({ ...schema, title: typeName }, typeName, {
    bannerComment: generatedBanner(fileName),
    format: true,
    style: {
      bracketSpacing: true,
      printWidth: 100,
      semi: true,
      singleQuote: true,
      tabWidth: 2,
      trailingComma: 'all',
    },
    unknownAny: true,
  });

  artifacts.set(path.join(generatedRoot, `${schemaName}.ts`), normalizeNewline(compiled));
  contractRows.push({ schemaName, typeName });
  schemaRows.push(
    `  ${JSON.stringify(schemaName)}: ${indent(JSON.stringify(schema, null, 2), 2)},`,
  );
}

artifacts.set(path.join(contractsRoot, 'generated.ts'), generatedIndex(contractRows));
artifacts.set(path.join(contractsRoot, 'schema-index.ts'), generatedSchemaIndex(schemaRows));

const expectedGeneratedFiles = new Set(
  [...artifacts.keys()]
    .filter((filePath) => filePath.startsWith(`${generatedRoot}${path.sep}`))
    .map((filePath) => path.basename(filePath)),
);

const drift = [];
for (const [filePath, expected] of artifacts) {
  let current = null;
  try {
    current = await readFile(filePath, 'utf8');
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  if (current !== expected) drift.push(path.relative(repositoryRoot, filePath));
}

try {
  const generatedFiles = await readdir(generatedRoot);
  for (const fileName of generatedFiles) {
    if (fileName.endsWith('.ts') && !expectedGeneratedFiles.has(fileName)) {
      drift.push(path.relative(repositoryRoot, path.join(generatedRoot, fileName)));
    }
  }
} catch (error) {
  if (error?.code !== 'ENOENT') throw error;
}

if (checkOnly) {
  if (drift.length > 0) {
    console.error(`Generated contracts are stale:\n${drift.map((item) => `- ${item}`).join('\n')}`);
    process.exitCode = 1;
  } else {
    console.log(`Generated contracts are reproducible (${schemaFiles.length} schemas).`);
  }
} else {
  await mkdir(generatedRoot, { recursive: true });
  for (const [filePath, contents] of artifacts) {
    await mkdir(path.dirname(filePath), { recursive: true });
    await writeFile(filePath, contents, 'utf8');
  }
  console.log(`Generated ${schemaFiles.length} TypeScript contracts and schema index.`);
}

function toPascalCase(value) {
  return value
    .split(/[^A-Za-z0-9]+/u)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join('');
}

function generatedBanner(sourceName) {
  return [
    '/* eslint-disable */',
    '/**',
    ' * This file is generated. Do not edit it by hand.',
    ` * Source: rag_ime/contracts/json/${sourceName}`,
    ' */',
  ].join('\n');
}

function generatedIndex(rows) {
  const imports = rows
    .map(
      ({ schemaName, typeName }) =>
        `import type { ${typeName} } from './generated/${schemaName}';`,
    )
    .join('\n');
  const exports = rows.map(({ typeName }) => `  ${typeName},`).join('\n');
  const mapRows = rows
    .map(({ schemaName, typeName }) => `  '${schemaName}': ${typeName};`)
    .join('\n');

  return normalizeNewline(`/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Run scripts/generate_control_center_contracts.mjs instead.
 */

${imports}

export type {
${exports}
};

export interface ContractTypeMap {
${mapRows}
}

export type GeneratedContractName = keyof ContractTypeMap;
`);
}

function generatedSchemaIndex(schemaRows) {
  return normalizeNewline(`/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * The values are byte-stable projections of rag_ime/contracts/json/*.json.
 */

export const contractSchemas = {
${schemaRows.join('\n')}
} as const;

export type ContractName = keyof typeof contractSchemas;

export const contractSchemaIds = Object.fromEntries(
  Object.entries(contractSchemas).map(([name, schema]) => [name, schema.$id]),
) as Record<ContractName, string>;
`);
}

function indent(value, spaces) {
  const prefix = ' '.repeat(spaces);
  return value.replaceAll('\n', `\n${prefix}`);
}

function normalizeNewline(value) {
  return `${value.trimEnd()}\n`;
}
