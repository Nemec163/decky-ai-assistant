import { SidebarNavigation } from "@decky/ui";
import { DiagnosticsSettings } from "./DiagnosticsSettings";
import { ProfileSettings } from "./ProfileSettings";
import { TerminalSettings } from "./TerminalSettings";
import { VoiceSettings } from "./VoiceSettings";

export function SettingsPage() {
  return (
    <SidebarNavigation
      title="Decky AI Assistant"
      showTitle
      pages={[
        {
          title: "Profiles",
          content: <ProfileSettings />,
        },
        {
          title: "Terminal",
          content: <TerminalSettings />,
        },
        {
          title: "Voice",
          content: <VoiceSettings />,
        },
        {
          title: "Diagnostics",
          content: <DiagnosticsSettings />,
        },
      ]}
    />
  );
}
