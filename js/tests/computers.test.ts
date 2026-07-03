import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Computer } from "../src/computers/computer";
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
  it("create() sends explicit resource/template fields and unwraps snake_case response", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_abc",
        name: "test",
        status: "creating",
        vcpus: 2,
        ram_mb: 2048,
        disk_size_mb: 15360,
        image: "ubuntu-desktop-24.04",
        template_id: "coding-agent",
        template_version: "latest",
        created_at: "2026-04-16T00:00:00Z",
        last_error: null,
        stopped_at: null,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.create({
      cpus: 2,
      memory: 2048,
      diskSizeMb: 15360,
      templateId: "coding-agent",
      templateVersion: "latest",
    });

    assert.equal(calls.length, 1);
    assert.equal(calls[0]!.method, "POST");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers");
    assert.deepEqual(calls[0]!.body, {
      vcpus: 2,
      ram_mb: 2048,
      disk_size_mb: 15360,
      template_id: "coding-agent",
      template_version: "latest",
    });
    assert.equal(calls[0]!.headers["authorization"], "Bearer test-token");
    assert.equal(result.id, "cmp_abc");
    assert.equal(result.ramMb, 2048);
    assert.equal(result.diskSizeMb, 15360);
    assert.equal(result.templateId, "coding-agent");
    assert.equal(result.templateVersion, "latest");
    assert.equal(result.lastError, null);
  });

  it("create() leaves defaults to the backend when no params are provided", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_d",
        name: "d",
        status: "creating",
        vcpus: 1,
        ram_mb: 512,
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await client.create();

    assert.deepEqual(calls[0]!.body, {});
  });

  it("create() accepts friendly disk sizes", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_disk",
        name: "disk",
        status: "creating",
        vcpus: 1,
        ram_mb: 1024,
        disk_size_mb: 1536,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await client.create({ disk: "1.5gb" });

    assert.deepEqual(calls[0]!.body, { disk_size_mb: 1536 });
  });

  it("create() rejects conflicting aliases", async () => {
    const client = new ComputersClient(makeConfig(async () => new Response()));

    await assert.rejects(
      () => client.create({ cpus: 1, vcpus: 2 }),
      /cpus and vcpus must have the same value/i,
    );
    await assert.rejects(
      () => client.create({ memory: 1024, ramMb: 2048 }),
      /memory and ramMb must have the same value/i,
    );
    await assert.rejects(
      () => client.create({ disk: "2gb", diskSizeMb: 1024 }),
      /disk and diskSizeMb must have the same value/i,
    );
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
            disk_size_mb: 7168,
            image: "ubuntu-desktop-24.04",
            template_id: "scratch",
            created_at: "2026-04-16T00:00:00Z",
            connection: { ssh: "user@host", access_url: "https://a" },
          },
          {
            id: "cmp_2",
            name: "two",
            status: "stopped",
            vcpus: 4,
            ram_mb: 8192,
            disk_size_mb: 15360,
            image: "ubuntu-desktop-24.04",
            template_id: "browser-agent",
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
    assert.equal(result.computers[1]!.diskSizeMb, 15360);
    assert.equal(result.computers[1]!.templateId, "browser-agent");
    assert.equal(result.computers[1]!.stoppedAt, "2026-04-16T01:00:00Z");
  });

  it("listTemplates() maps sandbox template metadata", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: [
        {
          id: "coding-agent",
          display_name: "Coding Agent",
          description: "Ready-to-code sandbox",
          default_vcpus: 1,
          default_ram_mb: 1024,
          default_disk_size_mb: 15360,
          version: "latest",
          experimental: false,
        },
      ],
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const templates = await client.listTemplates();

    assert.equal(calls[0]!.method, "GET");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/templates");
    assert.equal(templates[0]!.id, "coding-agent");
    assert.equal(templates[0]!.displayName, "Coding Agent");
    assert.equal(templates[0]!.defaultDiskSizeMb, 15360);
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
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
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
          disk_size_mb: 7168,
          image: "ubuntu-desktop-24.04",
          template_id: "scratch",
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

  it("published port methods hit the right endpoints and map response fields", async () => {
    const { fetch, calls } = makeFetchMock((call) => ({
      status: 200,
      body: call.method === "GET"
        ? [
            {
              id: "cpp_1",
              computer_id: "cmp_1",
              port: 8080,
              url: "https://p-test.celesto.ai",
              status: "published",
              created_at: "2026-04-16T00:00:00Z",
            },
          ]
        : {
            id: "cpp_1",
            computer_id: "cmp_1",
            port: 8080,
            url: call.method === "DELETE" ? null : "https://p-test.celesto.ai",
            status: call.method === "DELETE" ? "unpublished" : "published",
            created_at: "2026-04-16T00:00:00Z",
          },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const published = await client.publishPort("cmp_1", 8080);
    const ports = await client.listPublishedPorts("cmp_1");
    const unpublished = await client.unpublishPort("cmp_1", 8080);

    assert.equal(published.url, "https://p-test.celesto.ai");
    assert.equal(ports[0]!.computerId, "cmp_1");
    assert.equal(unpublished.status, "unpublished");
    assert.deepEqual(calls.map((call) => `${call.method} ${call.url}`), [
      "POST https://api.example.test/v1/computers/cmp_1/published-ports",
      "GET https://api.example.test/v1/computers/cmp_1/published-ports",
      "DELETE https://api.example.test/v1/computers/cmp_1/published-ports/8080",
    ]);
  });

  it("Computer convenience object supports properties, run, stop, and publishPort", async () => {
    const { fetch, calls } = makeFetchMock((call) => {
      if (call.url.endsWith("/exec")) {
        return { status: 200, body: { exit_code: 0, stdout: "hello\n", stderr: "" } };
      }
      if (call.url.endsWith("/stop")) {
        return {
          status: 200,
          body: {
            id: "cmp_1",
            name: "curie",
            status: "stopped",
            vcpus: 1,
            ram_mb: 512,
            disk_size_mb: 2048,
            image: "ubuntu-desktop-24.04",
            template_id: "scratch",
            created_at: "2026-04-16T00:00:00Z",
          },
        };
      }
      if (call.url.endsWith("/published-ports")) {
        return {
          status: 200,
          body: {
            id: "cpp_1",
            computer_id: "cmp_1",
            port: 8080,
            url: "https://p-test.celesto.ai",
            status: "published",
            created_at: "2026-04-16T00:00:00Z",
          },
        };
      }
      return {
        status: 201,
        body: {
          id: "cmp_1",
          name: "curie",
          status: "running",
          vcpus: 1,
          ram_mb: 512,
          disk_size_mb: 2048,
          image: "ubuntu-desktop-24.04",
          template_id: "scratch",
          created_at: "2026-04-16T00:00:00Z",
        },
      };
    });

    const computer = await Computer.create(
      { cpus: 1, memory: 512, disk: "2gb" },
      makeConfig(fetch),
    );
    const result = await computer.run("echo hello", { timeout: 60 });
    await computer.stop();
    const url = await computer.publishPort(8080);

    assert.equal(computer.name, "curie");
    assert.equal(computer["name"], "curie");
    assert.equal(computer.get("name"), "curie");
    assert.equal(result.stdout, "hello\n");
    assert.equal(computer.status, "stopped");
    assert.equal(url, "https://p-test.celesto.ai");
    assert.deepEqual(calls[0]!.body, {
      vcpus: 1,
      ram_mb: 512,
      disk_size_mb: 2048,
    });
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
        if (!(err instanceof CelestoApiError)) {
          return false;
        }
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
        if (!(err instanceof CelestoNetworkError)) {
          return false;
        }
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
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
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
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
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
