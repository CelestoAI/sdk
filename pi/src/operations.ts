import { randomUUID } from "node:crypto";
import path from "node:path";

import type {
  BashOperations,
  EditOperations,
  ReadOperations,
  WriteOperations,
} from "@earendil-works/pi-coding-agent";
import type {
  ComputerExecResponse,
  ComputerExecStreamEvent,
  ExecParams,
} from "@celestoai/sdk";

export const REMOTE_WORKSPACE = "/workspace";

export interface RemoteComputer {
  run(command: string, params?: ExecParams): Promise<ComputerExecResponse>;
  runStream(
    command: string,
    params?: ExecParams,
  ): AsyncGenerator<ComputerExecStreamEvent>;
}

export function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

export function toRemotePath(
  inputPath: string,
  localRoot: string,
  remoteRoot = REMOTE_WORKSPACE,
): string {
  const normalizedRemoteRoot = path.posix.resolve(remoteRoot);
  const asPosix = inputPath.replaceAll("\\", "/");

  if (
    asPosix === normalizedRemoteRoot ||
    asPosix.startsWith(`${normalizedRemoteRoot}/`)
  ) {
    const normalized = path.posix.resolve(asPosix);
    if (
      normalized !== normalizedRemoteRoot &&
      !normalized.startsWith(`${normalizedRemoteRoot}/`)
    ) {
      throw new Error(`Path must stay inside ${remoteRoot}.`);
    }
    return normalized;
  }

  const absoluteLocalRoot = path.resolve(localRoot);
  const absoluteInput = path.isAbsolute(inputPath)
    ? path.resolve(inputPath)
    : path.resolve(absoluteLocalRoot, inputPath);
  const relative = path.relative(absoluteLocalRoot, absoluteInput);
  if (
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error(`Path must stay inside ${localRoot}.`);
  }

  return relative
    ? path.posix.join(normalizedRemoteRoot, ...relative.split(path.sep))
    : normalizedRemoteRoot;
}

function commandError(
  action: string,
  response: ComputerExecResponse,
): Error {
  const detail = response.stderr.trim() || response.stdout.trim();
  return new Error(
    detail
      ? `${action} failed: ${detail}`
      : `${action} failed with exit code ${response.exitCode}.`,
  );
}

export async function execChecked(
  computer: RemoteComputer,
  command: string,
  action: string,
  params: ExecParams = {},
): Promise<ComputerExecResponse> {
  const response = await computer.run(command, params);
  if (response.exitCode !== 0) {
    throw commandError(action, response);
  }
  return response;
}

export async function readRemoteFile(
  computer: RemoteComputer,
  remotePath: string,
): Promise<Buffer> {
  const response = await execChecked(
    computer,
    `base64 < ${shellQuote(remotePath)} | tr -d '\\n'`,
    `Read ${remotePath}`,
  );
  const encoded = response.stdout.trim();
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw new Error(`Celesto returned invalid file data for ${remotePath}.`);
  }
  return Buffer.from(encoded, "base64");
}

export async function writeRemoteFile(
  computer: RemoteComputer,
  remotePath: string,
  content: Buffer | string,
): Promise<void> {
  const encoded = Buffer.isBuffer(content)
    ? content.toString("base64")
    : Buffer.from(content).toString("base64");
  const parent = path.posix.dirname(remotePath);
  const template = `${remotePath}.celesto.XXXXXX`;
  const command = [
    "set -eu",
    `mkdir -p ${shellQuote(parent)}`,
    `tmp=$(mktemp ${shellQuote(template)})`,
    `printf %s ${shellQuote(encoded)} | base64 -d > "$tmp"`,
    `mv "$tmp" ${shellQuote(remotePath)}`,
  ].join("; ");
  await execChecked(computer, command, `Write ${remotePath}`);
}

export async function removeRemotePath(
  computer: RemoteComputer,
  remotePath: string,
): Promise<void> {
  await execChecked(
    computer,
    `rm -f -- ${shellQuote(remotePath)}`,
    `Delete ${remotePath}`,
  );
}

function imageMimeType(filePath: string): string | null {
  switch (path.extname(filePath).toLowerCase()) {
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".png":
      return "image/png";
    case ".gif":
      return "image/gif";
    case ".webp":
      return "image/webp";
    default:
      return null;
  }
}

export function createCelestoReadOperations(
  computer: RemoteComputer,
  localRoot: string,
): ReadOperations {
  const remote = (input: string) => toRemotePath(input, localRoot);
  return {
    readFile: (input) => readRemoteFile(computer, remote(input)),
    access: async (input) => {
      const remotePath = remote(input);
      await execChecked(
        computer,
        `test -r ${shellQuote(remotePath)}`,
        `Open ${remotePath}`,
      );
    },
    detectImageMimeType: async (input) => imageMimeType(remote(input)),
  };
}

export function createCelestoWriteOperations(
  computer: RemoteComputer,
  localRoot: string,
): WriteOperations {
  const remote = (input: string) => toRemotePath(input, localRoot);
  return {
    writeFile: (input, content) =>
      writeRemoteFile(computer, remote(input), content),
    mkdir: async (input) => {
      const remotePath = remote(input);
      await execChecked(
        computer,
        `mkdir -p ${shellQuote(remotePath)}`,
        `Create ${remotePath}`,
      );
    },
  };
}

export function createCelestoEditOperations(
  computer: RemoteComputer,
  localRoot: string,
): EditOperations {
  const read = createCelestoReadOperations(computer, localRoot);
  const write = createCelestoWriteOperations(computer, localRoot);
  const remote = (input: string) => toRemotePath(input, localRoot);
  return {
    readFile: read.readFile,
    writeFile: write.writeFile,
    access: async (input) => {
      const remotePath = remote(input);
      await execChecked(
        computer,
        `test -r ${shellQuote(remotePath)} && test -w ${shellQuote(remotePath)}`,
        `Edit ${remotePath}`,
      );
    },
  };
}

async function terminateRemoteCommand(
  computer: RemoteComputer,
  pidFile: string,
): Promise<void> {
  const command = [
    "attempt=0",
    "while [ \"$attempt\" -lt 20 ]; do",
    `  if [ -r ${shellQuote(pidFile)} ]; then`,
    `    pid=$(cat ${shellQuote(pidFile)})`,
    "    case \"$pid\" in ''|*[!0-9]*) exit 0 ;; esac",
    "    pgid=$(ps -o pgid= -p \"$pid\" 2>/dev/null | tr -d ' ')",
    "    if [ \"$pgid\" = \"$pid\" ]; then",
    "      /bin/kill -TERM -- \"-$pid\" 2>/dev/null || true",
    "      sleep 0.2",
    "      /bin/kill -KILL -- \"-$pid\" 2>/dev/null || true",
    "    fi",
    `    rm -f -- ${shellQuote(pidFile)}`,
    "    exit 0",
    "  fi",
    "  attempt=$((attempt + 1))",
    "  sleep 0.05",
    "done",
  ].join("\n");
  await computer.run(command, { timeout: 10 });
}

export function createCelestoBashOperations(
  computer: RemoteComputer,
  localRoot: string,
): BashOperations {
  return {
    exec: async (command, cwd, { onData, signal, timeout }) => {
      const remoteCwd = toRemotePath(cwd, localRoot);
      const timeoutSeconds =
        timeout === undefined ? undefined : Math.max(1, Math.min(300, timeout));
      const token = randomUUID();
      const pidFile = `/tmp/celesto-pi-${token}.pid`;
      const childCommand = `env CELESTO_PI_COMMAND_ID=${shellQuote(token)} setsid sh -c ${shellQuote(command)}`;
      const commandBody = [
        `${childCommand} & child=$!`,
        `printf '%s\\n' \"$child\" > ${shellQuote(pidFile)}`,
        "wait \"$child\"",
        "status=$?",
        `rm -f -- ${shellQuote(pidFile)}`,
        "exit \"$status\"",
      ].join("; ");
      const remoteCommand = `cd ${shellQuote(remoteCwd)} && { ${commandBody}; }`;
      let exitCode: number | null = null;
      let cleanupPromise: Promise<void> | undefined;
      const cleanup = (): Promise<void> => {
        cleanupPromise ??= terminateRemoteCommand(computer, pidFile).catch(
          () => undefined,
        );
        return cleanupPromise;
      };
      const onAbort = (): void => {
        void cleanup();
      };
      signal?.addEventListener("abort", onAbort, { once: true });

      try {
        for await (const event of computer.runStream(remoteCommand, {
          signal,
          timeout: timeoutSeconds,
        })) {
          if (event.type === "stdout" || event.type === "stderr") {
            onData(Buffer.from(event.data));
          } else if (event.type === "exit") {
            exitCode = event.exitCode;
          }
        }
      } catch (error) {
        await cleanup();
        if (signal?.aborted) {
          throw new Error("aborted");
        }
        throw error;
      } finally {
        signal?.removeEventListener("abort", onAbort);
      }

      if (signal?.aborted) {
        await cleanup();
        throw new Error("aborted");
      }
      return { exitCode };
    },
  };
}
