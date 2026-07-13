import { callable } from "@decky/api";

export type ModuleStatus = {
  name: string;
  available: boolean;
  error: string | null;
};

export type PingResult = {
  plugin: string;
  mode: string;
  root: string;
  modules: ModuleStatus[];
};

export type CliProfileSummary = {
  name: string;
  display_name: string;
  executable: string;
  argv?: string[];
  risk: string;
  profile_type: string;
  permission_bypass_enabled: boolean;
};

export type CliProfilesResult = {
  profiles: CliProfileSummary[];
};

export type CliProfileHealth = {
  name: string;
  display_name: string;
  profile_type: string;
  status: string;
  auth_state: string;
  can_launch: boolean;
  needs_login: boolean;
  version: string | null;
  path: string | null;
  risk: string;
  messages: string[];
};

export type CliProfileHealthResult = {
  profiles: CliProfileHealth[];
};

export type CliSetupPlan = {
  name: string;
  display_name: string;
  action: string;
  status: string;
  argv: string[];
  risk: string;
  npm_package: string | null;
  install_prefix: string | null;
  bin_dir: string | null;
  auth_argv: string[];
  path: string | null;
  error: string | null;
  message: string;
};

export type CliSetupPlanResult = {
  plan: CliSetupPlan;
};

export type AgentPackInstallPlan = {
  target: string;
  display_name: string;
  status: string;
  risk: string;
  source_dir: string | null;
  install_dir: string | null;
  write_paths: string[];
  message: string;
};

export type AgentPackInstallPlanResult = {
  plan: AgentPackInstallPlan;
};

export type AgentPackInstallResult = {
  plan: AgentPackInstallPlan;
  installed: boolean;
  files_written: number;
  directories_written: number;
};

export type ReleaseChannel = "stable" | "dev";

export type PluginUpdatePlan = {
  status: "ready" | "up_to_date" | "unavailable" | "installed" | string;
  risk: string;
  channel: ReleaseChannel;
  current_version: string;
  latest_version: string;
  tag_name: string;
  asset_name: string;
  asset_url: string;
  asset_digest: string;
  html_url: string;
  message: string;
  reload_required: boolean;
};

export type PluginUpdatePlanResult = PluginUpdatePlan;

export type PluginUpdateResult = {
  plan: PluginUpdatePlan;
  installed: boolean;
  files_written: number;
  directories_written: number;
  bytes_downloaded: number;
  sha256: string;
  reload_required: boolean;
};

export type PermissionBypassPlan = {
  name: string;
  display_name: string;
  status: string;
  risk: string;
  enabled: boolean;
  bypass_args: string[];
  message: string;
};

export type PermissionBypassPlanResult = {
  plan: PermissionBypassPlan;
};

export type PermissionBypassUpdateResult = PermissionBypassPlanResult & {
  profiles: CliProfileSummary[];
};

export type StoragePlanEntry = {
  section: string;
  path: string;
  label: string;
  max_depth: number;
  follow_symlinks: boolean;
};

export type StoragePlanResult = {
  entries: StoragePlanEntry[];
};

export type TerminalConfig = {
  font_family: string;
  font_size: number;
  use_dpad: boolean;
  dpad_mode: "arrows" | "scroll";
  disable_virtual_keyboard: boolean;
  extra_keys: boolean;
  auto_copy_selection: boolean;
  voice_input: boolean;
  voice_prefer_native_cli: boolean;
};

export type TerminalSessionSnapshot = {
  id: string;
  profile_name: string;
  display_name: string;
  pid: number;
  argv: string[];
  cwd: string | null;
  cols: number;
  rows: number;
  started_at: number;
  running: boolean;
};

export type TerminalSessionsResult = {
  sessions: TerminalSessionSnapshot[];
};

export type TerminalSessionResult = {
  session: TerminalSessionSnapshot;
};

export type TerminalReadResult = {
  data: string;
  session: TerminalSessionSnapshot;
  links: string[];
};

export type TerminalLinksResult = {
  links: string[];
  output_tail?: string;
};

export type ClipboardReadResult = {
  text: string;
  source: string | null;
  error: string | null;
};

export type VoiceTranscriptionConfig = {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key_required: boolean;
  api_key_configured: boolean;
};

export type OpenTerminalProfileRequest = {
  profile_name: string;
  cols: number;
  rows: number;
};

export type OpenCliSetupActionRequest = OpenTerminalProfileRequest & {
  action: "install" | "auth" | "install_auth";
};

export type SessionIdRequest = {
  session_id: string;
};

export type ReadTerminalSessionRequest = SessionIdRequest & {
  max_bytes: number;
  timeout_seconds: number;
};

export type WriteTerminalSessionRequest = SessionIdRequest & {
  data: string;
};

export type ResizeTerminalSessionRequest = SessionIdRequest & {
  cols: number;
  rows: number;
};

export type AddCliProfileRequest = {
  name?: string;
  display_name?: string;
  command: string;
};

export type RemoveCliProfileRequest = {
  name: string;
};

export type TranscribeVoiceAudioRequest = {
  audio_base64: string;
  content_type: string;
  filename: string;
};

export type VoiceTranscriptionConfigUpdate = Partial<
  Pick<VoiceTranscriptionConfig, "enabled" | "base_url" | "model">
> & {
  api_key?: string;
  clear_api_key?: boolean;
};

export type CliProfileMutationResult = {
  profile?: CliProfileSummary;
  removed?: string;
  profiles: CliProfileSummary[];
};

export const pingBackend = callable<[], PingResult>("ping");
export const getCliProfiles = callable<[], CliProfilesResult>("get_cli_profiles");
export const getCliProfileHealth = callable<[], CliProfileHealthResult>(
  "get_cli_profile_health",
);
export const getCliSetupPlan = callable<
  [{ profile_name: string; action: "install" | "auth" | "install_auth" }],
  CliSetupPlanResult
>("get_cli_setup_plan");
export const openCliSetupAction = callable<
  [OpenCliSetupActionRequest],
  TerminalSessionResult
>("open_cli_setup_action");
export const getAgentPackInstallPlan = callable<
  [{ profile_name: string }],
  AgentPackInstallPlanResult
>("get_agent_pack_install_plan");
export const installAgentPack = callable<
  [{ profile_name: string }],
  AgentPackInstallResult
>("install_agent_pack");
export const getPluginUpdatePlan = callable<[], PluginUpdatePlanResult>(
  "get_plugin_update_plan",
);
export const getReleaseChannel = callable<[], { channel: ReleaseChannel }>(
  "get_release_channel",
);
export const setReleaseChannel = callable<
  [{ channel: ReleaseChannel }],
  { channel: ReleaseChannel }
>("set_release_channel");
export const updatePluginToLatest = callable<
  [{}],
  PluginUpdateResult
>("update_plugin_to_latest");
export const getPermissionBypassPlan = callable<
  [{ profile_name: string }],
  PermissionBypassPlanResult
>("get_permission_bypass_plan");
export const updatePermissionBypass = callable<
  [{ profile_name: string; enabled: boolean }],
  PermissionBypassUpdateResult
>("update_permission_bypass");
export const addCliProfile = callable<[AddCliProfileRequest], CliProfileMutationResult>(
  "add_cli_profile",
);
export const removeCliProfile = callable<
  [RemoveCliProfileRequest],
  CliProfileMutationResult
>("remove_cli_profile");
export const getTerminalConfig = callable<[], TerminalConfig>("get_terminal_config");
export const updateTerminalConfig = callable<[Partial<TerminalConfig>], TerminalConfig>(
  "update_terminal_config",
);
export const getVoiceTranscriptionConfig = callable<[], VoiceTranscriptionConfig>(
  "get_voice_transcription_config",
);
export const updateVoiceTranscriptionConfig = callable<
  [VoiceTranscriptionConfigUpdate],
  VoiceTranscriptionConfig
>("update_voice_transcription_config");
export type VoiceCaptureStartResult = {
  recording: boolean;
  tool: string;
  error?: string | null;
};
export type VoiceCaptureStopResult = {
  text: string;
  error?: string | null;
  audio_bytes?: number;
  duration_seconds?: number;
  sample_rate?: number;
  channels?: number;
};
export const startVoiceCapture = callable<[], VoiceCaptureStartResult>("start_voice_capture");
export const stopVoiceCapture = callable<[], VoiceCaptureStopResult>("stop_voice_capture");
export const cancelVoiceCapture = callable<[], { cancelled: boolean }>("cancel_voice_capture");
export const transcribeVoiceAudio = callable<
  [TranscribeVoiceAudioRequest],
  { text: string }
>("transcribe_voice_audio");
export const getStoragePlan = callable<[], StoragePlanResult>("get_storage_plan");
export const listTerminalSessions = callable<[], TerminalSessionsResult>(
  "list_terminal_sessions",
);
export const openTerminalProfile = callable<
  [OpenTerminalProfileRequest],
  TerminalSessionResult
>("open_terminal_profile");
export const readTerminalSession = callable<
  [ReadTerminalSessionRequest],
  TerminalReadResult
>("read_terminal_session");
export const getTerminalSessionLinks = callable<[SessionIdRequest], TerminalLinksResult>(
  "get_terminal_session_links",
);
export const clearTerminalSessionLinks = callable<[SessionIdRequest], { links: string[] }>(
  "clear_terminal_session_links",
);
export const readBackendClipboard = callable<[], ClipboardReadResult>(
  "read_clipboard_text",
);
export const writeTerminalSession = callable<
  [WriteTerminalSessionRequest],
  { bytes_written: number }
>("write_terminal_session");
export const resizeTerminalSession = callable<
  [ResizeTerminalSessionRequest],
  TerminalSessionResult
>("resize_terminal_session");
export const restartTerminalSession = callable<[SessionIdRequest], TerminalSessionResult>(
  "restart_terminal_session",
);
export const stopTerminalSession = callable<
  [SessionIdRequest],
  { stopped: boolean; session_id: string }
>("stop_terminal_session");
