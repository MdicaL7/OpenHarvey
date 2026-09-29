# Reusing Memory outside OpenHarvey

Memory now has three boundaries. `memory_core` contains the preference rules and
record types. `contract_web/memory_repository.py` maps them to OpenHarvey's
existing SQLite table. `scripts/memory-plugin/tool.js` registers the OpenCode
tool and accepts a host-provided execution function.

## Python core

`MemoryService(repository)` exposes `list(scope_id)`, `snapshot(scope_id,
enabled)`, `create(scope_id, content, provenance)`, `update(scope_id, id,
expected_revision, content, provenance)`, and `delete(scope_id, id,
expected_revision)`. The authenticated host selects `scope_id`; model tool
arguments must not be trusted as an owner identity. `MemoryRepository` specifies
six storage methods: `list`, `get`, `used_chars`, `insert`, `replace`, and
`delete`. The package imports only Python's standard library.

The host must open a transaction before mutations and use the same connection
for authorization, capacity checks, memory writes, and any durable receipt.
OpenHarvey continues to use `BEGIN IMMEDIATE` with `SQLiteMemoryRepository` so
concurrent writes cannot pass a stale capacity or revision check. Existing
`personal_memories` rows and public API responses need no migration.

The core returns records and domain exceptions. A new host translates those
exceptions into its own API responses, manages enablement, and chooses how to
inject the snapshot into each Agent turn. OpenHarvey keeps its current full
snapshot prompt, execution-scoped capability, HTTP/E2B transports, idempotent
receipts, and verified UI citations in the host adapter.

## OpenCode tool

`createMemoryTool({execute, description})` in
`scripts/memory-plugin/tool.js` registers the same `memory` arguments and
returns the same receipt-shaped tool output. `execute(args, context)` is
provided by the host. The default plugin uses `openHarveyExecute`, which reads
`.memory-capability` and uses the existing HTTP or file-exchange transport.
A different OpenCode host can supply its own execution function without that
file or the OpenHarvey server. It must authenticate its caller, implement
storage and transaction handling, and supply relevant memories in Agent
context; loading the tool alone does not provide recall.

Start OpenCode without `--pure`: that flag suppresses configured external
plugins, including this tool. OpenHarvey's local and E2B launchers load only
their explicitly configured plugin files in isolated runtime directories.

Run `npm --prefix scripts/memory-plugin ci` and
`npm --prefix scripts/memory-plugin run build` after plugin source changes.
The generated `runtime/plugins/memory.js` is the bundled plugin loaded by
OpenCode 1.16.2 and has only the default OpenHarvey plugin export. A different
host imports the factory from `scripts/memory-plugin/tool.js` into its own
plugin entry point. OpenCode treats every export of a loaded plugin file as a
plugin function, so the factory must not be exported from the default bundle.
