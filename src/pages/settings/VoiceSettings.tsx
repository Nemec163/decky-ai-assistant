import { Focusable, SteamSpinner, TextField } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaTrash } from "react-icons/fa";
import {
  getTerminalConfig,
  getVoiceTranscriptionConfig,
  updateTerminalConfig,
  updateVoiceTranscriptionConfig,
  type TerminalConfig,
  type VoiceTranscriptionConfig,
  type VoiceTranscriptionConfigUpdate,
} from "../../api/callables";
import { toMessage } from "../../lib/errors";
import { showError } from "../../lib/toast";
import {
  ActionButton,
  DeckyTextField,
  ErrorBanner,
  SectionHeader,
  SettingField,
  SettingToggle,
} from "../../ui/primitives";
import { buttonRowStyle, stackStyle } from "../../ui/styles";

export function VoiceSettings() {
  const [config, setConfig] = useState<TerminalConfig | null>(null);
  const [voiceApiConfig, setVoiceApiConfig] = useState<VoiceTranscriptionConfig | null>(null);
  const [voiceApiKey, setVoiceApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getTerminalConfig(), getVoiceTranscriptionConfig()])
      .then(([terminalResult, voiceApiResult]) => {
        setConfig(terminalResult);
        setVoiceApiConfig(voiceApiResult);
        setError(null);
      })
      .catch((caught) => {
        setError(toMessage(caught));
        showError(caught, "Could not load voice settings.");
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
      showError(caught, "Could not update voice settings.");
    }
  };

  const updateVoiceApiConfig = async (patch: VoiceTranscriptionConfigUpdate) => {
    if (!voiceApiConfig) {
      return;
    }
    const optimistic = { ...voiceApiConfig, ...patch };
    setVoiceApiConfig({
      ...optimistic,
      api_key_configured:
        patch.clear_api_key ? false : Boolean(patch.api_key) || voiceApiConfig.api_key_configured,
    });
    try {
      const result = await updateVoiceTranscriptionConfig(patch);
      setVoiceApiConfig(result);
      if (patch.api_key || patch.clear_api_key) {
        setVoiceApiKey("");
      }
      setError(null);
    } catch (caught) {
      setVoiceApiConfig(voiceApiConfig);
      setError(toMessage(caught));
      showError(caught, "Could not update voice API settings.");
    }
  };

  if (!config || !voiceApiConfig) {
    return <SteamSpinner />;
  }

  const keyStatus = voiceApiConfig.api_key_required
    ? voiceApiConfig.api_key_configured
      ? "Key saved."
      : "Key required for this endpoint."
    : "Key optional for this endpoint.";

  return (
    <Focusable style={{ ...stackStyle, marginTop: "1rem" }}>
      <SettingToggle
        title="Voice Input"
        description="Show the microphone button on terminal pages."
        checked={config.voice_input}
        onChange={(checked) => updateConfig({ voice_input: checked }).catch(showError)}
      />
      <SettingToggle
        title="Prefer Native Voice"
        description="Use the CLI's built-in voice when it supports it."
        checked={config.voice_prefer_native_cli}
        onChange={(checked) =>
          updateConfig({ voice_prefer_native_cli: checked }).catch(showError)
        }
      />

      <SectionHeader title="External transcription" />
      <SettingToggle
        title="External Voice API"
        description="Send recorded audio to an OpenAI-compatible endpoint."
        checked={voiceApiConfig.enabled}
        onChange={(checked) => updateVoiceApiConfig({ enabled: checked }).catch(showError)}
      />
      {voiceApiConfig.enabled ? (
        <>
          <SettingField title="Endpoint URL">
            <TextField
              value={voiceApiConfig.base_url}
              onChange={(event) =>
                updateVoiceApiConfig({ base_url: event.currentTarget.value }).catch(showError)
              }
            />
          </SettingField>
          <SettingField title="Model" description="e.g. gpt-4o-mini-transcribe">
            <TextField
              value={voiceApiConfig.model}
              onChange={(event) =>
                updateVoiceApiConfig({ model: event.currentTarget.value }).catch(showError)
              }
            />
          </SettingField>
          <SettingField title="API Key" description={keyStatus}>
            <DeckyTextField
              type="password"
              value={voiceApiKey}
              placeholder={voiceApiConfig.api_key_configured ? "Saved — paste to replace" : "Paste API key"}
              onChange={(event: { currentTarget: HTMLInputElement }) =>
                setVoiceApiKey(event.currentTarget.value)
              }
              onBlur={() => {
                const nextKey = voiceApiKey.trim();
                if (nextKey) {
                  updateVoiceApiConfig({ api_key: nextKey }).catch(showError);
                }
              }}
            />
          </SettingField>
          {voiceApiConfig.api_key_configured ? (
            <Focusable style={{ ...buttonRowStyle, justifyContent: "flex-end" }}>
              <ActionButton
                icon={<FaTrash />}
                label="Clear key"
                onClick={() => updateVoiceApiConfig({ clear_api_key: true }).catch(showError)}
              />
            </Focusable>
          ) : null}
        </>
      ) : null}
      <ErrorBanner message={error} />
    </Focusable>
  );
}
