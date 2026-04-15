// test.mjs (Node 18+)
  import { GatekeeperClient } from "@celestoai/sdk/gatekeeper";

  const client = new GatekeeperClient({
    token: process.env.CELESTO_API_KEY,
  });

  const res = await client.listConnections({ projectName: "Default" });
  console.log(res);

