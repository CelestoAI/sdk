import { EventEmitter } from "node:events";
import WebSocket from "ws";

import { buildRequestContext, ClientConfig } from "../core/config";
import { OpenTerminalOptions } from "./types";

const toWsUrl = (baseUrl: string): string =>
  baseUrl.replace(/^https:/i, "wss:").replace(/^http:/i, "ws:");

/**
 * Interactive terminal session on a running computer.
 *
 * Emits:
 * - `"data"` with a string or `Buffer` for each chunk of server output
 * - `"close"` with `(code: number, reason: string)` when the session ends
 * - `"error"` with an `Error` on socket failures
 *
 * Call `write()` to send keystrokes, `resize()` to update the PTY size, and
 * `close()` to cleanly terminate the session.
 */
export class Terminal extends EventEmitter {
  readonly #ws: WebSocket;
  #closed = false;

  constructor(ws: WebSocket) {
    super();
    this.#ws = ws;

    ws.on("message", (raw, isBinary) => {
      if (isBinary) {
        this.emit("data", raw as Buffer);
      } else {
        this.emit("data", (raw as Buffer).toString("utf-8"));
      }
    });

    ws.on("close", (code, reason) => {
      this.#closed = true;
      this.emit("close", code, reason.toString("utf-8"));
    });

    ws.on("error", (err) => {
      this.emit("error", err);
    });
  }

  /** True once the underlying WebSocket has closed. */
  get closed(): boolean {
    return this.#closed;
  }

  /** Send raw keystrokes to the remote PTY. */
  write(data: string | Uint8Array): void {
    if (this.#closed) {
      throw new Error("Terminal is closed");
    }
    this.#ws.send(data);
  }

  /** Resize the remote PTY. Server expects `{ type: "resize", cols, rows }`. */
  resize(cols: number, rows: number): void {
    if (this.#closed) {
      throw new Error("Terminal is closed");
    }
    this.#ws.send(JSON.stringify({ type: "resize", cols, rows }));
  }

  /** Close the session. Resolves after the socket has fully closed. */
  close(code: number = 1000, reason?: string): Promise<void> {
    if (this.#closed) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const done = (): void => {
        this.#ws.removeListener("close", done);
        resolve();
      };
      this.#ws.once("close", done);
      this.#ws.close(code, reason);
    });
  }

  // Typed event overloads — keeps consumer callsites type-safe while letting
  // the underlying EventEmitter handle dispatch. The implementation signature
  // uses `any` to satisfy TypeScript's overload-compatibility check, matching
  // the pattern used in @types/node.
  on(event: "data", listener: (data: string | Buffer) => void): this;
  on(event: "close", listener: (code: number, reason: string) => void): this;
  on(event: "error", listener: (err: Error) => void): this;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on(event: string, listener: (...args: any[]) => void): this {
    return super.on(event, listener);
  }

  once(event: "data", listener: (data: string | Buffer) => void): this;
  once(event: "close", listener: (code: number, reason: string) => void): this;
  once(event: "error", listener: (err: Error) => void): this;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  once(event: string, listener: (...args: any[]) => void): this {
    return super.once(event, listener);
  }
}

/**
 * Open an interactive terminal WebSocket against a computer.
 *
 * Caller is responsible for passing a resolved computer ID (not a name) —
 * the WebSocket endpoint does not resolve names. The high-level
 * `ComputersClient.openTerminal()` handles resolution for you.
 */
export const openTerminalConnection = async (
  config: ClientConfig,
  resolvedComputerId: string,
  options?: OpenTerminalOptions,
): Promise<Terminal> => {
  const ctx = buildRequestContext(config);
  if (!ctx.token) {
    throw new Error("A token is required to open a terminal session");
  }

  const wsBase = toWsUrl(ctx.baseUrl);
  const fullUrl = `${wsBase}/v1/computers/${encodeURIComponent(resolvedComputerId)}/terminal`;

  const headers: Record<string, string> = {
    Authorization: `Bearer ${ctx.token}`,
  };
  if (ctx.organizationId) {
    headers["X-Current-Organization"] = ctx.organizationId;
  }

  const ws = new WebSocket(fullUrl, { headers });

  if (options?.signal) {
    const signal = options.signal;
    if (signal.aborted) {
      ws.terminate();
      throw new Error("Aborted before terminal connect");
    }
    const onAbort = (): void => {
      ws.terminate();
    };
    signal.addEventListener("abort", onAbort, { once: true });
    ws.once("close", () => signal.removeEventListener("abort", onAbort));
  }

  await new Promise<void>((resolve, reject) => {
    const cleanup = (): void => {
      ws.removeListener("open", onOpen);
      ws.removeListener("error", onError);
      ws.removeListener("close", onClose);
    };
    const onOpen = (): void => {
      cleanup();
      resolve();
    };
    const onError = (err: Error): void => {
      cleanup();
      reject(err);
    };
    const onClose = (code: number, reason: Buffer): void => {
      cleanup();
      reject(
        new Error(
          `Terminal WebSocket closed before open (code=${code}${
            reason.length ? ` reason=${reason.toString("utf-8")}` : ""
          })`,
        ),
      );
    };
    ws.once("open", onOpen);
    ws.once("error", onError);
    ws.once("close", onClose);
  });

  // Match the Python CLI: send the token as a first message too. Backend
  // currently authenticates via the Authorization header (see CLAUDE.md),
  // but sending both preserves compatibility with the legacy first-message
  // token pattern.
  ws.send(JSON.stringify({ token: ctx.token }));

  return new Terminal(ws);
};
