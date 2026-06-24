import { useCallback, useEffect, useState } from "react";
import {
  getAgentPackInstallPlan,
  getCliProfiles,
  getCliSetupPlan,
  getPermissionBypassPlan,
  type AgentPackInstallPlan,
  type AgentPackInstallResult,
  type CliProfileHealthResult,
  type CliProfileMutationResult,
  type CliProfilesResult,
  type CliProfileSummary,
  type CliSetupPlan,
  type PermissionBypassPlan,
} from "../api/callables";
import { toMessage } from "../lib/errors";
import { showError } from "../lib/toast";

export type SetupPlans = {
  install: CliSetupPlan | null;
  auth: CliSetupPlan | null;
  installAuth: CliSetupPlan | null;
};

const MANAGED_SETUP_PROFILES = ["codex", "claude"];

/**
 * Consolidates the name-keyed data loading for the Profiles settings page:
 * the initial profile list plus the per-selected-profile setup plans, agent
 * pack plan, and permission bypass plan. The component keeps form/busy state and
 * the mutation handlers; this hook owns the derived selection and the effects.
 */
export function useProfileSetup() {
  const [profiles, setProfiles] = useState<CliProfileSummary[]>([]);
  const [profileHealth, setProfileHealth] = useState<CliProfileHealthResult | null>(null);
  const [settingsProfile, setSettingsProfile] = useState("codex");
  const [setupPlans, setSetupPlans] = useState<SetupPlans | null>(null);
  const [agentPackPlan, setAgentPackPlan] = useState<AgentPackInstallPlan | null>(null);
  const [agentPackResult, setAgentPackResult] = useState<AgentPackInstallResult | null>(null);
  const [permissionBypassPlan, setPermissionBypassPlan] =
    useState<PermissionBypassPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedProfile = profiles.find((profile) => profile.name === settingsProfile);
  const selectedHealth = profileHealth?.profiles.find(
    (profile) => profile.name === settingsProfile,
  );
  const managedSetupSupported =
    selectedProfile?.profile_type === "built_in" &&
    MANAGED_SETUP_PROFILES.includes(selectedProfile.name);

  const reportError = useCallback((caught: unknown) => {
    setError(toMessage(caught));
    showError(caught);
  }, []);

  const applyProfiles = useCallback(
    (result: CliProfilesResult | CliProfileMutationResult) => {
      const nextProfiles = result.profiles;
      setProfiles(nextProfiles);
      setSettingsProfile((current) =>
        nextProfiles.some((profile) => profile.name === current)
          ? current
          : nextProfiles.find((profile) => profile.name === "codex")?.name ??
            nextProfiles[0]?.name ??
            "codex",
      );
    },
    [],
  );

  // Initial profile list.
  useEffect(() => {
    getCliProfiles()
      .then((result) => {
        applyProfiles(result);
        setError(null);
      })
      .catch(reportError);
  }, [applyProfiles, reportError]);

  // Setup plans for the selected managed profile.
  useEffect(() => {
    if (!selectedProfile || !managedSetupSupported) {
      setSetupPlans(null);
      return;
    }

    let cancelled = false;
    Promise.all([
      getCliSetupPlan({ profile_name: selectedProfile.name, action: "install" }),
      getCliSetupPlan({ profile_name: selectedProfile.name, action: "auth" }).catch(() => null),
      getCliSetupPlan({ profile_name: selectedProfile.name, action: "install_auth" }),
    ])
      .then(([install, auth, installAuth]) => {
        if (!cancelled) {
          setSetupPlans({
            install: install.plan,
            auth: auth?.plan ?? null,
            installAuth: installAuth.plan,
          });
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          reportError(caught);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [managedSetupSupported, reportError, selectedProfile?.name]);

  // Agent pack + permission bypass plans for the selected profile.
  useEffect(() => {
    if (!selectedProfile) {
      setAgentPackPlan(null);
      setAgentPackResult(null);
      setPermissionBypassPlan(null);
      return;
    }

    let cancelled = false;
    const agentPackRequest = managedSetupSupported
      ? getAgentPackInstallPlan({ profile_name: selectedProfile.name }).then(
          (result) => result.plan,
        )
      : Promise.resolve(null);

    Promise.all([
      agentPackRequest,
      getPermissionBypassPlan({ profile_name: selectedProfile.name }).then(
        (result) => result.plan,
      ),
    ])
      .then(([nextAgentPackPlan, nextPermissionBypassPlan]) => {
        if (!cancelled) {
          setAgentPackPlan(nextAgentPackPlan);
          setAgentPackResult(null);
          setPermissionBypassPlan(nextPermissionBypassPlan);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          reportError(caught);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [managedSetupSupported, reportError, selectedProfile?.name]);

  return {
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
    profileHealth,
    setProfileHealth,
    error,
    setError,
    applyProfiles,
  };
}
