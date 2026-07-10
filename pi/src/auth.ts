import { execFile as execFileCallback } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify, parseEnv } from "node:util";

const execFile = promisify(execFileCallback);

export const MISSING_CREDENTIALS_MESSAGE =
  "No Celesto credentials found. Run pip install celesto && celesto auth login, or export CELESTO_API_KEY.";

interface CredentialResolutionOptions {
  env?: NodeJS.ProcessEnv;
  readDotEnv?: (filePath: string) => Promise<string>;
  loadSavedApiKey?: () => Promise<string | undefined>;
}

function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

async function readDotEnvApiKey(
  cwd: string,
  readDotEnv: (filePath: string) => Promise<string>,
): Promise<string | undefined> {
  try {
    const contents = await readDotEnv(path.join(cwd, ".env"));
    return nonEmpty(parseEnv(contents).CELESTO_API_KEY);
  } catch {
    return undefined;
  }
}

async function loadCliApiKey(): Promise<string | undefined> {
  try {
    const { stdout } = await execFile("celesto", ["auth", "token"], {
      encoding: "utf8",
      timeout: 5_000,
      maxBuffer: 64 * 1024,
    });
    return nonEmpty(stdout);
  } catch {
    return undefined;
  }
}

/** Resolve Celesto credentials without exposing them to the remote computer. */
export async function resolveCelestoApiKey(
  cwd: string,
  options: CredentialResolutionOptions = {},
): Promise<string | undefined> {
  const env = options.env ?? process.env;
  const environmentKey = nonEmpty(env.CELESTO_API_KEY);
  if (environmentKey) return environmentKey;

  const dotEnvKey = await readDotEnvApiKey(
    cwd,
    options.readDotEnv ?? ((filePath) => readFile(filePath, "utf8")),
  );
  if (dotEnvKey) return dotEnvKey;

  return (options.loadSavedApiKey ?? loadCliApiKey)();
}

/** Resolve a local API key or return an actionable setup error. */
export async function requireCelestoApiKey(
  cwd: string,
  options: CredentialResolutionOptions = {},
): Promise<string> {
  const apiKey = await resolveCelestoApiKey(cwd, options);
  if (!apiKey) throw new Error(MISSING_CREDENTIALS_MESSAGE);
  return apiKey;
}
