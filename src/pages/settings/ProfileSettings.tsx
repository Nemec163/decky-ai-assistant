import {
  DialogButton,
  Dropdown,
  Focusable,
  Router,
  staticClasses,
  type SingleDropdownOption,
} from "@decky/ui";
import { useState } from "react";
import { FaDownload, FaSignInAlt } from "react-icons/fa";
import {
  getCliProfileHealth,
  installAgentPack,
  openCliSetupAction,
  updatePermissionBypass,
  type CliProfileHealth,
} from "../../api/callables";
import { useProfileSetup } from "../../hooks/useProfileSetup";
import {
  DEFAULT_TERMINAL_COLS,
  DEFAULT_TERMINAL_ROWS,
  TERMINAL_ROUTE_BASE,
} from "../../lib/constants";
import { toMessage } from "../../lib/errors";
import { profileCommand, profileLabel } from "../../lib/profiles";
import { reloadDeckyPlugin } from "../../lib/reload";
import { showError, showToast } from "../../lib/toast";
import {
  DangerNote,
  ErrorBanner,
  IconLabel,
  SectionHeader,
  SettingRow,
  SettingToggle,
  StatusLine,
} from "../../ui/primitives";
import { buttonRowStyle, stackStyle } from "../../ui/styles";

function friendlyStatus(health: CliProfileHealth): string {
  if (health.can_launch) {
    return "Ready";
  }
  if (health.needs_login) {
    return "Needs sign-in";
  }
  if (health.status === "missing") {
    return "Not installed";
  }
  return "Installed";
}

export function ProfileSettings() {
  const {
    profiles,
    settingsProfile,
    setSettingsProfile,
    selectedProfile,
    selectedHealth,
    managedSetupSupported,
    setupPlans,
    agentPackPlan,
    setAgentPackPlan,
    agentPackResult,
    setAgentPackResult,
    permissionBypassPlan,
    setPermissionBypassPlan,
    setProfileHealth,
    error,
    setError,
    applyProfiles,
  } = useProfileSetup();

  const [busyLabel, setBusyLabel] = useState<string | null>(null);

  const profileOptions: SingleDropdownOption[] = profiles.map((profile) => ({
    data: profile.name,
    label: profileLabel(profile),
  }));
  const settingsProfileOption =
    profileOptions.find((option) => option.data === settingsProfile) ?? profileOptions[0];

  const reportError = (caught: unknown) => {
    setError(toMessage(caught));
    showError(caught);
  };

  const runProfileHealth = async () => {
    setBusyLabel("health");
    try {
      const result = await getCliProfileHealth();
      setProfileHealth(result);
      setError(null);
    } catch (caught) {
      reportError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const openSetupAction = async (action: "install" | "auth" | "install_auth") => {
    if (!selectedProfile || !managedSetupSupported) {
      return;
    }

    setBusyLabel(`setup-${action}`);
    try {
      const result = await openCliSetupAction({
        profile_name: selectedProfile.name,
        action,
        confirmed: true,
        cols: DEFAULT_TERMINAL_COLS,
        rows: DEFAULT_TERMINAL_ROWS,
      });
      setError(null);
      Router.Navigate(`${TERMINAL_ROUTE_BASE}/${result.session.id}`);
    } catch (caught) {
      reportError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const installNativePack = async () => {
    if (!selectedProfile || !agentPackPlan || agentPackPlan.status !== "ready") {
      return;
    }

    setBusyLabel("agent-pack");
    try {
      const result = await installAgentPack({
        profile_name: selectedProfile.name,
        confirmed: true,
      });
      setAgentPackPlan(result.plan);
      setAgentPackResult(result);
      setError(null);
      showToast({
        body: `${result.plan.display_name} assistant pack installed (${result.files_written} files). Reloading plugin...`,
      });
      await reloadDeckyPlugin();
    } catch (caught) {
      reportError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const setPermissionBypass = async (enabled: boolean) => {
    if (!selectedProfile) {
      return;
    }

    setBusyLabel("permission-bypass");
    try {
      const result = await updatePermissionBypass({
        profile_name: selectedProfile.name,
        enabled,
      });
      setPermissionBypassPlan(result.plan);
      applyProfiles(result);
      setError(null);
      showToast({
        body: enabled
          ? `${result.plan.display_name} permission bypass enabled. Restart existing sessions to apply.`
          : `${result.plan.display_name} permission bypass disabled.`,
        critical: enabled,
      });
    } catch (caught) {
      reportError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const setupPrimaryAction: "install_auth" | "auth" =
    selectedHealth?.can_launch || setupPlans?.auth?.status === "ready" ? "auth" : "install_auth";
  const setupPrimaryLabel =
    setupPrimaryAction === "auth" ? "Sign in" : "Install + sign in";
  const setupPrimaryIcon = setupPrimaryAction === "auth" ? <FaSignInAlt /> : <FaDownload />;
  const setupPlanForDisplay =
    setupPrimaryAction === "auth"
      ? setupPlans?.auth ?? setupPlans?.installAuth
      : setupPlans?.installAuth;

  return (
    <Focusable style={{ ...stackStyle, marginTop: "1rem" }}>
      {profileOptions.length > 0 ? (
        <SettingRow
          title="Profile"
          description={selectedProfile ? profileCommand(selectedProfile) : undefined}
          control={
            <Dropdown
              disabled={busyLabel !== null}
              menuLabel="CLI profile"
              onChange={(selection) => {
                const nextProfile = selection?.data;
                if (nextProfile) {
                  setSettingsProfile(String(nextProfile));
                }
              }}
              rgOptions={profileOptions}
              selectedOption={settingsProfile}
              strDefaultLabel={String(settingsProfileOption?.label ?? "Profile")}
            />
          }
        />
      ) : null}

      <DialogButton disabled={busyLabel !== null} onClick={() => runProfileHealth().catch(showError)}>
        {busyLabel === "health" ? "Checking..." : "Check status"}
      </DialogButton>
      {selectedHealth ? (
        <StatusLine label="Status" value={friendlyStatus(selectedHealth)} />
      ) : null}

      {managedSetupSupported ? (
        <Focusable style={{ ...stackStyle, paddingTop: "10px" }}>
          <SectionHeader title="Setup" />
          {setupPlanForDisplay?.message ? (
            <div className={staticClasses.Label}>{setupPlanForDisplay.message}</div>
          ) : null}
          <Focusable style={buttonRowStyle}>
            <DialogButton
              disabled={busyLabel !== null || setupPlanForDisplay?.status !== "ready"}
              onClick={() => openSetupAction(setupPrimaryAction).catch(showError)}
            >
              <IconLabel
                icon={setupPrimaryIcon}
                label={
                  busyLabel === `setup-${setupPrimaryAction}` ? "Opening..." : setupPrimaryLabel
                }
              />
            </DialogButton>
            <DialogButton
              disabled={busyLabel !== null || setupPlans?.install?.status !== "ready"}
              onClick={() => openSetupAction("install").catch(showError)}
            >
              <IconLabel
                icon={<FaDownload />}
                label={busyLabel === "setup-install" ? "Opening..." : "Update"}
              />
            </DialogButton>
          </Focusable>
        </Focusable>
      ) : null}

      {agentPackPlan ? (
        <Focusable style={{ ...stackStyle, paddingTop: "10px" }}>
          <SectionHeader
            title="Assistant Pack"
            description="Install Decky AI Assistant skills and tools into this CLI."
          />
          <StatusLine
            label="Status"
            value={agentPackResult?.installed ? "installed" : agentPackPlan.status}
          />
          {agentPackPlan.message ? (
            <div className={staticClasses.Label}>{agentPackPlan.message}</div>
          ) : null}
          <DialogButton
            disabled={busyLabel !== null || agentPackPlan.status !== "ready"}
            onClick={() => installNativePack().catch(showError)}
          >
            <IconLabel
              icon={<FaDownload />}
              label={busyLabel === "agent-pack" ? "Installing..." : "Install native pack"}
            />
          </DialogButton>
        </Focusable>
      ) : null}

      {permissionBypassPlan ? (
        <Focusable style={{ ...stackStyle, paddingTop: "10px" }}>
          <SectionHeader title="Permissions" />
          <SettingToggle
            title="Bypass permissions"
            description="Run this CLI with approvals disabled."
            checked={permissionBypassPlan.enabled}
            disabled={busyLabel !== null || permissionBypassPlan.status === "unsupported"}
            onChange={(enabled) => setPermissionBypass(enabled).catch(showError)}
          />
          <DangerNote
            message={`Danger: ${permissionBypassPlan.message}`}
          />
        </Focusable>
      ) : null}

      <ErrorBanner message={error} />
    </Focusable>
  );
}
