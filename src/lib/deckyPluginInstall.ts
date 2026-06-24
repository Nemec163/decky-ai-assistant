import { type PluginUpdatePlan } from "../api/callables";

const PLUGIN_NAME = "Decky AI Assistant";
const DECKY_INSTALL_TYPE_UPDATE = 2;

type DeckyInstallBackendSurface = {
  callable?: <Args extends unknown[] = [], Result = void>(
    route: string,
  ) => (...args: Args) => Promise<Result>;
  call?: <Args extends unknown[] = [], Result = void>(
    route: string,
    ...args: Args
  ) => Promise<Result>;
};

type DeckyInstallGlobalSurface = typeof globalThis & {
  DeckyBackend?: DeckyInstallBackendSurface;
};

type InstallPluginArgs = [
  artifact: string,
  name?: string,
  version?: string,
  hash?: string | boolean,
  installType?: number,
];

export async function requestDeckyPluginUpdateInstall(plan: PluginUpdatePlan): Promise<void> {
  const artifact = plan.asset_url.trim();
  if (!artifact) {
    throw new Error("Plugin update asset URL is missing.");
  }

  const version = plan.latest_version || plan.tag_name.replace(/^v/, "") || "dev";
  const hash = normalizeSha256Digest(plan.asset_digest);
  const backend = (globalThis as DeckyInstallGlobalSurface).DeckyBackend;
  if (backend?.callable) {
    await backend.callable<InstallPluginArgs, void>("utilities/install_plugin")(
      artifact,
      PLUGIN_NAME,
      version,
      hash,
      DECKY_INSTALL_TYPE_UPDATE,
    );
    return;
  }
  if (backend?.call) {
    await backend.call<InstallPluginArgs, void>(
      "utilities/install_plugin",
      artifact,
      PLUGIN_NAME,
      version,
      hash,
      DECKY_INSTALL_TYPE_UPDATE,
    );
    return;
  }
  throw new Error("Decky Loader install API is unavailable in this runtime.");
}

function normalizeSha256Digest(value: string): string {
  const digest = value.trim().toLowerCase();
  if (digest.startsWith("sha256:")) {
    return digest.slice("sha256:".length);
  }
  return /^[a-f0-9]{64}$/.test(digest) ? digest : "";
}
