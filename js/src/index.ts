import { ComputersClient } from "./computers";
import { GatekeeperClient } from "./gatekeeper";
import type { ClientConfig } from "./core/config";

export { GatekeeperClient } from "./gatekeeper";
export type {
  GatekeeperAccessRules,
  GatekeeperAccessRulesParams,
  GatekeeperAccessRulesUpdate,
  GatekeeperConnectRequest,
  GatekeeperConnectResponse,
  GatekeeperConnection,
  GatekeeperDriveFile,
  GatekeeperDriveListParams,
  GatekeeperDriveListResponse,
  GatekeeperListConnectionsParams,
  GatekeeperListConnectionsResponse,
  GatekeeperRevokeParams,
  GatekeeperRevokeResponse,
} from "./gatekeeper";
export { ComputersClient, Terminal } from "./computers";
export type {
  ComputerConnectionInfo,
  ComputerExecResponse,
  ComputerInfo,
  ComputerListResponse,
  ComputerStatus,
  CreateComputerParams,
  ExecParams,
  OpenTerminalOptions,
} from "./computers";
export type { ClientConfig, RequestOverrides } from "./core/config";
export { CelestoApiError } from "./core/errors";

export class CelestoClient {
  readonly gatekeeper: GatekeeperClient;
  readonly computers: ComputersClient;

  constructor(config: ClientConfig) {
    this.gatekeeper = new GatekeeperClient(config);
    this.computers = new ComputersClient(config);
  }
}
