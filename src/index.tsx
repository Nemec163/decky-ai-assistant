import { staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { FaTerminal } from "react-icons/fa";
import { SETTINGS_ROUTE, TERMINAL_ROUTE } from "./lib/constants";
import { PluginPanel } from "./pages/PluginPanel";
import { TerminalPage } from "./pages/TerminalPage";
import { SettingsPage } from "./pages/settings/SettingsPage";

function registerRoutes() {
  routerHook.addRoute(TERMINAL_ROUTE, TerminalPage);
  routerHook.addRoute(SETTINGS_ROUTE, SettingsPage);
}

function unregisterRoutes() {
  routerHook.removeRoute(TERMINAL_ROUTE);
  routerHook.removeRoute(SETTINGS_ROUTE);
}

export default definePlugin(() => {
  registerRoutes();

  return {
    name: "Decky AI Assistant",
    titleView: <div className={staticClasses.Title}>Decky AI Assistant</div>,
    content: <PluginPanel />,
    icon: <FaTerminal />,
    onDismount() {
      unregisterRoutes();
    },
  };
});
