# Celesto SDK (Gatekeeper)

Node-only TypeScript SDK for Celesto's Gatekeeper API (`/v1/gatekeeper`).

## Install

```bash
npm install @celestoai/sdk
```

## Quickstart

```ts
import { GatekeeperClient } from "@celestoai/sdk/gatekeeper";

const client = new GatekeeperClient({
  baseUrl: "https://api.celesto.ai",
  token: process.env.CELESTO_API_KEY,
  // If using JWT and multiple orgs, set the org context:
  // organizationId: "org_123",
});

const connect = await client.connect({
  subject: "customer_123",
  provider: "google_drive",
  projectName: "Default",
});

if (connect.status === "redirect") {
  console.log("OAuth URL:", connect.oauthUrl);
}
```

## Documentation

```
https://docs.celesto.ai/celesto-sdk/gatekeeper
```

## Notes

- `token` accepts either a Celesto API key or a JWT.
- `organizationId` adds the `X-Current-Organization` header.
- Requires Node 18+ for built-in `fetch`.

## License

Apache-2.0. The SDK is open source; use of the Celesto platform is governed by the Celesto Terms of Service:
```
https://celesto.ai/legal/terms
```
