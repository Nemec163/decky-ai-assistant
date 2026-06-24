import {
  DialogButton,
  Router,
  SteamSpinner,
} from "@decky/ui";
import { type CSSProperties, useEffect, useState } from "react";
import { FaCog, FaInfoCircle, FaPlay, FaTerminal, FaTimesCircle } from "react-icons/fa";
import {
  getCliProfileHealth,
  getCliProfiles,
  listTerminalSessions,
  openTerminalProfile,
  stopTerminalSession,
  type CliProfileSummary,
  type TerminalSessionSnapshot,
} from "../api/callables";
import {
  DEFAULT_TERMINAL_COLS,
  DEFAULT_TERMINAL_ROWS,
  TERMINAL_ROUTE_BASE,
} from "../lib/constants";
import { toMessage } from "../lib/errors";
import { navigateToSettings, shortSessionId } from "../lib/profiles";
import { showError } from "../lib/toast";
import { EmptyState, ErrorBanner, IconLabel, SectionHeader } from "../ui/primitives";
import { sidePanelStyle } from "../ui/styles";

const terminalSessionRowStyle: CSSProperties = {
  alignItems: "stretch",
  display: "flex",
  gap: "8px",
  justifyContent: "center",
  width: "100%",
};

const panelButtonListStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "10px",
  width: "100%",
};

const closeTerminalButtonStyle: CSSProperties = {
  alignItems: "center",
  boxSizing: "border-box",
  display: "flex",
  flex: "0 0 40px",
  height: "40px",
  justifyContent: "center",
  lineHeight: 1,
  minWidth: "40px",
  padding: 0,
  width: "40px",
};

const closeTerminalIconStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  height: "100%",
  justifyContent: "center",
  lineHeight: 1,
  width: "100%",
};

const resumeTerminalButtonStyle: CSSProperties = {
  flexGrow: 1,
  justifyContent: "flex-start",
  minWidth: 0,
  overflow: "hidden",
  padding: "8px 10px",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  width: 0,
};

const fullWidthButtonStyle: CSSProperties = {
  justifyContent: "flex-start",
  minWidth: 0,
  width: "100%",
};

export function PluginPanel() {
  const [loading, setLoading] = useState(true);
  const [profiles, setProfiles] = useState<CliProfileSummary[]>([]);
  const [sessions, setSessions] = useState<TerminalSessionSnapshot[]>([]);
  const [busyProfile, setBusyProfile] = useState<string | null>(null);
  const [closingSessionId, setClosingSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeSessions = sessions.filter((item) => item.running);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getCliProfiles(),
      getCliProfileHealth(),
      listTerminalSessions().catch(() => ({ sessions: [] })),
    ])
      .then(([result, healthResult, sessionResult]) => {
        if (!cancelled) {
          const healthByName = new Map(
            healthResult.profiles.map((profile) => [profile.name, profile]),
          );
          setProfiles(
            result.profiles.filter((profile) => healthByName.get(profile.name)?.can_launch),
          );
          setSessions(sessionResult.sessions);
          setError(null);
          setLoading(false);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(toMessage(caught, "Could not load plugin panel."));
          showError(caught, "Could not load plugin panel.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resumeSession = (session: TerminalSessionSnapshot) => {
    Router.CloseSideMenus();
    Router.Navigate(`${TERMINAL_ROUTE_BASE}/${session.id}`);
  };

  const openProfile = async (profile: CliProfileSummary) => {
    setBusyProfile(profile.name);
    try {
      const result = await openTerminalProfile({
        profile_name: profile.name,
        cols: DEFAULT_TERMINAL_COLS,
        rows: DEFAULT_TERMINAL_ROWS,
      });
      setSessions((current) => [
        result.session,
        ...current.filter((session) => session.id !== result.session.id),
      ]);
      setError(null);
      Router.CloseSideMenus();
      Router.Navigate(`${TERMINAL_ROUTE_BASE}/${result.session.id}`);
    } catch (caught) {
      setError(toMessage(caught, "Could not open terminal."));
      showError(caught, "Could not open terminal.");
    } finally {
      setBusyProfile(null);
    }
  };

  const closeSession = async (session: TerminalSessionSnapshot) => {
    setClosingSessionId(session.id);
    try {
      await stopTerminalSession({ session_id: session.id });
      setSessions((current) => current.filter((item) => item.id !== session.id));
      setError(null);
    } catch (caught) {
      setError(toMessage(caught, "Could not close terminal."));
      showError(caught, "Could not close terminal.");
    } finally {
      setClosingSessionId(null);
    }
  };

  if (loading) {
    return (
      <div style={sidePanelStyle}>
        <SteamSpinner />
      </div>
    );
  }

  return (
    <div style={sidePanelStyle}>
      {profiles.length > 0 ? (
        <>
          <SectionHeader title="Launch" />
          <div style={panelButtonListStyle}>
            {profiles.map((profile) => (
              <DialogButton
                disabled={busyProfile !== null}
                key={profile.name}
                onClick={() => openProfile(profile)}
                style={fullWidthButtonStyle}
              >
                <IconLabel
                  icon={<FaPlay />}
                  label={busyProfile === profile.name ? "Opening..." : profile.display_name}
                />
              </DialogButton>
            ))}
          </div>
        </>
      ) : null}
      {!loading && profiles.length === 0 && activeSessions.length === 0 ? (
        <EmptyState
          icon={<FaInfoCircle />}
          title="No AI CLIs detected"
          description="Open Settings to install or authorize a CLI profile."
        />
      ) : null}
      <div style={panelButtonListStyle}>
        <DialogButton onClick={navigateToSettings} style={fullWidthButtonStyle}>
          <IconLabel icon={<FaCog />} label="Settings" />
        </DialogButton>
      </div>
      {activeSessions.length > 0 ? (
        <div style={panelButtonListStyle}>
          <SectionHeader title="Active terminals" />
          <div style={panelButtonListStyle}>
            {activeSessions.map((session) => (
              <div key={session.id} style={terminalSessionRowStyle}>
                <DialogButton
                  disabled={closingSessionId === session.id}
                  onClick={() => resumeSession(session)}
                  style={resumeTerminalButtonStyle}
                >
                  <IconLabel
                    icon={<FaTerminal />}
                    label={`${session.display_name} / ${shortSessionId(session)}`}
                  />
                </DialogButton>
                <DialogButton
                  aria-label={`Close ${session.display_name} terminal`}
                  disabled={closingSessionId !== null}
                  onClick={() => closeSession(session)}
                  style={closeTerminalButtonStyle}
                >
                  <span
                    style={closeTerminalIconStyle}
                    title={`Close ${session.display_name} terminal`}
                  >
                    <FaTimesCircle />
                  </span>
                </DialogButton>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <ErrorBanner message={error} />
    </div>
  );
}
