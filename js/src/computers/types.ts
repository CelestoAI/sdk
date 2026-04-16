export type ComputerStatus =
  | "creating"
  | "running"
  | "stopping"
  | "stopped"
  | "starting"
  | "deleting"
  | "deleted"
  | "error";

export interface ComputerConnectionInfo {
  ssh?: string;
  accessUrl?: string;
}

export interface ComputerInfo {
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ramMb: number;
  image: string;
  connection?: ComputerConnectionInfo;
  lastError?: string | null;
  createdAt: string;
  stoppedAt?: string | null;
}

export interface ComputerListResponse {
  computers: ComputerInfo[];
  count: number;
}

export interface ComputerExecResponse {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export interface CreateComputerParams {
  /** Number of virtual CPUs (1-16). Defaults to 1. */
  cpus?: number;
  /** Memory in MB (512-32768). Defaults to 1024. */
  memory?: number;
  /** OS image name. Defaults to "ubuntu-desktop-24.04". */
  image?: string;
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
 * const conn = await celesto.computers.getTerminalConnection("my-computer");
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
