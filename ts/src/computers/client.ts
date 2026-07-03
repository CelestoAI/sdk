import { buildRequestContext, ClientConfig, RequestOverrides } from "../core/config";
import { request } from "../core/http";
import {
  ComputerConnectionInfo,
  ComputerExecResponse,
  ComputerInfo,
  ComputerListResponse,
  ComputerPublishedPortInfo,
  ComputerStatus,
  CreateComputerParams,
  ExecParams,
  ListComputersParams,
  SandboxTemplateInfo,
  TerminalConnectionInfo,
} from "./types";

interface ComputerConnectionInfoWire {
  ssh?: string | null;
  access_url?: string | null;
}

interface ComputerPublishedPortInfoWire {
  id?: string | null;
  computer_id: string;
  port: number;
  url?: string | null;
  status: ComputerPublishedPortInfo["status"];
  created_at?: string | null;
}

interface ComputerInfoWire {
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ram_mb: number;
  disk_size_mb: number;
  image: string;
  template_id: string;
  template_version?: string | null;
  connection?: ComputerConnectionInfoWire | null;
  published_ports?: ComputerPublishedPortInfoWire[];
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

interface SandboxTemplateInfoWire {
  id: string;
  display_name: string;
  description: string;
  default_vcpus: number;
  default_ram_mb: number;
  default_disk_size_mb: number;
  version?: string | null;
  experimental: boolean;
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

const toPublishedPortInfo = (payload: ComputerPublishedPortInfoWire): ComputerPublishedPortInfo => ({
  id: payload.id ?? null,
  computerId: payload.computer_id,
  port: payload.port,
  url: payload.url ?? null,
  status: payload.status,
  createdAt: payload.created_at ?? null,
});

const toComputerInfo = (payload: ComputerInfoWire): ComputerInfo => ({
  id: payload.id,
  name: payload.name,
  status: payload.status,
  vcpus: payload.vcpus,
  ramMb: payload.ram_mb,
  diskSizeMb: payload.disk_size_mb,
  image: payload.image,
  templateId: payload.template_id,
  templateVersion: payload.template_version ?? null,
  connection: toConnection(payload.connection),
  publishedPorts: payload.published_ports?.map(toPublishedPortInfo),
  lastError: payload.last_error ?? null,
  createdAt: payload.created_at,
  stoppedAt: payload.stopped_at ?? null,
});

const toExecResponse = (payload: ComputerExecResponseWire): ComputerExecResponse => ({
  exitCode: payload.exit_code,
  stdout: payload.stdout,
  stderr: payload.stderr,
});

const toSandboxTemplateInfo = (payload: SandboxTemplateInfoWire): SandboxTemplateInfo => ({
  id: payload.id,
  displayName: payload.display_name,
  description: payload.description,
  defaultVcpus: payload.default_vcpus,
  defaultRamMb: payload.default_ram_mb,
  defaultDiskSizeMb: payload.default_disk_size_mb,
  version: payload.version ?? null,
  experimental: payload.experimental,
});

const diskUnitsToMb: Record<string, number> = {
  "": 1,
  m: 1,
  mb: 1,
  mib: 1,
  g: 1024,
  gb: 1024,
  gib: 1024,
  t: 1024 * 1024,
  tb: 1024 * 1024,
  tib: 1024 * 1024,
};

const parseDiskSizeMb = (disk: number | string | undefined): number | undefined => {
  if (disk === undefined) {
    return undefined;
  }

  if (typeof disk === "number") {
    if (!Number.isInteger(disk) || disk <= 0) {
      throw new Error("disk as a number must be a whole number of MB.");
    }
    return disk;
  }

  const match = /^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$/.exec(disk);
  if (!match) {
    throw new Error("disk must be a size in MB or a string like '2gb'.");
  }

  const multiplier = diskUnitsToMb[match[2]!.toLowerCase()];
  if (multiplier === undefined) {
    throw new Error("disk must use MB, GB, or TB, for example '2048mb' or '2gb'.");
  }

  const sizeMb = Number(match[1]) * multiplier;
  if (!Number.isInteger(sizeMb) || sizeMb <= 0) {
    throw new Error("disk must resolve to a whole number of MB, for example '1536mb' or '1.5gb'.");
  }
  return sizeMb;
};

const buildCreateComputerBody = (params: CreateComputerParams): Record<string, unknown> => {
  if (params.cpus !== undefined && params.vcpus !== undefined && params.cpus !== params.vcpus) {
    throw new Error("cpus and vcpus must have the same value when both are provided.");
  }
  if (params.memory !== undefined && params.ramMb !== undefined && params.memory !== params.ramMb) {
    throw new Error("memory and ramMb must have the same value when both are provided.");
  }

  const parsedDiskSizeMb = parseDiskSizeMb(params.disk);
  if (
    parsedDiskSizeMb !== undefined &&
    params.diskSizeMb !== undefined &&
    parsedDiskSizeMb !== params.diskSizeMb
  ) {
    throw new Error("disk and diskSizeMb must have the same value when both are provided.");
  }

  const body: Record<string, unknown> = {};
  const vcpus = params.vcpus ?? params.cpus;
  const ramMb = params.ramMb ?? params.memory;
  const diskSizeMb = params.diskSizeMb ?? parsedDiskSizeMb;
  if (vcpus !== undefined) {
    body.vcpus = vcpus;
  }
  if (ramMb !== undefined) {
    body.ram_mb = ramMb;
  }
  if (diskSizeMb !== undefined) {
    body.disk_size_mb = diskSizeMb;
  }
  if (params.image !== undefined) {
    body.image = params.image;
  }
  if (params.templateId !== undefined) {
    body.template_id = params.templateId;
  }
  if (params.templateVersion !== undefined) {
    body.template_version = params.templateVersion;
  }
  return body;
};

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
 * const computer = await Computer.create();
 * const result = await computer.run("uname -a");
 * console.log(result.stdout);
 * await computer.delete();
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
      body: buildCreateComputerBody(params),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async listTemplates(options?: RequestOverrides): Promise<SandboxTemplateInfo[]> {
    const ctx = buildRequestContext(this.config);
    const data = await request<SandboxTemplateInfoWire[]>(ctx, {
      method: "GET",
      path: computersPath("/templates"),
      ...pickOverrides(options),
    });
    return data.map(toSandboxTemplateInfo);
  }

  async list(params: ListComputersParams = {}, options?: RequestOverrides): Promise<ComputerListResponse> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerListResponseWire>(ctx, {
      method: "GET",
      path: computersPath(""),
      query: {
        status: params.status,
        template_id: params.templateId,
        project_id: params.projectId,
        limit: params.limit,
      },
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

  async publishPort(
    computerId: string,
    port = 8000,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports`),
      body: { port },
      ...pickOverrides(options),
    });
    return toPublishedPortInfo(data);
  }

  async listPublishedPorts(
    computerId: string,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo[]> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire[]>(ctx, {
      method: "GET",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports`),
      ...pickOverrides(options),
    });
    return data.map(toPublishedPortInfo);
  }

  async unpublishPort(
    computerId: string,
    port = 8000,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire>(ctx, {
      method: "DELETE",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports/${port}`),
      ...pickOverrides(options),
    });
    return toPublishedPortInfo(data);
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
   * const conn = await client.getTerminalConnection("my-computer");
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
