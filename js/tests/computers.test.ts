import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ComputersClient } from "../src/computers/client";
import type { ClientConfig } from "../src/core/config";
import { CelestoApiError, CelestoError, CelestoNetworkError } from "../src/core/errors";

interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

const makeFetchMock = (
  responder: (call: RecordedCall) => { status: number; body: unknown },
): { fetch: typeof fetch; calls: RecordedCall[] } => {
  const calls: RecordedCall[] = [];
  const mock: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const rawHeaders = (init?.headers ?? {}) as Record<string, string>;
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rawHeaders)) {
      headers[k.toLowerCase()] = v;
    }
    const bodyStr = typeof init?.body === "string" ? init.body : undefined;
    const parsed = bodyStr ? JSON.parse(bodyStr) : undefined;
    const call: RecordedCall = {
      url,
      method: init?.method ?? "GET",
      headers,
      body: parsed,
    };
    calls.push(call);
    const { status, body } = responder(call);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return { fetch: mock, calls };
};

const makeConfig = (fetchMock: typeof fetch): ClientConfig => ({
  baseUrl: "https://api.example.test",
  token: "test-token",
  fetch: fetchMock,
});

describe("ComputersClient", () => {
  it("create() sends vcpus/ram_mb wire fields and unwraps snake_case response", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_abc",
        name: "test",
        status: "creating",
        vcpus: 2,
        ram_mb: 2048,
        image: "ubuntu-desktop-24.04",
        created_at: "2026-04-16T00:00:00Z",
        last_error: null,
        stopped_at: null,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.create({ cpus: 2, memory: 2048 });

    assert.equal(calls.length, 1);
    assert.equal(calls[0]!.method, "POST");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers");
    assert.deepEqual(calls[0]!.body, {
      vcpus: 2,
      ram_mb: 2048,
      image: "ubuntu-desktop-24.04",
    });
    assert.equal(calls[0]!.headers["authorization"], "Bearer test-token");
    assert.equal(result.id, "cmp_abc");
    assert.equal(result.ramMb, 2048);
    assert.equal(result.lastError, null);
  });

  it("create() applies defaults when no params are provided", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_d",
        name: "d",
        status: "creating",
        vcpus: 1,
        ram_mb: 1024,
        image: "ubuntu-desktop-24.04",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await client.create();

    assert.deepEqual(calls[0]!.body, {
      vcpus: 1,
      ram_mb: 1024,
      image: "ubuntu-desktop-24.04",
    });
  });

  it("list() maps each computer through the wire transform", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 200,
      body: {
        computers: [
          {
            id: "cmp_1",
            name: "one",
            status: "running",
            vcpus: 1,
            ram_mb: 1024,
            image: "ubuntu-desktop-24.04",
            created_at: "2026-04-16T00:00:00Z",
            connection: { ssh: "user@host", access_url: "https://a" },
          },
          {
            id: "cmp_2",
            name: "two",
            status: "stopped",
            vcpus: 4,
            ram_mb: 8192,
            image: "ubuntu-desktop-24.04",
            created_at: "2026-04-16T00:00:00Z",
            stopped_at: "2026-04-16T01:00:00Z",
          },
        ],
        count: 2,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.list();

    assert.equal(result.count, 2);
    assert.equal(result.computers.length, 2);
    assert.equal(result.computers[0]!.connection?.ssh, "user@host");
    assert.equal(result.computers[0]!.connection?.accessUrl, "https://a");
    assert.equal(result.computers[1]!.stoppedAt, "2026-04-16T01:00:00Z");
  });

  it("get() resolves name to ID via /v1/computers/{name}", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: {
        id: "cmp_resolved",
        name: "my-name",
        status: "running",
        vcpus: 1,
        ram_mb: 1024,
        image: "ubuntu-desktop-24.04",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const info = await client.get("my-name");

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/my-name");
    assert.equal(info.id, "cmp_resolved");
  });

  it("exec() sends command + timeout and unwraps exit_code", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: { exit_code: 0, stdout: "ok\n", stderr: "" },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.exec("cmp_1", "uname -a", { timeout: 60 });

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/cmp_1/exec");
    assert.deepEqual(calls[0]!.body, { command: "uname -a", timeout: 60 });
    assert.equal(result.exitCode, 0);
    assert.equal(result.stdout, "ok\n");
  });

  it("stop/start/delete hit the right endpoints with the right methods", async () => {
    const hits: string[] = [];
    const { fetch } = makeFetchMock((call) => {
      hits.push(`${call.method} ${call.url}`);
      return {
        status: 200,
        body: {
          id: "cmp_1",
          name: "n",
          status: "stopping",
          vcpus: 1,
          ram_mb: 1024,
          image: "ubuntu-desktop-24.04",
          created_at: "2026-04-16T00:00:00Z",
        },
      };
    });
    const client = new ComputersClient(makeConfig(fetch));

    await client.stop("cmp_1");
    await client.start("cmp_1");
    await client.delete("cmp_1");

    assert.deepEqual(hits, [
      "POST https://api.example.test/v1/computers/cmp_1/stop",
      "POST https://api.example.test/v1/computers/cmp_1/start",
      "DELETE https://api.example.test/v1/computers/cmp_1",
    ]);
  });

  it("throws CelestoApiError on non-2xx responses", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 404,
      body: { detail: "Computer not found" },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await assert.rejects(
      () => client.get("cmp_missing"),
      (err: unknown) => {
        assert.ok(err instanceof CelestoApiError);
        assert.ok(err instanceof CelestoError, "CelestoApiError should extend CelestoError");
        assert.equal(err.status, 404);
        assert.equal(err.message, "Computer not found");
        return true;
      },
    );
  });

  it("wraps network failures in CelestoNetworkError", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };
    const client = new ComputersClient(makeConfig(failingFetch));

    await assert.rejects(
      () => client.list(),
      (err: unknown) => {
        assert.ok(err instanceof CelestoNetworkError);
        assert.ok(err instanceof CelestoError, "CelestoNetworkError should extend CelestoError");
        assert.match(err.message, /fetch failed/);
        return true;
      },
    );
  });

  it("getTerminalConnection() resolves name and returns wss:// URL with auth", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 200,
      body: {
        id: "cmp_resolved_id",
        name: "my-computer",
        status: "running",
        vcpus: 1,
        ram_mb: 1024,
        image: "ubuntu-desktop-24.04",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const conn = await client.getTerminalConnection("my-computer");

    assert.equal(conn.url, "wss://api.example.test/v1/computers/cmp_resolved_id/terminal");
    assert.equal(conn.headers["Authorization"], "Bearer test-token");
    assert.deepEqual(JSON.parse(conn.firstMessage), { token: "test-token" });
  });

  it("getTerminalConnection() throws when no token is configured", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 200,
      body: {
        id: "cmp_1",
        name: "n",
        status: "running",
        vcpus: 1,
        ram_mb: 1024,
        image: "ubuntu-desktop-24.04",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient({ baseUrl: "https://api.example.test", fetch });

    await assert.rejects(
      () => client.getTerminalConnection("cmp_1"),
      /token is required/i,
    );
  });
});
