import assert from "node:assert/strict";
import test from "node:test";

import {
  MISSING_CREDENTIALS_MESSAGE,
  requireCelestoApiKey,
  resolveCelestoApiKey,
} from "../src/auth.js";

test("environment credentials take precedence", async () => {
  let readDotEnv = false;
  let loadSavedApiKey = false;

  const apiKey = await resolveCelestoApiKey("/project", {
    env: { CELESTO_API_KEY: "environment-key" },
    readDotEnv: async () => {
      readDotEnv = true;
      return "CELESTO_API_KEY=dotenv-key";
    },
    loadSavedApiKey: async () => {
      loadSavedApiKey = true;
      return "saved-key";
    },
  });

  assert.equal(apiKey, "environment-key");
  assert.equal(readDotEnv, false);
  assert.equal(loadSavedApiKey, false);
});

test("credentials can be loaded from the project .env", async () => {
  let requestedPath = "";
  let loadSavedApiKey = false;

  const apiKey = await resolveCelestoApiKey("/project", {
    env: {},
    readDotEnv: async (filePath) => {
      requestedPath = filePath;
      return 'OTHER=value\nCELESTO_API_KEY="dotenv-key"\n';
    },
    loadSavedApiKey: async () => {
      loadSavedApiKey = true;
      return "saved-key";
    },
  });

  assert.equal(apiKey, "dotenv-key");
  assert.equal(requestedPath, "/project/.env");
  assert.equal(loadSavedApiKey, false);
});

test("saved CLI credentials are used after environment sources miss", async () => {
  const apiKey = await resolveCelestoApiKey("/project", {
    env: {},
    readDotEnv: async () => {
      throw new Error("missing");
    },
    loadSavedApiKey: async () => "saved-key",
  });

  assert.equal(apiKey, "saved-key");
});

test("missing credentials return the setup command", async () => {
  await assert.rejects(
    requireCelestoApiKey("/project", {
      env: {},
      readDotEnv: async () => "OTHER=value\n",
      loadSavedApiKey: async () => undefined,
    }),
    new Error(MISSING_CREDENTIALS_MESSAGE),
  );
});
