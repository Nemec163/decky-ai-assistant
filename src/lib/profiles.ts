import { Router } from "@decky/ui";
import { type CliProfileSummary, type TerminalSessionSnapshot } from "../api/callables";
import { SETTINGS_ROUTE } from "./constants";

export function profileCommand(profile: CliProfileSummary | undefined) {
  if (!profile) {
    return "unknown";
  }
  const argv = profile.argv && profile.argv.length > 0 ? profile.argv : [profile.executable];
  return argv.join(" ");
}

export function profileLabel(profile: CliProfileSummary) {
  return `${profile.display_name} (${profile.executable})`;
}

export function shortSessionId(session: TerminalSessionSnapshot) {
  return session.id.slice(0, 8);
}

export function navigateToSettings() {
  Router.CloseSideMenus();
  Router.Navigate(SETTINGS_ROUTE);
}
