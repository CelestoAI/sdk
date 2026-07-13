import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import type {
  ExtensionAPI,
  ExtensionContext,
  SessionStartEvent,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";

import celestoPiExtension, { assertSafeLocalRoot } from "../src/index.js";

test("push refuses filesystem and home directory roots", () => {
  assert.throws(
    () => assertSafeLocalRoot(path.parse(process.cwd()).root),
    /Refusing to copy/,
  );
  assert.throws(() => assertSafeLocalRoot(os.homedir()), /Refusing to copy/);
  assert.doesNotThrow(() =>
    assertSafeLocalRoot(path.join(os.tmpdir(), "celesto-project")),
  );
});

test("local tools use the session cwd without --celesto", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "celesto-extension-test-"));
  try {
    await writeFile(path.join(root, "hello.txt"), "hello from local\n");

    const flags = new Map<string, boolean | string | undefined>();
    const tools = new Map<string, ToolDefinition>();
    const handlers = new Map<
      string,
      Array<(event: unknown, ctx: ExtensionContext) => unknown>
    >();
    const commands = new Set<string>();
    const api = {
      registerFlag(name: string, options: { default?: boolean | string }) {
        flags.set(name, options.default);
      },
      getFlag(name: string) {
        return flags.get(name);
      },
      registerTool(tool: ToolDefinition) {
        tools.set(tool.name, tool);
      },
      registerCommand(name: string) {
        commands.add(name);
      },
      on(
        event: string,
        handler: (event: unknown, ctx: ExtensionContext) => unknown,
      ) {
        const existing = handlers.get(event) ?? [];
        existing.push(handler);
        handlers.set(event, existing);
      },
      appendEntry() {},
    } as unknown as ExtensionAPI;

    celestoPiExtension(api);
    const context = {
      cwd: root,
      sessionManager: { getBranch: () => [] },
      ui: {
        theme: { fg: (_color: string, value: string) => value },
        setStatus() {},
        notify() {},
      },
    } as unknown as ExtensionContext;
    for (const handler of handlers.get("session_start") ?? []) {
      await handler(
        { type: "session_start", reason: "startup" } satisfies SessionStartEvent,
        context,
      );
    }

    assert(flags.has("celesto"));
    assert(flags.has("celesto-computer"));
    assert(commands.has("celesto"));
    assert.deepEqual([...tools.keys()].sort(), ["bash", "edit", "read", "write"]);

    const result = await tools.get("read")?.execute(
      "call-1",
      { path: "hello.txt" },
      undefined,
      undefined,
      context,
    );
    assert.equal(result?.content[0]?.type, "text");
    assert.match(
      result?.content[0]?.type === "text" ? result.content[0].text : "",
      /hello from local/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
