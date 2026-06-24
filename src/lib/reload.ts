const PLUGIN_NAME = "Decky AI Assistant";

type DeckyBackendSurface = {
  callable?: <Args extends unknown[] = [], Result = void>(
    route: string,
  ) => (...args: Args) => Promise<Result>;
  call?: <Args extends unknown[] = [], Result = void>(
    route: string,
    ...args: Args
  ) => Promise<Result>;
};

type SteamBrowserSurface = {
  RestartJSContext?: () => void;
};

type ReloadGlobalSurface = typeof globalThis & {
  DeckyBackend?: DeckyBackendSurface;
  SteamClient?: {
    Browser?: SteamBrowserSurface;
  };
};

export type ReloadResult = {
  ok: boolean;
  attempts: string[];
  message: string;
};

export async function reloadDeckyPlugin(): Promise<ReloadResult> {
  const surface = globalThis as ReloadGlobalSurface;
  const attempts: string[] = [];

  const backend = surface.DeckyBackend;
  if (backend?.callable) {
    attempts.push("loader/reload_plugin");
    try {
      await backend.callable<[string], void>("loader/reload_plugin")(PLUGIN_NAME);
      return {
        ok: true,
        attempts,
        message: "Decky plugin reload requested.",
      };
    } catch (caught) {
      console.warn("Decky plugin reload callable failed", caught);
    }
  } else if (backend?.call) {
    attempts.push("loader/reload_plugin");
    try {
      await backend.call<[string], void>("loader/reload_plugin", PLUGIN_NAME);
      return {
        ok: true,
        attempts,
        message: "Decky plugin reload requested.",
      };
    } catch (caught) {
      console.warn("Decky plugin reload call failed", caught);
    }
  }

  const restartJSContext = surface.SteamClient?.Browser?.RestartJSContext;
  if (restartJSContext) {
    attempts.push("SteamClient.Browser.RestartJSContext");
    window.setTimeout(() => restartJSContext(), 250);
    return {
      ok: true,
      attempts,
      message: "Steam JavaScript context restart requested.",
    };
  }

  attempts.push("window.location.reload");
  window.setTimeout(() => window.location.reload(), 250);
  return {
    ok: true,
    attempts,
    message: "Window reload requested.",
  };
}
