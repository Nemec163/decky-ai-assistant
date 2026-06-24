import { Router } from "@decky/ui";

/** Open a URL in the Deck's external browser, falling back across host surfaces. */
export function openExternalUrl(value: string) {
  const deckyRouter = Router as typeof Router & {
    NavigateToExternalWeb?: (url: string) => void;
  };
  if (typeof deckyRouter.NavigateToExternalWeb === "function") {
    deckyRouter.NavigateToExternalWeb(value);
    return true;
  }

  const steamClient = (window as Window & {
    SteamClient?: { System?: { OpenInSystemBrowser?: (url: string) => void } };
  }).SteamClient;
  if (typeof steamClient?.System?.OpenInSystemBrowser === "function") {
    steamClient.System.OpenInSystemBrowser(value);
    return true;
  }

  const openedWindow = window.open(value, "_blank", "noopener,noreferrer");
  return Boolean(openedWindow);
}
