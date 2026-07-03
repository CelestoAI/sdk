export type ComputerStatus =
  | "creating"
  | "running"
  | "stopping"
  | "stopped"
  | "starting"
  | "restoring"
  | "restorable"
  | "deleting"
  | "deleted"
  | "error";

export interface ComputerConnectionInfo {
  ssh?: string;
  accessUrl?: string;
}

export type PublishedPortStatus =
  | "publishing"
  | "published"
  | "unpublishing"
  | "unpublished"
  | "error";

export interface ComputerPublishedPortInfo {
  id?: string | null;
  computerId: string;
  port: number;
  url?: string | null;
  status: PublishedPortStatus;
  createdAt?: string | null;
}

export interface ComputerInfo {
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ramMb: number;
  diskSizeMb: number;
  image: string;
  templateId: string;
  templateVersion?: string | null;
  connection?: ComputerConnectionInfo;
  publishedPorts?: ComputerPublishedPortInfo[];
  lastError?: string | null;
  createdAt: string;
  stoppedAt?: string | null;
}

export interface ComputerListResponse {
  computers: ComputerInfo[];
  count: number;
}

export interface ListComputersParams {
  /** Optional status filter, such as "running" or "stopped". */
  status?: ComputerStatus;
  /** Optional template filter, such as "coding-agent". */
  templateId?: string;
  /** Optional project ID filter. */
  projectId?: string;
  /** Optional maximum number of computers to return. */
  limit?: number;
}

export interface ComputerExecResponse {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export interface SandboxTemplateInfo {
  id: string;
  displayName: string;
  description: string;
  defaultVcpus: number;
  defaultRamMb: number;
  defaultDiskSizeMb: number;
  version?: string | null;
  experimental: boolean;
}

export interface CreateComputerParams {
  /** Number of virtual CPUs (1-16). Alias for vcpus. */
  cpus?: number;
  /** Number of virtual CPUs (1-16). */
  vcpus?: number;
  /** Memory in MB (512-32768). Alias for ramMb. */
  memory?: number;
  /** Memory in MB (512-32768). */
  ramMb?: number;
  /** Disk size as MB or a string like "2gb". Alias for diskSizeMb. */
  disk?: number | string;
  /** Disk size in MB (512-51200). */
  diskSizeMb?: number;
  /** Legacy OS image selector. */
  image?: string;
  /** Sandbox template id, such as "scratch" or "coding-agent". */
  templateId?: string;
  /** Optional immutable template version. */
  templateVersion?: string;
}

export interface ExecParams {
  /** Timeout in seconds (1-300). Defaults to 30. */
  timeout?: number;
}

/**
 * Everything needed to open a WebSocket terminal connection.
 *
 * Use with any WebSocket library:
 * ```ts
 * const conn = await client.getTerminalConnection("my-computer");
 * const ws = new WebSocket(conn.url, { headers: conn.headers });
 * ws.on("open", () => ws.send(conn.firstMessage));
 * ```
 */
export interface TerminalConnectionInfo {
  /** The wss:// URL to connect to. */
  url: string;
  /** Headers to send on the WebSocket handshake (includes Authorization). */
  headers: Record<string, string>;
  /** JSON string to send as the first message after connect (legacy token auth). */
  firstMessage: string;
}
