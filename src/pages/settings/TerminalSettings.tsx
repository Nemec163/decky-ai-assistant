import { Dropdown, Focusable, SteamSpinner, TextField } from "@decky/ui";
import { useEffect, useState } from "react";
import {
  getTerminalConfig,
  updateTerminalConfig,
  type TerminalConfig,
} from "../../api/callables";
import { toMessage } from "../../lib/errors";
import { showError } from "../../lib/toast";
import { ErrorBanner, SettingField, SettingRow, SettingToggle } from "../../ui/primitives";
import { stackStyle } from "../../ui/styles";

const dpadModeOptions = [
  { data: "arrows", label: "Arrow keys" },
  { data: "scroll", label: "Scroll" },
];

export function TerminalSettings() {
  const [config, setConfig] = useState<TerminalConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTerminalConfig()
      .then((terminalResult) => {
        setConfig(terminalResult);
        setError(null);
      })
      .catch((caught) => {
        setError(toMessage(caught));
        showError(caught, "Could not load terminal settings.");
      });
  }, []);

  const updateConfig = async (patch: Partial<TerminalConfig>) => {
    if (!config) {
      return;
    }
    const optimistic = { ...config, ...patch };
    setConfig(optimistic);
    try {
      const result = await updateTerminalConfig(patch);
      setConfig(result);
      setError(null);
    } catch (caught) {
      setConfig(config);
      setError(toMessage(caught));
      showError(caught, "Could not update terminal settings.");
    }
  };

  if (!config) {
    return <SteamSpinner />;
  }

  return (
    <Focusable style={{ ...stackStyle, marginTop: "1rem" }}>
      <SettingField
        title="Font Family"
        description="Monospace font for the terminal."
      >
        <TextField
          value={config.font_family}
          onChange={(event) => updateConfig({ font_family: event.currentTarget.value })}
        />
      </SettingField>
      <SettingRow
        title="Font Size"
        control={
          <TextField
            mustBeNumeric
            value={String(config.font_size)}
            onChange={(event) => {
              const nextValue = Number.parseInt(event.currentTarget.value, 10);
              if (!Number.isNaN(nextValue)) {
                updateConfig({ font_size: nextValue }).catch(showError);
              }
            }}
          />
        }
      />
      <SettingRow
        title="D-Pad Mode"
        description="Move the cursor with arrow keys, or scroll the output."
        control={
          <Dropdown
            rgOptions={dpadModeOptions}
            selectedOption={config.dpad_mode}
            onChange={(option) => {
              const mode = option.data as TerminalConfig["dpad_mode"];
              updateConfig({ dpad_mode: mode, use_dpad: mode === "arrows" }).catch(showError);
            }}
          />
        }
      />
      <SettingToggle
        title="Extra Keys"
        description="Show Esc, arrow, and Ctrl keys below the terminal."
        checked={config.extra_keys}
        onChange={(checked) => updateConfig({ extra_keys: checked }).catch(showError)}
      />
      <SettingToggle
        title="Disable Virtual Keyboard"
        description="Type directly without opening the Steam keyboard."
        checked={config.disable_virtual_keyboard}
        onChange={(checked) =>
          updateConfig({ disable_virtual_keyboard: checked }).catch(showError)
        }
      />
      <SettingToggle
        title="Auto-Copy Selection"
        description="Copy selected text to the clipboard automatically."
        checked={config.auto_copy_selection}
        onChange={(checked) =>
          updateConfig({ auto_copy_selection: checked }).catch(showError)
        }
      />
      <ErrorBanner message={error} />
    </Focusable>
  );
}
