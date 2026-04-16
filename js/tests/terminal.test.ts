import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, it } from "node:test";

import { WebSocketServer, type WebSocket as ServerSocket } from "ws";

import { openTerminalConnection } from "../src/computers/terminal";
import type { ClientConfig } from "../src/core/config";

interface ServerContext {
  baseUrl: string;
  authHeader: string | undefined;
  lastPath: string | undefined;
  serverSockets: ServerSocket[];
  firstMessages: string[];
  shutdown: () => Promise<void>;
}

const startServer = async (): Promise<ServerContext> => {
  const http = createServer();
  const wss = new WebSocketServer({ noServer: true });

  const ctx: ServerContext = {
    baseUrl: "",
    authHeader: undefined,
    lastPath: undefined,
    serverSockets: [],
    firstMessages: [],
    shutdown: async () => {},
  };

  http.on("upgrade", (request, socket, head) => {
    ctx.authHeader = request.headers["authorization"] as string | undefined;
    ctx.lastPath = request.url;
    wss.handleUpgrade(request, socket, head, (ws) => {
      ctx.serverSockets.push(ws);
      ws.once("message", (raw) => {
        ctx.firstMessages.push(raw.toString("utf-8"));
      });
    });
  });

  await new Promise<void>((resolve) => http.listen(0, "127.0.0.1", resolve));
  const addr = http.address() as AddressInfo;
  ctx.baseUrl = `http://127.0.0.1:${addr.port}`;

  ctx.shutdown = async () => {
    for (const sock of ctx.serverSockets) {
      sock.close();
    }
    wss.close();
    await new Promise<void>((resolve) => http.close(() => resolve()));
  };

  return ctx;
};

describe("openTerminalConnection", () => {
  let server: ServerContext;

  before(async () => {
    server = await startServer();
  });

  after(async () => {
    await server.shutdown();
  });

  const makeConfig = (): ClientConfig => ({
    baseUrl: server.baseUrl,
    token: "term-token",
  });

  it("connects to /v1/computers/{id}/terminal with Authorization header", async () => {
    const terminal = await openTerminalConnection(makeConfig(), "cmp_abc");

    assert.equal(server.lastPath, "/v1/computers/cmp_abc/terminal");
    assert.equal(server.authHeader, "Bearer term-token");

    await terminal.close();
  });

  it("sends the legacy first-message token after handshake", async () => {
    const before = server.firstMessages.length;
    const terminal = await openTerminalConnection(makeConfig(), "cmp_first");

    // Wait a tick for the first-message to flush server-side
    await new Promise((resolve) => setTimeout(resolve, 20));

    const newMessages = server.firstMessages.slice(before);
    assert.equal(newMessages.length, 1);
    assert.deepEqual(JSON.parse(newMessages[0]!), { token: "term-token" });

    await terminal.close();
  });

  it("emits 'data' for server-sent text and binary messages", async () => {
    const terminal = await openTerminalConnection(makeConfig(), "cmp_data");
    const serverSocket = server.serverSockets[server.serverSockets.length - 1]!;

    const received: Array<string | Buffer> = [];
    terminal.on("data", (chunk) => received.push(chunk));

    // Wait a tick so the server-side socket has fully upgraded
    await new Promise((resolve) => setTimeout(resolve, 10));

    serverSocket.send("hello");
    serverSocket.send(Buffer.from([0x01, 0x02, 0x03]));

    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(received.length, 2);
    assert.equal(received[0], "hello");
    assert.ok(Buffer.isBuffer(received[1]));
    assert.deepEqual(received[1], Buffer.from([0x01, 0x02, 0x03]));

    await terminal.close();
  });

  it("write() sends keystrokes and resize() sends JSON resize frame", async () => {
    const terminal = await openTerminalConnection(makeConfig(), "cmp_write");
    const serverSocket = server.serverSockets[server.serverSockets.length - 1]!;

    const serverRecv: string[] = [];
    serverSocket.on("message", (raw) => serverRecv.push(raw.toString("utf-8")));

    // Wait past the first-message token that was sent during handshake
    await new Promise((resolve) => setTimeout(resolve, 20));
    const firstMessageCount = serverRecv.length;

    terminal.write("ls\n");
    terminal.resize(120, 40);

    await new Promise((resolve) => setTimeout(resolve, 50));

    const newMessages = serverRecv.slice(firstMessageCount);
    assert.equal(newMessages.length, 2);
    assert.equal(newMessages[0], "ls\n");
    assert.deepEqual(JSON.parse(newMessages[1]!), { type: "resize", cols: 120, rows: 40 });

    await terminal.close();
  });

  it("emits 'close' with the server-sent code and reason", async () => {
    const terminal = await openTerminalConnection(makeConfig(), "cmp_close");
    const serverSocket = server.serverSockets[server.serverSockets.length - 1]!;

    const closePromise = new Promise<{ code: number; reason: string }>((resolve) => {
      terminal.on("close", (code: number, reason: string) => resolve({ code, reason }));
    });

    await new Promise((resolve) => setTimeout(resolve, 10));
    serverSocket.close(4042, "server-bye");

    const result = await closePromise;
    assert.equal(result.code, 4042);
    assert.equal(result.reason, "server-bye");
    assert.equal(terminal.closed, true);
  });

  it("write() throws after close", async () => {
    const terminal = await openTerminalConnection(makeConfig(), "cmp_post_close");
    await terminal.close();
    assert.throws(() => terminal.write("nope"), /Terminal is closed/);
  });

  it("rejects if no token is configured", async () => {
    await assert.rejects(
      () => openTerminalConnection({ baseUrl: server.baseUrl }, "cmp_notoken"),
      /token is required/i,
    );
  });
});
