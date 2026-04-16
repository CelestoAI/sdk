# @celestoai/sdk

Node-only TypeScript SDK for the [Celesto](https://celesto.ai) platform. Covers:

- **Gatekeeper** (`/v1/gatekeeper`) — delegated access to user resources
- **Computers** (`/v1/computers`) — create, manage, and interact with sandboxed virtual machines

## Install

```bash
npm install @celestoai/sdk
```

## Quickstart

```ts
import { Celesto } from "@celestoai/sdk";

const celesto = new Celesto({
  token: process.env.CELESTO_API_KEY,
  // organizationId: "org_123", // optional, for JWTs with multiple orgs
});

// Gatekeeper
const connect = await celesto.gatekeeper.connect({
  subject: "customer_123",
  provider: "google_drive",
  projectName: "Default",
});

// Computers
const computer = await celesto.computers.create({ cpus: 2, memory: 2048 });
const result = await celesto.computers.exec(computer.id, "uname -a");
console.log(result.stdout);
await celesto.computers.delete(computer.id);
```

## Computers

### Lifecycle

```ts
const computer = await celesto.computers.create({
  cpus: 2,
  memory: 2048,
  image: "ubuntu-desktop-24.04",
});

await celesto.computers.stop(computer.id);
await celesto.computers.start(computer.id);
await celesto.computers.delete(computer.id);

const { computers, count } = await celesto.computers.list();
```

### Running commands

```ts
const result = await celesto.computers.exec(computer.id, "ls -la", { timeout: 60 });
console.log(result.exitCode, result.stdout, result.stderr);
```

### Interactive terminal

`openTerminal()` returns an event-driven handle backed by a WebSocket. It accepts either a
computer ID or a human-readable name — the name is resolved to the canonical ID before the
WebSocket handshake. `openTerminal()` does **not** auto-resume stopped computers; call
`start()` yourself and poll for `status === "running"` if you need that.

```ts
const terminal = await celesto.computers.openTerminal(computer.id);

terminal.on("data", (chunk) => process.stdout.write(chunk));
terminal.on("close", (code, reason) => {
  console.log(`terminal closed: ${code} ${reason}`);
});
terminal.on("error", (err) => {
  console.error(err);
});

terminal.write("ls -la\n");
terminal.resize(120, 40);

// ...later
await terminal.close();
```

## Gatekeeper

```ts
import { GatekeeperClient } from "@celestoai/sdk/gatekeeper";

const client = new GatekeeperClient({ token: process.env.CELESTO_API_KEY });

const connect = await client.connect({
  subject: "customer_123",
  provider: "google_drive",
  projectName: "Default",
});

if (connect.status === "redirect") {
  console.log("OAuth URL:", connect.oauthUrl);
}
```

Full docs: https://docs.celesto.ai/celesto-sdk/gatekeeper

## Notes

- `token` accepts either a Celesto API key or a JWT.
- `organizationId` adds the `X-Current-Organization` header.
- Requires Node 18+ for built-in `fetch`. The `ws` package is used for WebSocket terminal support.

## License

Apache-2.0. The SDK is open source; use of the Celesto platform is governed by the Celesto Terms of Service: https://celesto.ai/legal/terms
