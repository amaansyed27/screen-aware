import net from "node:net";
import { spawn } from "node:child_process";
import { writeFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HOST = "127.0.0.1";
const DEFAULT_START_PORT = 5173;
const DEFAULT_ATTEMPTS = 50;

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function canBind(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen({ host: HOST, port });
  });
}

async function findOpenPort() {
  const startPort = parsePositiveInt(process.env.SCREEN_AWARE_DEV_PORT, DEFAULT_START_PORT);
  const attempts = parsePositiveInt(process.env.SCREEN_AWARE_DEV_PORT_ATTEMPTS, DEFAULT_ATTEMPTS);
  for (let offset = 0; offset < attempts; offset += 1) {
    const port = startPort + offset;
    if (await canBind(port)) {
      return port;
    }
  }
  throw new Error(
    `No available dev port found from ${startPort} to ${startPort + attempts - 1}. ` +
      "Set SCREEN_AWARE_DEV_PORT to choose a different starting port."
  );
}

function runTauri(port) {
  const extraArgs = process.argv.slice(2);
  const devUrl = `http://${HOST}:${port}`;
  const config = {
    build: {
      devUrl,
      beforeDevCommand: `npm run dev -- --port ${port} --strictPort`
    }
  };
  const configPath = path.join(os.tmpdir(), `screen-aware-tauri-dev-${process.pid}.json`);
  writeFileSync(configPath, JSON.stringify(config), "utf8");

  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const tauriEntrypoint = path.resolve(
    scriptDir,
    "..",
    "node_modules",
    "@tauri-apps",
    "cli",
    "tauri.js"
  );
  const args = [tauriEntrypoint, "dev", "--config", configPath, ...extraArgs];

  console.log(`[screen-aware] using companion dev server ${devUrl}`);

  const child = spawn(process.execPath, args, {
    stdio: "inherit",
    env: {
      ...process.env,
      SCREEN_AWARE_DEV_PORT: String(port)
    }
  });

  child.on("error", (error) => {
    rmSync(configPath, { force: true });
    console.error(`[screen-aware] failed to start Tauri dev: ${error.message}`);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    rmSync(configPath, { force: true });
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });
}

try {
  runTauri(await findOpenPort());
} catch (error) {
  console.error(`[screen-aware] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
