# @celestoai/sdk

Use this package to run work in Celesto from a Node.js app. Your code can create
a cloud computer, run commands in it, and delete it when the work is done.

An AI agent is software that can plan and run tasks. A harness is the code that
starts, tests, or supervises an agent.

Use this package when you want to:

- Run an AI agent or harness in a clean computer.
- Run shell commands from JavaScript or TypeScript.
- Keep agent work separate from your laptop, server, or production system.
- Ask a user to approve access to Google Drive through Gatekeeper.

Gatekeeper is Celesto's access helper. It lets a user approve which external
files or folders your app can use.

## Requirements

- Node.js 18 or newer.
- A Celesto API key from [Celesto Settings](https://celesto.ai) under
  **Settings > Security**.

## Install

```bash
npm install @celestoai/sdk
```

Set your API key before running SDK examples:

```bash
export CELESTO_API_KEY="your-api-key"
```

## Quickstart

Create a file named `quickstart.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create();
try {
  console.log(`Computer ready: ${computer.name}`);

  const result = await computer.run("uname -a");
  console.log(result.stdout);
} finally {
  await computer.delete();
}
```

Run it:

```bash
node quickstart.mjs
```

## Computers

A computer is a disposable cloud machine for your app or agent. By default,
Celesto creates a `scratch` computer, which is a minimal Ubuntu computer.

### Create with Custom Resources

Create a file named `create-computer.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({
  cpus: 2,
  memory: 2048,
  disk: "15gb",
});

try {
  console.log(computer.name, computer["name"]);
} finally {
  await computer.delete();
}
```

Omit CPU, memory, or disk fields to use the default size. `disk` accepts MB as
an integer or strings such as `"2gb"`.

### Templates

Use a template when you want a computer that already has extra tools installed.
For example, `coding-agent` includes common tools for coding tasks.

List available templates:

Create a file named `list-templates.mjs`:

```js
import { Celesto } from "@celestoai/sdk";

const celesto = new Celesto({ token: process.env.CELESTO_API_KEY });

const templates = await celesto.computers.listTemplates();
for (const template of templates) {
  console.log(template.id, template.defaultRamMb);
}
```

Create a computer from a template:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({ templateId: "coding-agent" });
try {
  console.log(computer.name);
} finally {
  await computer.delete();
}
```

### Run a Command

Create a file named `run-command.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create();
try {
  const result = await computer.run("ls -la", {
    timeout: 60,
  });

  console.log(result.exitCode);
  console.log(result.stdout);
  console.error(result.stderr);
} finally {
  await computer.delete();
}
```

### Manage Computers

`computerId` can be `computer.id` from `Computer.create()` or a computer name
shown by the Celesto command-line tool: `celesto computer list`.

| Method | What it does |
| --- | --- |
| `celesto.computers.list()` | List computers in your account |
| `Computer.get(computerId)` | Get one computer by name or ID |
| `computer.stop()` | Stop a running computer |
| `computer.start()` | Start a stopped computer |
| `computer.delete()` | Delete a computer |

### Publish Ports

Publish a port when a service inside the computer needs a public URL:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.get("curie");
const url = await computer.publishPort(8000);
console.log(url);
```

List and remove published ports:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.get("curie");
console.log(await computer.listPublishedPorts());
await computer.unpublishPort(8000);
```

### Terminal Connections

Use `getTerminalConnection()` when you are building your own interactive
terminal. It returns the WebSocket URL, headers, and first message needed to
connect. A WebSocket is a long-running connection for sending terminal input and
receiving terminal output.

The SDK does not install a WebSocket package for you. Use any WebSocket library
that supports custom headers.

## Gatekeeper

Use Gatekeeper when your app needs user-approved access to an external resource,
such as Google Drive.

Create a file named `gatekeeper-connect.mjs`:

```js
import { GatekeeperClient } from "@celestoai/sdk/gatekeeper";

const client = new GatekeeperClient({ token: process.env.CELESTO_API_KEY });

const connect = await client.connect({
  subject: "customer_123",
  provider: "google_drive",
  projectName: "Default",
});

if (connect.status === "redirect") {
  console.log(connect.oauthUrl);
} else {
  console.log(connect.status);
}
```

If the response prints a URL, open it so the user can approve access.

Full Gatekeeper docs: https://docs.celesto.ai/celesto-sdk/gatekeeper

## Configuration

| Option | What it does |
| --- | --- |
| `token` | Celesto API key or JWT |
| `apiKey` | Alias for `token` |
| `baseUrl` | Custom Celesto API URL |
| `organizationId` | Sends the `X-Current-Organization` header |
| `timeoutMs` | Request timeout in milliseconds |
| `headers` | Extra headers to send with every request |

Pass these options as the second argument to `Computer.create()` or
`Computer.get()`, or to `new Celesto(...)` when using service clients.

JWT is a signed login token. Most users should use a Celesto API key.

## Errors

The SDK exports these error classes:

| Error | When it is used |
| --- | --- |
| `CelestoApiError` | The API returns an error status |
| `CelestoNetworkError` | The network request fails |
| `CelestoError` | Base class for all SDK errors |

## Develop Locally

If you are contributing and have `npm` installed, run these commands from the
repository's `js` directory:

```bash
npm install
npm test
npm run lint
npm run build
```

## License

Apache-2.0. The SDK is open source. Use of the Celesto platform is governed by
the Celesto Terms of Service: https://celesto.ai/legal/terms
