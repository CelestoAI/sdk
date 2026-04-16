import { buildRequestContext, ClientConfig, RequestOverrides } from "../core/config";
import { request } from "../core/http";
import {
  ComputerConnectionInfo,
  ComputerExecResponse,
  ComputerInfo,
  ComputerListResponse,
  ComputerStatus,
  CreateComputerParams,
  ExecParams,
  TerminalConnectionInfo,
} from "./types";

interface ComputerConnectionInfoWire {
  ssh?: string | null;
  access_url?: string | null;
}

interface ComputerInfoWire {
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ram_mb: number;
  image: string;
  connection?: ComputerConnectionInfoWire | null;
  last_error?: string | null;
  created_at: string;
  stopped_at?: string | null;
}

interface ComputerListResponseWire {
  computers: ComputerInfoWire[];
  count: number;
}

interface ComputerExecResponseWire {
  exit_code: number;
  stdout: string;
  stderr: string;
}

const toConnection = (
  payload: ComputerConnectionInfoWire | null | undefined,
): ComputerConnectionInfo | undefined => {
  if (!payload) {
    return undefined;
  }
  const out: ComputerConnectionInfo = {};
  if (payload.ssh != null) {
    out.ssh = payload.ssh;
  }
  if (payload.access_url != null) {
    out.accessUrl = payload.access_url;
  }
  return out;
};

const toComputerInfo = (payload: ComputerInfoWire): ComputerInfo => ({
  id: payload.id,
  name: payload.name,
  status: payload.status,
  vcpus: payload.vcpus,
  ramMb: payload.ram_mb,
  image: payload.image,
  connection: toConnection(payload.connection),
  lastError: payload.last_error ?? null,
  createdAt: payload.created_at,
  stoppedAt: payload.stopped_at ?? null,
});

const toExecResponse = (payload: ComputerExecResponseWire): ComputerExecResponse => ({
  exitCode: payload.exit_code,
  stdout: payload.stdout,
  stderr: payload.stderr,
});

const computersPath = (path: string): string => `/v1/computers${path}`;

const pickOverrides = (options?: RequestOverrides): RequestOverrides => ({
  headers: options?.headers,
  signal: options?.signal,
});

/**
 * Client for managing sandboxed computers (AI sandboxes).
 *
 * Provides create/list/get/exec/stop/start/delete over HTTP, plus
 * `getTerminalConnection()` which returns the URL and headers needed
 * to open a WebSocket terminal with any WS library of your choice.
 *
 * @example
 * ```ts
 * const celesto = new Celesto({ token: process.env.CELESTO_API_KEY });
 * const computer = await celesto.computers.create({ cpus: 2, memory: 2048 });
 * const result = await celesto.computers.exec(computer.id, "uname -a");
 * console.log(result.stdout);
 * await celesto.computers.delete(computer.id);
 * ```
 */
export class ComputersClient {
  private readonly config: ClientConfig;

  constructor(config: ClientConfig) {
    this.config = config;
  }

  async create(params: CreateComputerParams = {}, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(""),
      body: {
        vcpus: params.cpus ?? 1,
        ram_mb: params.memory ?? 1024,
        image: params.image ?? "ubuntu-desktop-24.04",
      },
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async list(options?: RequestOverrides): Promise<ComputerListResponse> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerListResponseWire>(ctx, {
      method: "GET",
      path: computersPath(""),
      ...pickOverrides(options),
    });
    return {
      computers: data.computers.map(toComputerInfo),
      count: data.count,
    };
  }

  async get(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "GET",
      path: computersPath(`/${encodeURIComponent(computerId)}`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async exec(
    computerId: string,
    command: string,
    params: ExecParams = {},
    options?: RequestOverrides,
  ): Promise<ComputerExecResponse> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerExecResponseWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/exec`),
      body: {
        command,
        timeout: params.timeout ?? 30,
      },
      ...pickOverrides(options),
    });
    return toExecResponse(data);
  }

  async stop(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/stop`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async start(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/start`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async delete(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "DELETE",
      path: computersPath(`/${encodeURIComponent(computerId)}`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  /**
   * Get connection info for opening a WebSocket terminal session.
   *
   * Accepts either a computer ID (e.g. `cmp_xxx`) or a human-readable name.
   * The name is resolved to the canonical ID via a GET call — the backend's
   * WebSocket endpoint does not resolve names on its own.
   *
   * Returns the URL, headers, and first message needed to open the connection
   * with any WebSocket library of your choice.
   *
   * @example
   * ```ts
   * const conn = await celesto.computers.getTerminalConnection("my-computer");
   * const ws = new WebSocket(conn.url, { headers: conn.headers });
   * ws.on("open", () => ws.send(conn.firstMessage));
   * ws.on("message", (data) => process.stdout.write(data));
   * ```
   */
  async getTerminalConnection(computerIdOrName: string): Promise<TerminalConnectionInfo> {
    const info = await this.get(computerIdOrName);
    const ctx = buildRequestContext(this.config);

    if (!ctx.token) {
      throw new Error("A token is required for terminal connections");
    }

    const wsBase = ctx.baseUrl.replace(/^https:/i, "wss:").replace(/^http:/i, "ws:");
    const url = `${wsBase}/v1/computers/${encodeURIComponent(info.id)}/terminal`;

    const headers: Record<string, string> = {
      Authorization: `Bearer ${ctx.token}`,
    };
    if (ctx.organizationId) {
      headers["X-Current-Organization"] = ctx.organizationId;
    }

    return {
      url,
      headers,
      firstMessage: JSON.stringify({ token: ctx.token }),
    };
  }
}
