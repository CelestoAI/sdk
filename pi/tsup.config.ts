import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "tsup";

const packageRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  noExternal: ["@celestoai/sdk", "dotenv"],
  // Bundle the SDK source from this repository so Pi and SDK releases cannot drift.
  esbuildOptions(options) {
    options.alias = {
      ...options.alias,
      "@celestoai/sdk": path.resolve(packageRoot, "../ts/src/index.ts"),
      dotenv: path.resolve(packageRoot, "node_modules/dotenv/lib/main.js"),
    };
  },
});
