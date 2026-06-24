import { DialogButton, Focusable, ToggleField, staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaDownload, FaHeartbeat, FaSyncAlt } from "react-icons/fa";
import {
  getCliProfileHealth,
  getPluginUpdatePlan,
  getReleaseChannel,
  pingBackend,
  setReleaseChannel,
  updatePluginToLatest,
  type CliProfileHealthResult,
  type PingResult,
  type PluginUpdatePlanResult,
  type ReleaseChannel,
} from "../../api/callables";
import { requestDeckyPluginUpdateInstall } from "../../lib/deckyPluginInstall";
import { reloadDeckyPlugin } from "../../lib/reload";
import { showError, showToast } from "../../lib/toast";
import { IconLabel, SectionHeader, StatusLine } from "../../ui/primitives";
import { stackStyle } from "../../ui/styles";

export function DiagnosticsSettings() {
  const [ping, setPing] = useState<PingResult | null>(null);
  const [profileHealth, setProfileHealth] = useState<CliProfileHealthResult | null>(null);
  const [pluginUpdate, setPluginUpdate] = useState<PluginUpdatePlanResult | null>(null);
  const [channel, setChannel] = useState<ReleaseChannel>("stable");
  const [busyLabel, setBusyLabel] = useState<string | null>(null);

  const checked = ping !== null && profileHealth !== null;
  const backendReady = ping?.modules.every((module) => module.available) ?? false;
  const launchable = profileHealth?.profiles.filter((profile) => profile.can_launch).length ?? 0;
  const totalProfiles = profileHealth?.profiles.length ?? 0;

  useEffect(() => {
    let active = true;
    getReleaseChannel()
      .then((result) => {
        if (active) {
          setChannel(result.channel);
        }
      })
      .catch(showError);
    return () => {
      active = false;
    };
  }, []);

  const runHealthCheck = async () => {
    setBusyLabel("health");
    try {
      const [pingResult, healthResult] = await Promise.all([
        pingBackend(),
        getCliProfileHealth(),
      ]);
      setPing(pingResult);
      setProfileHealth(healthResult);
    } catch (caught) {
      showError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const checkForUpdate = async () => {
    setBusyLabel("plugin-check");
    try {
      setPluginUpdate(await getPluginUpdatePlan());
    } catch (caught) {
      showError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const updatePlugin = async () => {
    setBusyLabel("plugin-update");
    try {
      const plan = await getPluginUpdatePlan();
      setPluginUpdate(plan);
      if (plan.status === "up_to_date") {
        showToast({ body: plan.message || "Plugin is up to date." });
        return;
      }
      if (plan.status !== "ready") {
        throw new Error(plan.message || "Plugin update is not available.");
      }

      try {
        await requestDeckyPluginUpdateInstall(plan);
        setPluginUpdate({
          ...plan,
          status: "install_requested",
          message: "Decky Loader install prompt opened. Confirm it to install the update.",
          reload_required: true,
        });
        showToast({
          body: `Confirm the Decky install prompt to install ${plan.latest_version}.`,
        });
        return;
      } catch (loaderInstallError) {
        console.warn("Decky Loader install API failed; falling back to backend updater.", loaderInstallError);
      }

      const result = await updatePluginToLatest({ confirmed: true });
      setPluginUpdate(result.plan);
      showToast({
        body: `Decky AI Assistant ${result.plan.latest_version} installed. Reloading plugin...`,
      });
      await reloadDeckyPlugin();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  const updateReleaseChannel = async (checked: boolean) => {
    const nextChannel: ReleaseChannel = checked ? "dev" : "stable";
    setBusyLabel("release-channel");
    try {
      const result = await setReleaseChannel({ channel: nextChannel });
      setChannel(result.channel);
      await checkForUpdate();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusyLabel(null);
    }
  };

  return (
    <Focusable style={{ ...stackStyle, marginTop: "1rem" }}>
      <DialogButton
        disabled={busyLabel !== null}
        onClick={() => runHealthCheck().catch(showError)}
      >
        <IconLabel
          icon={<FaHeartbeat />}
          label={busyLabel === "health" ? "Checking..." : "Run health check"}
        />
      </DialogButton>
      {checked ? (
        <Focusable style={stackStyle}>
          <StatusLine label="Backend" value={backendReady ? "ready" : "error"} />
          <StatusLine label="CLIs ready" value={`${launchable} / ${totalProfiles}`} />
        </Focusable>
      ) : (
        <div className={staticClasses.Label}>
          Checks the backend and how many CLIs are ready to launch.
        </div>
      )}

      <Focusable style={{ ...stackStyle, paddingTop: "10px" }}>
        <SectionHeader title="Plugin Update" />
        <ToggleField
          label="Dev channel (prereleases)"
          description="Dev pulls prerelease builds and may be unstable."
          checked={channel === "dev"}
          disabled={busyLabel !== null}
          onChange={(checked) => updateReleaseChannel(checked).catch(showError)}
        />
        {pluginUpdate ? (
          <Focusable style={stackStyle}>
            <StatusLine label="Channel" value={channel} />
            <StatusLine label="Installed" value={pluginUpdate.current_version} />
            <StatusLine label="Latest" value={pluginUpdate.latest_version || "not found"} />
            <StatusLine label="Status" value={pluginUpdate.status} />
            {pluginUpdate.message ? (
              <div className={staticClasses.Label}>{pluginUpdate.message}</div>
            ) : null}
          </Focusable>
        ) : (
          <StatusLine label="Status" value="not checked" />
        )}
        <DialogButton
          disabled={busyLabel !== null}
          onClick={() => checkForUpdate().catch(showError)}
        >
          <IconLabel
            icon={<FaSyncAlt />}
            label={busyLabel === "plugin-check" ? "Checking..." : "Check for update"}
          />
        </DialogButton>
        <DialogButton
          disabled={
            busyLabel !== null ||
            pluginUpdate?.status === "up_to_date" ||
            pluginUpdate?.status === "unavailable"
          }
          onClick={() => updatePlugin().catch(showError)}
        >
          <IconLabel
            icon={<FaDownload />}
            label={busyLabel === "plugin-update" ? "Updating..." : "Update plugin"}
          />
        </DialogButton>
      </Focusable>
    </Focusable>
  );
}
