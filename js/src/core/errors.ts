export class CelestoApiError extends Error {
  readonly status: number;
  readonly data: unknown;
  readonly requestId?: string;

  constructor(message: string, status: number, data: unknown, requestId?: string) {
    super(message);
    this.name = "CelestoApiError";
    this.status = status;
    this.data = data;
    this.requestId = requestId;
  }
}
