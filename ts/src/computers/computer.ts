import { ClientConfig } from "../core/config";
import { ComputersClient } from "./client";
import {
  ComputerConnectionInfo,
  ComputerExecResponse,
  ComputerInfo,
  ComputerPublishedPortInfo,
  ComputerStatus,
  CreateComputerParams,
  ExecParams,
  ListComputersParams,
  SandboxTemplateInfo,
} from "./types";

const defaultConfig = (): ClientConfig => ({
  token: typeof process !== "undefined" ? process.env.CELESTO_API_KEY : undefined,
});

/** Convenience object for one Celesto computer. */
export class Computer {
  private readonly client: ComputersClient;
  private info: ComputerInfo;

  private constructor(client: ComputersClient, info: ComputerInfo) {
    this.client = client;
    this.info = info;
  }

  /** Create a new computer and return an object with methods on it. */
  static async create(params: CreateComputerParams = {}, config: ClientConfig = defaultConfig()): Promise<Computer> {
    const client = new ComputersClient(config);
    const info = await client.create(params);
    return new Computer(client, info);
  }

  /** Load an existing computer by name or ID. */
  static async get(computerIdOrName: string, config: ClientConfig = defaultConfig()): Promise<Computer> {
    const client = new ComputersClient(config);
    const info = await client.get(computerIdOrName);
    return new Computer(client, info);
  }

  /** List computers in the current account. */
  static async list(params: ListComputersParams = {}, config: ClientConfig = defaultConfig()): Promise<Computer[]> {
    const client = new ComputersClient(config);
    const response = await client.list(params);
    return response.computers.map((info) => new Computer(client, info));
  }

  /** List available computer templates. */
  static async listTemplates(config: ClientConfig = defaultConfig()): Promise<SandboxTemplateInfo[]> {
    const client = new ComputersClient(config);
    return client.listTemplates();
  }

  /** Wrap an existing API response in the convenience object. */
  static fromInfo(info: ComputerInfo, config: ClientConfig = defaultConfig()): Computer {
    return new Computer(new ComputersClient(config), info);
  }

  get id(): string {
    return this.info.id;
  }

  get name(): string {
    return this.info.name;
  }

  get status(): ComputerStatus {
    return this.info.status;
  }

  get vcpus(): number {
    return this.info.vcpus;
  }

  get ramMb(): number {
    return this.info.ramMb;
  }

  get diskSizeMb(): number {
    return this.info.diskSizeMb;
  }

  get image(): string {
    return this.info.image;
  }

  get templateId(): string {
    return this.info.templateId;
  }

  get templateVersion(): string | null | undefined {
    return this.info.templateVersion;
  }

  get connection(): ComputerConnectionInfo | undefined {
    return this.info.connection;
  }

  get publishedPorts(): ComputerPublishedPortInfo[] | undefined {
    return this.info.publishedPorts;
  }

  get lastError(): string | null | undefined {
    return this.info.lastError;
  }

  get createdAt(): string {
    return this.info.createdAt;
  }

  get stoppedAt(): string | null | undefined {
    return this.info.stoppedAt;
  }

  /** Get one field from the latest computer data. */
  get<K extends keyof ComputerInfo>(key: K): ComputerInfo[K] {
    return this.info[key];
  }

  /** Return a copy of the latest computer data. */
  toJSON(): ComputerInfo {
    return { ...this.info };
  }

  /** Reload this computer from Celesto. */
  async refresh(): Promise<this> {
    this.info = await this.client.get(this.id);
    return this;
  }

  /** Run a shell command on this computer. */
  async run(command: string, params: ExecParams = {}): Promise<ComputerExecResponse> {
    return this.client.exec(this.id, command, params);
  }

  /** Alias for run(). */
  async exec(command: string, params: ExecParams = {}): Promise<ComputerExecResponse> {
    return this.run(command, params);
  }

  /** Stop this computer and update the local data. */
  async stop(): Promise<this> {
    this.info = await this.client.stop(this.id);
    return this;
  }

  /** Start this computer and update the local data. */
  async start(): Promise<this> {
    this.info = await this.client.start(this.id);
    return this;
  }

  /** Delete this computer and update the local data. */
  async delete(): Promise<this> {
    this.info = await this.client.delete(this.id);
    return this;
  }

  /** Publish a port and return its public URL when the API provides one. */
  async publishPort(port = 8000): Promise<string | null> {
    const published = await this.client.publishPort(this.id, port);
    const existing = this.info.publishedPorts ?? [];
    this.info = {
      ...this.info,
      publishedPorts: [...existing.filter((item) => item.port !== published.port), published],
    };
    return published.url ?? null;
  }

  /** List public ports for this computer. */
  async listPublishedPorts(): Promise<ComputerPublishedPortInfo[]> {
    const publishedPorts = await this.client.listPublishedPorts(this.id);
    this.info = { ...this.info, publishedPorts };
    return publishedPorts;
  }

  /** Remove a public port route. */
  async unpublishPort(port = 8000): Promise<ComputerPublishedPortInfo> {
    const unpublished = await this.client.unpublishPort(this.id, port);
    this.info = {
      ...this.info,
      publishedPorts: (this.info.publishedPorts ?? []).filter((item) => item.port !== port),
    };
    return unpublished;
  }
}
