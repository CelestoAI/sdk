import assert from "node:assert/strict";
import test from "node:test";

import type {
  ComputerExecResponse,
  ComputerExecStreamEvent,
  ExecParams,
} from "@celestoai/sdk";

import {
  createCelestoBashOperations,
  createCelestoReadOperations,
  createCelestoWriteOperations,
  shellQuote,
  toRemotePath,
  type RemoteComputer,
} from "../src/operations.js";

class FakeComputer implements RemoteComputer {
  commands: string[] = [];
  responses: ComputerExecResponse[] = [];
  events: ComputerExecStreamEvent[] = [];
  streamParams: ExecParams | undefined;

  async run(command: string): Promise<ComputerExecResponse> {
    this.commands.push(command);
    return (
      this.responses.shift() ?? {
        exitCode: 0,
        stdout: "",
        stderr: "",
      }
    );
  }

  async *runStream(
    command: string,
    params?: ExecParams,
  ): AsyncGenerator<ComputerExecStreamEvent> {
    this.commands.push(command);
    this.streamParams = params;
    for (const event of this.events) yield event;
  }
}

test("shellQuote protects single quotes", () => {
  assert.equal(shellQuote("it's safe"), `'it'"'"'s safe'`);
});

test("toRemotePath maps project paths and rejects escapes", () => {
  assert.equal(
    toRemotePath("/project/src/main.ts", "/project"),
    "/workspace/src/main.ts",
  );
  assert.equal(toRemotePath("/workspace/src/main.ts", "/project"), "/workspace/src/main.ts");
  assert.throws(
    () => toRemotePath("/project/../secret", "/project"),
    /must stay inside/,
  );
  assert.throws(
    () => toRemotePath("/workspace/../etc/passwd", "/project"),
    /must stay inside/,
  );
});

test("read and write operations transfer file contents as base64", async () => {
  const computer = new FakeComputer();
  computer.responses.push({
    exitCode: 0,
    stdout: Buffer.from("hello").toString("base64"),
    stderr: "",
  });

  const read = createCelestoReadOperations(computer, "/project");
  assert.equal((await read.readFile("/project/a.txt")).toString(), "hello");
  assert.match(computer.commands[0] ?? "", /\/workspace\/a\.txt/);

  const write = createCelestoWriteOperations(computer, "/project");
  await write.writeFile("/project/a.txt", "updated");
  const command = computer.commands[1] ?? "";
  assert.match(command, /mkdir -p/);
  assert.match(command, new RegExp(Buffer.from("updated").toString("base64")));
  assert.match(command, /mv/);
});

test("bash operations stream stdout and stderr and pass the abort signal", async () => {
  const computer = new FakeComputer();
  computer.events = [
    { type: "started", commandId: "cmd", startedAtUnixMs: 1, timeoutSeconds: 30 },
    { type: "stdout", data: "one" },
    { type: "stderr", data: "two" },
    { type: "exit", exitCode: 7 },
  ];
  const output: string[] = [];
  const controller = new AbortController();

  const result = await createCelestoBashOperations(computer, "/project").exec(
    "echo test",
    "/project/src",
    {
      onData: (data) => output.push(data.toString()),
      signal: controller.signal,
      timeout: 900,
    },
  );

  assert.deepEqual(output, ["one", "two"]);
  assert.deepEqual(result, { exitCode: 7 });
  assert.equal(computer.streamParams?.signal, controller.signal);
  assert.equal(computer.streamParams?.timeout, 300);
  assert.match(
    computer.commands[0] ?? "",
    /^cd '\/workspace\/src' && \{ env CELESTO_PI_COMMAND_ID='[^']+' setsid sh -c 'echo test'/,
  );
});

test("aborting bash explicitly terminates the remote process group", async () => {
  class AbortableComputer extends FakeComputer {
    override async *runStream(
      command: string,
      params?: ExecParams,
    ): AsyncGenerator<ComputerExecStreamEvent> {
      this.commands.push(command);
      this.streamParams = params;
      yield {
        type: "started",
        commandId: "long-command",
        startedAtUnixMs: 1,
        timeoutSeconds: 60,
      };
      await new Promise<never>((_resolve, reject) => {
        params?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      });
    }
  }

  const computer = new AbortableComputer();
  const controller = new AbortController();
  const execution = createCelestoBashOperations(computer, "/project").exec(
    "sleep 30",
    "/project",
    {
      onData: () => {},
      signal: controller.signal,
      timeout: 60,
    },
  );
  setTimeout(() => controller.abort(), 10);

  await assert.rejects(execution, /aborted/);
  assert.match(computer.commands[0] ?? "", /setsid sh -c 'sleep 30'/);
  assert.match(computer.commands[1] ?? "", /kill -TERM/);
  assert.match(computer.commands[1] ?? "", /pgid=/);
});
