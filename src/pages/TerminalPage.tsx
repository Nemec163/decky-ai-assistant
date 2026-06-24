import {
  Focusable,
  GamepadButton,
  Menu,
  MenuItem,
  Navigation,
  NavEntryPositionPreferences,
  SteamSpinner,
  showContextMenu,
  staticClasses,
  useParams,
  type GamepadEvent,
} from "@decky/ui";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  FaBan,
  FaChevronLeft,
  FaEllipsisV,
  FaKeyboard,
  FaMicrophone,
  FaPaste,
  FaQuestionCircle,
  FaRegCopy,
  FaRedo,
  FaStop,
  FaTerminal,
  FaTimesCircle,
} from "react-icons/fa";
import {
  cancelVoiceCapture,
  clearTerminalSessionLinks,
  getVoiceTranscriptionConfig,
  startVoiceCapture,
  stopVoiceCapture,
  writeTerminalSession,
  stopTerminalSession,
  type VoiceTranscriptionConfig,
} from "../api/callables";
import { copyTextToClipboard, readTextFromClipboard } from "../lib/clipboard";
import { toMessage } from "../lib/errors";
import { openExternalUrl } from "../lib/external";
import { useDelayedFocus } from "../lib/focus";
import { shortSessionId } from "../lib/profiles";
import { showError, showToast } from "../lib/toast";
import { useTerminalSession } from "../hooks/useTerminalSession";
import { DeckyTextField, TinyButton, type DeckyTextFieldHandle } from "../ui/primitives";
import {
  terminalHostStyle,
  terminalPageStyle,
  toolbarActionsStyle,
  toolbarStyle,
} from "../ui/styles";
import { AuthLinkPanel } from "./terminal/AuthLinkPanel";
import { ExtraKeysBar } from "./terminal/ExtraKeysBar";
import { XTERM_INLINE_CSS } from "./terminal/xtermStyles";

const WHEEL_PIXEL_LINE_HEIGHT = 18;
// Time given to the CLI to enable its tap voice mode after `/voice tap` before
// the first space keystroke that starts listening.
const NATIVE_VOICE_ENABLE_DELAY_MS = 800;

// Measured from Steam Deck Gaming Mode screenshots: 1280x800 frame with
// 60px bottom footer overlay and a small button-scale gap.
const STEAM_DECK_NORMAL_FOOTER_GAP_PX = 16;
const TERMINAL_SCROLL_SPEED = 3;

const normalTerminalPageStyle = {
  ...terminalPageStyle,
  height: `calc(100dvh - ${STEAM_DECK_NORMAL_FOOTER_GAP_PX}px)`,
  paddingBottom: `calc(1rem + ${STEAM_DECK_NORMAL_FOOTER_GAP_PX}px)`,
} as const;

const keyboardTriggerWrapperStyle: CSSProperties = {
  height: 0,
  left: 0,
  margin: 0,
  padding: 0,
  position: "absolute",
  top: 0,
  visibility: "hidden",
  width: 0,
  zIndex: -10,
};

const shortcutModalBodyStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 0,
  minWidth: 0,
  overflowY: "auto",
  paddingRight: "4px",
};

const shortcutModalRowStyle: CSSProperties = {
  alignItems: "center",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
  display: "grid",
  gap: "14px",
  gridTemplateColumns: "minmax(6.5rem, auto) minmax(0, 1fr)",
  padding: "5px 0",
};

const shortcutKeyStyle: CSSProperties = {
  fontFamily: "Menlo, Consolas, monospace",
  fontSize: "12px",
  lineHeight: "18px",
  opacity: 0.86,
  whiteSpace: "nowrap",
};

const shortcutDescriptionStyle: CSSProperties = {
  fontSize: "14px",
  lineHeight: "18px",
  minWidth: 0,
  overflowWrap: "anywhere",
};

const terminalFrameStyle: CSSProperties = {
  display: "flex",
  flex: "1 1 0",
  minHeight: 0,
  overflow: "hidden",
  position: "relative",
  width: "100%",
};

const shortcutModalOverlayStyle: CSSProperties = {
  alignItems: "center",
  background: "rgba(0,0,0,0.56)",
  boxSizing: "border-box",
  display: "flex",
  inset: 0,
  justifyContent: "center",
  padding: "16px",
  position: "absolute",
  zIndex: 8,
};

const shortcutModalStyle: CSSProperties = {
  background: "#171c22",
  border: "1px solid rgba(255,255,255,0.16)",
  borderRadius: "6px",
  boxShadow: "0 18px 48px rgba(0,0,0,0.44)",
  boxSizing: "border-box",
  display: "flex",
  flexDirection: "column",
  gap: "10px",
  maxHeight: "calc(100dvh - 160px)",
  minWidth: 0,
  padding: "12px 14px 14px",
  width: "min(34rem, 92vw)",
};

const shortcutModalHeaderStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  gap: "12px",
  justifyContent: "space-between",
  minWidth: 0,
};

const shortcutModalTitleStyle: CSSProperties = {
  color: "#f5f7fb",
  fontSize: "20px",
  fontWeight: 700,
  lineHeight: "24px",
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

type DpadMode = "arrows" | "scroll";

type SteamInputRegistration = {
  unregister: () => void;
};

type GameKeyboardMessage = {
  m_bOpen?: boolean;
};

type SteamInputApi = {
  RegisterForGameKeyboardMessages?: (
    callback: (message: GameKeyboardMessage) => void,
  ) => SteamInputRegistration;
  RegisterForUserDismissKeyboardMessages?: (
    callback: (message: unknown) => void,
  ) => SteamInputRegistration;
  SetKeyboardActionset?: (active: boolean, standalone: boolean) => unknown;
};

type TerminalLogDetails = Record<string, string | number | boolean | null | undefined>;

function terminalLog(event: string, details: TerminalLogDetails = {}) {
  const safeDetails = Object.fromEntries(
    Object.entries(details).filter(([, value]) => value !== undefined),
  );
  console.info(`[Decky AI Assistant] ${event}`, safeDetails);
}

function terminalWarn(event: string, details: TerminalLogDetails = {}) {
  const safeDetails = Object.fromEntries(
    Object.entries(details).filter(([, value]) => value !== undefined),
  );
  console.warn(`[Decky AI Assistant] ${event}`, safeDetails);
}

function normalizeVoiceText(value: string) {
  return value.replace(/[\r\n]+/g, " ").replace(/\s+/g, " ").trim();
}

function supportsNativeVoice(profileName: string | undefined) {
  return profileName === "claude";
}

function terminalDpadMode(config: { dpad_mode?: DpadMode; use_dpad?: boolean } | null): DpadMode {
  if (config?.dpad_mode === "scroll") {
    return "scroll";
  }
  return "arrows";
}

function steamInput(): SteamInputApi | null {
  return (
    (globalThis as typeof globalThis & { SteamClient?: { Input?: SteamInputApi } }).SteamClient
      ?.Input ?? null
  );
}

function voiceErrorMessage(caught: unknown, fallback = "Voice input failed.") {
  const message = toMessage(caught, fallback);
  const domName =
    typeof DOMException !== "undefined" && caught instanceof DOMException ? caught.name : "";
  const normalized = `${domName} ${message}`.toLowerCase();

  if (normalized.includes("notallowed") || normalized.includes("permission")) {
    return "Microphone access is blocked. Allow microphone access for Steam/Decky, then try again.";
  }
  if (normalized.includes("notfound") || normalized.includes("devicesnotfound")) {
    return "No microphone input device is available.";
  }
  if (normalized.includes("notreadable") || normalized.includes("trackstart")) {
    return "Microphone input is busy or unavailable.";
  }
  return message === "Something went wrong." ? fallback : message;
}

export function TerminalPage() {
  const params = useParams<{ sessionId?: string }>();
  const sessionId = String(params.sessionId ?? "");

  const {
    config,
    session,
    initialTerminalOutput,
    latestAuthLink,
    error,
    ready,
    terminalHostRef,
    xtermRef,
    setError,
    clearAuthLink,
    refitTerminal,
    restart,
  } = useTerminalSession(sessionId);

  const keyboardInputRef = useRef<DeckyTextFieldHandle | null>(null);
  const pasteBusyRef = useRef(false);
  const voiceActiveRef = useRef(false);
  const voiceBusyRef = useRef(false);
  // True once `/voice tap` has enabled the CLI tap voice mode for this session.
  const nativeVoiceEnabledRef = useRef(false);
  const [voiceApiConfig, setVoiceApiConfig] = useState<VoiceTranscriptionConfig | null>(null);
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceTranscribing, setVoiceTranscribing] = useState(false);
  const [voiceFinalText, setVoiceFinalText] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("Ready");
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const wheelAccumulatorRef = useRef(0);
  const focusWithDelay = useDelayedFocus();

  const terminalTitle = session
    ? `${session.display_name} / ${shortSessionId(session)}`
    : "Terminal";
  const sessionLogId = session ? shortSessionId(session) : null;
  const visibleAuthLink = latestAuthLink;
  const visibleExtraKeys = config?.extra_keys;
  const nativeVoiceAvailable = supportsNativeVoice(session?.profile_name);
  const externalVoiceReady = Boolean(
    voiceApiConfig?.enabled &&
      (!voiceApiConfig.api_key_required || voiceApiConfig.api_key_configured),
  );
  const dpadMode = terminalDpadMode(config);
  const captureGamepadInput = true;

  const keyboardInputElement = useCallback(
    () => keyboardInputRef.current?.m_elInput ?? null,
    [],
  );

  const focusTerminalNow = useCallback(() => {
    terminalHostRef.current?.focus();
    xtermRef.current?.focus();
  }, [terminalHostRef, xtermRef]);

  const focusTerminal = useCallback(() => {
    focusWithDelay(focusTerminalNow);
  }, [focusTerminalNow]);

  useEffect(() => {
    let secondFrame: number | undefined;
    const firstFrame = window.requestAnimationFrame(() => {
      refitTerminal();
      secondFrame = window.requestAnimationFrame(refitTerminal);
    });
    const timeout = window.setTimeout(refitTerminal, 80);

    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame !== undefined) {
        window.cancelAnimationFrame(secondFrame);
      }
      window.clearTimeout(timeout);
    };
  }, [refitTerminal, visibleAuthLink, visibleExtraKeys]);

  const scrollTerminalLines = useCallback(
    (lines: number) => {
      if (!Number.isFinite(lines) || lines === 0) {
        return;
      }
      xtermRef.current?.scrollLines(lines);
      focusTerminal();
    },
    [focusTerminal, xtermRef],
  );

  const scrollByBaseLines = useCallback(
    (baseLines: number) => {
      if (!config || !Number.isFinite(baseLines) || baseLines === 0) {
        return;
      }

      const speed = TERMINAL_SCROLL_SPEED / 3;
      wheelAccumulatorRef.current += baseLines * speed;

      if (Math.abs(wheelAccumulatorRef.current) >= 1) {
        const lines = Math.trunc(wheelAccumulatorRef.current);
        scrollTerminalLines(lines);
        wheelAccumulatorRef.current -= lines;
      }
    },
    [config, scrollTerminalLines],
  );

  useEffect(() => {
    const host = terminalHostRef.current;
    if (!host || !config) {
      return;
    }

    const handledEvents = new WeakSet<Event>();

    const handleWheel = (event: WheelEvent) => {
      if (handledEvents.has(event)) {
        return;
      }
      handledEvents.add(event);
      event.preventDefault();
      event.stopPropagation();

      const rows = Math.max(1, xtermRef.current?.rows ?? 10);
      const baseLines =
        event.deltaMode === WheelEvent.DOM_DELTA_LINE
          ? event.deltaY
          : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
            ? event.deltaY * rows
            : event.deltaY / WHEEL_PIXEL_LINE_HEIGHT;
      scrollByBaseLines(baseLines);
    };

    const options = { capture: true, passive: false } as const;
    window.addEventListener("wheel", handleWheel, options);
    document.addEventListener("wheel", handleWheel, options);
    host.addEventListener("wheel", handleWheel, options);
    return () => {
      window.removeEventListener("wheel", handleWheel, options);
      document.removeEventListener("wheel", handleWheel, options);
      host.removeEventListener("wheel", handleWheel, options);
      wheelAccumulatorRef.current = 0;
    };
  }, [config, scrollByBaseLines, terminalHostRef, xtermRef]);

  useEffect(() => {
    const input = steamInput();
    const registrations: SteamInputRegistration[] = [];
    const markClosed = (source: string) => {
      terminalLog("virtual keyboard closed", {
        session: sessionLogId,
        source,
      });
      keyboardInputElement()?.blur();
      setKeyboardOpen(false);
      focusTerminal();
    };

    try {
      const userDismiss = input?.RegisterForUserDismissKeyboardMessages?.(() => {
        markClosed("user-dismiss");
      });
      if (userDismiss) {
        registrations.push(userDismiss);
      }
    } catch {
      // Some Steam UI builds expose the method but reject callbacks outside games.
    }

    try {
      const gameKeyboard = input?.RegisterForGameKeyboardMessages?.((message) => {
        if (message.m_bOpen === true) {
          terminalLog("virtual keyboard opened", {
            session: sessionLogId,
            source: "steam-message",
          });
          setKeyboardOpen(true);
          return;
        }
        if (message.m_bOpen === false) {
          markClosed("steam-message");
        }
      });
      if (gameKeyboard) {
        registrations.push(gameKeyboard);
      }
    } catch {
      // Dismiss registration is best-effort; the toggle button still closes directly.
    }

    return () => {
      for (const registration of registrations) {
        registration.unregister();
      }
    };
  }, [focusTerminal, keyboardInputElement, sessionLogId]);

  useEffect(() => {
    let cancelled = false;
    getVoiceTranscriptionConfig()
      .then((result) => {
        if (!cancelled) {
          setVoiceApiConfig(result);
        }
      })
      .catch(reportError);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (voiceActiveRef.current) {
        voiceActiveRef.current = false;
        cancelVoiceCapture().catch(() => {});
      }
    };
  }, []);

  const reportError = (caught: unknown, fallback = "Terminal action failed.") => {
    setError(toMessage(caught, fallback));
    showError(caught, fallback);
  };

  const reportVoiceError = (caught: unknown, fallback = "Voice input failed.") => {
    const message = voiceErrorMessage(caught, fallback);
    voiceActiveRef.current = false;
    setVoiceRecording(false);
    setVoiceTranscribing(false);
    setVoiceStatus(message);
    setError("Voice input failed.");
    showToast({
      body: message,
      critical: true,
      fallback,
    });
  };

  const openKeyboard = () => {
    if (config?.disable_virtual_keyboard) {
      terminalLog("virtual keyboard disabled; focusing terminal", {
        session: sessionLogId,
      });
      focusTerminal();
      return;
    }
    const input = keyboardInputRef.current?.m_elInput;
    if (!input) {
      terminalWarn("virtual keyboard trigger input is unavailable", {
        session: sessionLogId,
      });
      return;
    }
    // Always re-summon the OSK. Steam does not report a *minimized* keyboard as
    // closed, so trusting `keyboardOpen` here left the button dead after a
    // minimize until the page was remounted. A plain click on an already-focused
    // input does not re-open a minimized OSK either, so blur first to force a
    // fresh focus transition, then click.
    terminalLog("virtual keyboard open requested", {
      hasSteamInput: Boolean(steamInput()),
      session: sessionLogId,
    });
    input.blur();
    input.value = "";
    setKeyboardOpen(true);
    input.click();
  };

  const writeInput = async (data: string) => {
    if (!session?.running) {
      return 0;
    }
    const result = await writeTerminalSession({ session_id: session.id, data });
    focusTerminal();
    return result.bytes_written;
  };

  const writeKeyboardInput = async (data: string) => {
    if (!session?.running) {
      return 0;
    }
    const result = await writeTerminalSession({ session_id: session.id, data });
    return result.bytes_written;
  };

  const writePasteInput = async (data: string) => {
    const terminal = xtermRef.current;
    const payload = terminal?.modes.bracketedPasteMode ? `\x1b[200~${data}\x1b[201~` : data;
    return writeInput(payload);
  };

  const writeClipboardText = async (data: string) => {
    const bytesWritten = await writePasteInput(data);
    if (bytesWritten <= 0) {
      throw new Error("terminal session accepted no pasted bytes");
    }
    setError(null);
  };

  const sendInput = (data: string) => {
    writeInput(data).catch(reportError);
  };

  const resetVoiceState = (status: string) => {
    setVoiceRecording(false);
    setVoiceTranscribing(false);
    setVoiceFinalText("");
    setVoiceStatus(status);
    showToast({
      body: status,
      critical: true,
      fallback: status,
    });
  };

  const clearVoiceState = () => {
    setVoiceRecording(false);
    setVoiceTranscribing(false);
    setVoiceFinalText("");
    setVoiceStatus("Ready");
  };

  const insertVoiceText = async (value = voiceFinalText) => {
    const text = normalizeVoiceText(value);
    if (!text) {
      setVoiceStatus("No dictated text is available to insert.");
      showToast({
        body: "No dictated text is available to insert.",
        critical: true,
        fallback: "No dictated text is available to insert.",
      });
      return;
    }
    if (!session?.running) {
      throw new Error("terminal session is not running");
    }
    const bytesWritten = await writePasteInput(text);
    if (bytesWritten <= 0) {
      throw new Error("terminal session accepted no voice input bytes");
    }
    clearVoiceState();
    setError(null);
  };

  const reportVoiceInsertError = (caught: unknown) => {
    const message = toMessage(caught, "Voice text could not be inserted.");
    setVoiceStatus(message);
    setError("Voice text could not be inserted.");
    showToast({
      body: message,
      critical: true,
      fallback: "Voice text could not be inserted.",
    });
  };

  const startBackendVoiceCapture = async () => {
    if (!session?.running) {
      return;
    }

    if (!externalVoiceReady) {
      resetVoiceState(
        voiceApiConfig?.enabled
          ? "External voice API key is not configured. Add it in Settings."
          : "External voice API is disabled. Enable it in Settings.",
      );
      return;
    }

    if (voiceBusyRef.current) {
      return;
    }

    voiceBusyRef.current = true;
    try {
      setVoiceFinalText("");
      setVoiceTranscribing(false);
      setVoiceStatus("Starting microphone...");
      const result = await startVoiceCapture();
      if (result.error || !result.recording) {
        throw new Error(result.error || "Microphone capture did not start.");
      }
      voiceActiveRef.current = true;
      setVoiceRecording(true);
      setVoiceStatus(
        result.tool
          ? `Recording with ${result.tool}... Press voice again to stop.`
          : "Recording... Press voice again to stop.",
      );
    } catch (caught) {
      reportVoiceError(caught, "Voice input failed.");
    } finally {
      voiceBusyRef.current = false;
    }
  };

  const stopBackendVoiceCapture = async () => {
    if (!voiceRecording) {
      return;
    }

    if (voiceBusyRef.current) {
      return;
    }

    voiceBusyRef.current = true;
    try {
      setVoiceRecording(false);
      setVoiceTranscribing(true);
      setVoiceStatus("Transcribing...");
      const result = await stopVoiceCapture();
      if (result.error) {
        throw new Error(result.error);
      }
      voiceActiveRef.current = false;
      const text = normalizeVoiceText(result?.text ?? "");
      setVoiceTranscribing(false);
      if (!text) {
        setVoiceStatus("Transcription returned no text.");
        showToast({
          body: "Transcription returned no text.",
          critical: true,
          fallback: "Transcription returned no text.",
        });
        return;
      }
      setVoiceFinalText(text);
      // Recognized text is always inserted as soon as recording stops, without
      // pressing Enter — same as native voice.
      try {
        await insertVoiceText(text);
      } catch (caught) {
        reportVoiceInsertError(caught);
      }
    } catch (caught) {
      voiceActiveRef.current = false;
      setVoiceTranscribing(false);
      reportVoiceError(caught, "Voice transcription failed.");
    } finally {
      voiceBusyRef.current = false;
    }
  };

  // Native voice = the CLI's own tap dictation (Claude `/voice tap`), where a
  // space keystroke starts listening and a second space sends the dictation.
  // Drive it from the same one-button toggle as external voice: first press
  // starts listening, second press sends. `/voice tap` is enabled lazily once
  // per session; the space keystrokes do the actual record/send.
  const toggleNativeVoice = async () => {
    if (!session?.running || voiceBusyRef.current) {
      return;
    }
    voiceBusyRef.current = true;
    try {
      if (voiceRecording) {
        const bytesWritten = await writeInput(" ");
        if (bytesWritten <= 0) {
          throw new Error("terminal session accepted no voice toggle bytes");
        }
        setVoiceRecording(false);
        setVoiceStatus("Voice sent to the CLI.");
        return;
      }

      if (!nativeVoiceEnabledRef.current) {
        const enableBytes = await writeInput("/voice tap\r");
        if (enableBytes <= 0) {
          throw new Error("terminal session accepted no native voice command bytes");
        }
        nativeVoiceEnabledRef.current = true;
        await new Promise((resolve) => window.setTimeout(resolve, NATIVE_VOICE_ENABLE_DELAY_MS));
        if (!session?.running) {
          return;
        }
      }

      const startBytes = await writeInput(" ");
      if (startBytes <= 0) {
        throw new Error("terminal session accepted no voice toggle bytes");
      }
      setVoiceRecording(true);
      setVoiceStatus("Listening... press voice again to send.");
    } finally {
      voiceBusyRef.current = false;
    }
  };

  const startVoiceInput = () => {
    if (voiceTranscribing) {
      return;
    }
    // Native CLI voice and external API voice share the same one-button UX:
    // press to start listening, press again to send/insert.
    if (nativeVoiceAvailable && config?.voice_prefer_native_cli) {
      toggleNativeVoice().catch((caught) => reportVoiceError(caught, "Voice input failed."));
      return;
    }
    if (voiceRecording) {
      stopBackendVoiceCapture().catch((caught) => reportVoiceError(caught));
      return;
    }
    startBackendVoiceCapture().catch((caught) => {
      reportVoiceError(caught, "Voice input failed.");
    });
  };

  const pasteClipboard = async () => {
    if (!session?.running) {
      return;
    }
    if (pasteBusyRef.current) {
      return;
    }
    pasteBusyRef.current = true;
    try {
      // The backend reads the gamescope Xwayland selection directly via libX11,
      // the focus-independent clipboard path that works in Gaming Mode (and
      // Desktop Mode). The text is written to the PTY as plain (bracketed) input,
      // so CLIs never receive a raw Ctrl+V.
      const value = await readTextFromClipboard();
      if (!value) {
        showToast({ body: "Clipboard is empty." });
        return;
      }
      await writeClipboardText(value);
    } catch (caught) {
      reportError(caught, "Clipboard paste failed.");
    } finally {
      pasteBusyRef.current = false;
    }
  };

  // Route Ctrl+V / Cmd+V / Shift+Insert through our paste flow instead of
  // letting xterm forward a raw Ctrl+V (0x16) to the CLI. On the Deck the
  // virtual-keyboard paste button arrives as one of these keystrokes, and some
  // CLIs (e.g. Codex) treat a literal Ctrl+V as "paste image" and error on the
  // unreachable X11 clipboard. Keep a ref to the latest handler so the xterm
  // binding never goes stale.
  const pasteShortcutRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    pasteShortcutRef.current = () => {
      pasteClipboard().catch(showError);
    };
  });

  useEffect(() => {
    const terminal = xtermRef.current;
    if (!ready || !terminal) {
      return;
    }
    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type !== "keydown") {
        return true;
      }
      const wantsPaste =
        ((event.ctrlKey || event.metaKey) && (event.key === "v" || event.key === "V")) ||
        (event.shiftKey && event.key === "Insert");
      if (!wantsPaste) {
        return true;
      }
      event.preventDefault();
      pasteShortcutRef.current();
      return false;
    });
    return () => {
      terminal.attachCustomKeyEventHandler(() => true);
    };
  }, [ready, xtermRef]);

  const handleKeyboardInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const value = event.currentTarget.value;
    if (!value) {
      return;
    }
    event.currentTarget.value = "";
    writeKeyboardInput(value).catch(reportError);
  };

  const handleKeyboardInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const specialKeys: Record<string, string | undefined> = {
      Enter: "\r",
      Backspace: "\x7f",
      Escape: "\x1b",
      Tab: "\t",
    };
    const data = specialKeys[event.key];
    if (!data) {
      return;
    }
    event.preventDefault();
    event.currentTarget.value = "";
    writeKeyboardInput(data).catch(reportError);
  };

  const copyAuthLink = async (link: string) => {
    try {
      await copyTextToClipboard(link);
      showToast({
        body: "Auth link copied.",
      });
    } catch (caught) {
      reportError(caught);
    }
  };

  const openAuthLink = async (link: string) => {
    try {
      await copyTextToClipboard(link);
    } catch {
      // Opening is still useful even when clipboard access is unavailable.
    }
    const opened = openExternalUrl(link);
    showToast({
      body: opened ? "Opening auth link." : "Auth link copied; open it in a browser.",
      critical: !opened,
    });
  };

  const dismissAuthLinks = async () => {
    if (!session) {
      clearAuthLink();
      return;
    }
    try {
      await clearTerminalSessionLinks({ session_id: session.id });
      clearAuthLink();
      focusTerminal();
    } catch (caught) {
      reportError(caught);
    }
  };

  const pageScrollLines = () => Math.max(1, (xtermRef.current?.rows ?? 10) - 1);
  const lineScrollLines = () => TERMINAL_SCROLL_SPEED;
  const scrollLineUp = () => xtermRef.current?.scrollLines(-lineScrollLines());
  const scrollLineDown = () => xtermRef.current?.scrollLines(lineScrollLines());
  const scrollPageUp = () => xtermRef.current?.scrollLines(-pageScrollLines());
  const scrollPageDown = () => xtermRef.current?.scrollLines(pageScrollLines());

  const consumeGamepadEvent = (event: GamepadEvent) => {
    event.preventDefault();
    if (captureGamepadInput) {
      event.stopPropagation();
    }
  };

  const handleDpad = (event: GamepadEvent) => {
    const mapping: Record<number, string | undefined> = {
      [GamepadButton.DIR_LEFT]: "\x1b[D",
      [GamepadButton.DIR_UP]: "\x1b[A",
      [GamepadButton.DIR_DOWN]: "\x1b[B",
      [GamepadButton.DIR_RIGHT]: "\x1b[C",
    };
    const data = mapping[event.detail.button];
    if (!data) {
      return;
    }
    consumeGamepadEvent(event);

    if (dpadMode === "scroll") {
      if (event.detail.button === GamepadButton.DIR_UP) {
        scrollLineUp();
      } else if (event.detail.button === GamepadButton.DIR_DOWN) {
        scrollLineDown();
      } else if (event.detail.button === GamepadButton.DIR_LEFT) {
        scrollPageUp();
      } else if (event.detail.button === GamepadButton.DIR_RIGHT) {
        scrollPageDown();
      }
      focusTerminal();
      return;
    }

    sendInput(data);
  };

  const restartSession = async () => {
    if (!session) {
      return;
    }
    try {
      await restart();
      // A restarted CLI no longer has tap voice mode enabled, and any in-flight
      // dictation is gone.
      nativeVoiceEnabledRef.current = false;
      clearVoiceState();
      focusTerminal();
    } catch (caught) {
      reportError(caught);
    }
  };

  const closeSession = async () => {
    if (!session) {
      Navigation.NavigateBack();
      return;
    }
    try {
      await stopTerminalSession({ session_id: session.id });
      clearAuthLink();
      Navigation.NavigateBack();
    } catch (caught) {
      reportError(caught);
    }
  };

  const copySelection = async () => {
    const selection = xtermRef.current?.getSelection();
    if (!selection) {
      showToast({ body: "No text selected." });
      return;
    }
    try {
      await copyTextToClipboard(selection);
    } catch (caught) {
      reportError(caught);
    }
  };

  const canStartVoiceFromDeck =
    config?.voice_input && session?.running && (externalVoiceReady || nativeVoiceAvailable);

  const closeShortcutHelp = () => {
    setShortcutHelpOpen(false);
    focusTerminal();
  };

  const handleDeckButtonDown = (event: GamepadEvent) => {
    if (!captureGamepadInput) {
      return;
    }

    const { button, is_repeat: isRepeat } = event.detail;
    if (button === GamepadButton.STEAM_GUIDE || button === GamepadButton.STEAM_QUICK_MENU) {
      return;
    }

    if (shortcutHelpOpen) {
      consumeGamepadEvent(event);
      if (
        !isRepeat &&
        (
          button === GamepadButton.OK ||
          button === GamepadButton.CANCEL ||
          button === GamepadButton.OPTIONS ||
          button === GamepadButton.START
        )
      ) {
        closeShortcutHelp();
      }
      return;
    }

    const sendDeckInput = (data: string, allowRepeat = false) => {
      consumeGamepadEvent(event);
      if (isRepeat && !allowRepeat) {
        return;
      }
      sendInput(data);
    };

    if (button === GamepadButton.OK) {
      sendDeckInput("\r");
      return;
    }
    if (button === GamepadButton.CANCEL) {
      consumeGamepadEvent(event);
      if (isRepeat) {
        return;
      }
      Navigation.NavigateBack();
      return;
    }
    if (button === GamepadButton.SECONDARY) {
      sendDeckInput("\x7f", true);
      return;
    }
    if (button === GamepadButton.OPTIONS) {
      consumeGamepadEvent(event);
      if (!isRepeat) {
        pasteClipboard().catch(showError);
      }
      return;
    }
    if (button === GamepadButton.BUMPER_LEFT) {
      sendDeckInput("\x1bb", true);
      return;
    }
    if (button === GamepadButton.BUMPER_RIGHT) {
      sendDeckInput("\x1bf", true);
      return;
    }
    if (button === GamepadButton.TRIGGER_LEFT) {
      consumeGamepadEvent(event);
      scrollPageUp();
      focusTerminal();
      return;
    }
    if (button === GamepadButton.TRIGGER_RIGHT) {
      consumeGamepadEvent(event);
      scrollPageDown();
      focusTerminal();
      return;
    }
    if (button === GamepadButton.SELECT) {
      consumeGamepadEvent(event);
      if (!isRepeat) {
        openKeyboard();
      }
      return;
    }
    if (button === GamepadButton.START) {
      consumeGamepadEvent(event);
      if (isRepeat) {
        return;
      }
      if (canStartVoiceFromDeck) {
        startVoiceInput();
      } else {
        openTerminalActionsMenu(terminalHostRef.current);
      }
      return;
    }
    if (button === GamepadButton.LSTICK_CLICK) {
      sendDeckInput("\x1b[H");
      return;
    }
    if (button === GamepadButton.RSTICK_CLICK) {
      sendDeckInput("\x1b[F");
      return;
    }
    if (button === GamepadButton.REAR_LEFT_UPPER) {
      sendDeckInput("\t");
      return;
    }
    if (button === GamepadButton.REAR_LEFT_LOWER) {
      sendDeckInput("\x1b");
      return;
    }
    if (button === GamepadButton.REAR_RIGHT_UPPER) {
      sendDeckInput("\x03");
      return;
    }
    if (button === GamepadButton.REAR_RIGHT_LOWER) {
      sendDeckInput("\x1b[3~", true);
    }
  };

  const menuItemLabel = (icon: ReactNode, label: string) => (
    <span style={{ alignItems: "center", display: "inline-flex", gap: "8px" }}>
      {icon}
      <span>{label}</span>
    </span>
  );

  const terminalActionsMenu = () => (
    <Menu label="Terminal actions">
      <MenuItem disabled={!session?.running} onSelected={() => sendInput("\x03")}>
        {menuItemLabel(<FaBan />, "Interrupt (^C)")}
      </MenuItem>
      <MenuItem disabled={!session} onSelected={() => { restartSession().catch(showError); }}>
        {menuItemLabel(<FaRedo />, "Restart")}
      </MenuItem>
      <MenuItem disabled={!session} tone="destructive" onSelected={() => { closeSession().catch(showError); }}>
        {menuItemLabel(<FaStop />, "Stop")}
      </MenuItem>
    </Menu>
  );

  const openTerminalActionsMenu = (anchor?: EventTarget | null) => {
    const element = anchor instanceof HTMLElement ? anchor : terminalHostRef.current ?? undefined;
    showContextMenu(terminalActionsMenu(), element);
  };

  const openOverflowMenu = (event: MouseEvent) => {
    openTerminalActionsMenu(event.currentTarget);
  };

  const shortcutRows = () => [
    ["A", "Enter"],
    ["B", "Back"],
    ["X", "Backspace"],
    ["Y", "Paste clipboard into the terminal"],
    ["DPad", dpadMode === "scroll" ? "Scroll lines/pages" : "Arrow keys"],
    ["Select", "Open the Steam keyboard"],
    ["Start", canStartVoiceFromDeck ? "Voice input" : "Terminal actions menu"],
    ["L1 / R1", "Move one word left / right"],
    ["L2 / R2", "Page up / page down"],
    ["L3 / R3", "Home / end"],
    ["L4 / L5", "Tab / Esc"],
    ["R4 / R5", "Ctrl+C / Delete"],
  ];

  const openShortcutHelp = () => {
    setShortcutHelpOpen(true);
  };

  if (!config || initialTerminalOutput === null) {
    return <SteamSpinner />;
  }

  return (
    <Focusable
      noFocusRing
      navEntryPreferPosition={
        captureGamepadInput ? NavEntryPositionPreferences.PREFERRED_CHILD : undefined
      }
      onButtonDown={handleDeckButtonDown}
      onGamepadFocus={captureGamepadInput && !keyboardOpen ? focusTerminalNow : undefined}
      onGamepadDirection={handleDpad}
      preferredFocus={captureGamepadInput}
      style={normalTerminalPageStyle}
    >
      <style>{XTERM_INLINE_CSS}</style>
      {shortcutHelpOpen ? (
        <div style={shortcutModalOverlayStyle} onClick={closeShortcutHelp}>
          <div
            aria-modal="true"
            role="dialog"
            style={shortcutModalStyle}
            onClick={(event) => event.stopPropagation()}
          >
            <div style={shortcutModalHeaderStyle}>
              <div style={shortcutModalTitleStyle}>Terminal shortcuts</div>
              <TinyButton
                focusable={false}
                onClick={closeShortcutHelp}
                title="Close terminal shortcuts"
              >
                <FaTimesCircle />
              </TinyButton>
            </div>
            <div style={shortcutModalBodyStyle}>
              {shortcutRows().map(([shortcut, description]) => (
                <div key={shortcut} style={shortcutModalRowStyle}>
                  <span style={shortcutKeyStyle}>{shortcut}</span>
                  <span style={shortcutDescriptionStyle}>
                    {description}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      <div style={toolbarStyle}>
        <div style={{ minWidth: 0 }}>
          <div
            className={staticClasses.Title}
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {terminalTitle}
          </div>
          {error ? <div className={staticClasses.Label}>{error}</div> : null}
        </div>
        <div style={toolbarActionsStyle}>
          <TinyButton
            focusable={false}
            onClick={openKeyboard}
            title={config.disable_virtual_keyboard ? "Focus terminal" : "Show keyboard"}
          >
            {config.disable_virtual_keyboard ? <FaTerminal /> : <FaKeyboard />}
          </TinyButton>
          {config.voice_input && (externalVoiceReady || nativeVoiceAvailable) ? (
            <TinyButton
              disabled={!session?.running || voiceTranscribing}
              focusable={false}
              onClick={startVoiceInput}
              title={voiceStatus}
            >
              {voiceRecording || voiceTranscribing ? <FaStop /> : <FaMicrophone />}
            </TinyButton>
          ) : null}
          <TinyButton
            focusable={false}
            onClick={openShortcutHelp}
            title="Show terminal shortcuts"
          >
            <FaQuestionCircle />
          </TinyButton>
          <TinyButton
            disabled={!session?.running}
            focusable={false}
            onClick={() => pasteClipboard().catch(showError)}
            title="Paste clipboard"
          >
            <FaPaste />
          </TinyButton>
          <TinyButton
            disabled={!session}
            focusable={false}
            onClick={() => copySelection().catch(showError)}
            title="Copy terminal selection"
          >
            <FaRegCopy />
          </TinyButton>
          <TinyButton
            focusable={false}
            onClick={(event: MouseEvent) => openOverflowMenu(event)}
            title="Terminal actions"
          >
            <FaEllipsisV />
          </TinyButton>
          <TinyButton
            focusable={false}
            onClick={() => Navigation.NavigateBack()}
            title="Back to plugin panel"
          >
            <FaChevronLeft />
          </TinyButton>
        </div>
      </div>

      <DeckyTextField
        ref={keyboardInputRef}
        autoCapitalize="none"
        autoComplete="off"
        autoCorrect="off"
        inputMode="text"
        spellCheck={false}
        style={keyboardTriggerWrapperStyle}
        tabIndex={-1}
        onChange={handleKeyboardInputChange}
        onFocus={() => {
          terminalLog("virtual keyboard trigger focused", {
            session: sessionLogId,
          });
          setKeyboardOpen(true);
        }}
        onKeyDown={handleKeyboardInputKeyDown}
      />

      {visibleAuthLink ? (
        <AuthLinkPanel
          link={visibleAuthLink}
          onOpen={() => openAuthLink(visibleAuthLink).catch(showError)}
          onCopy={() => copyAuthLink(visibleAuthLink).catch(showError)}
          onHide={() => dismissAuthLinks().catch(showError)}
        />
      ) : null}

      <div style={terminalFrameStyle}>
        <div
          aria-label="Terminal input"
          className="decky-ai-terminal"
          onClick={focusTerminal}
          ref={terminalHostRef}
          role="textbox"
          style={{ ...terminalHostStyle, flex: "1 1 0", height: "100%", minHeight: 0 }}
          tabIndex={0}
        >
          {null}
        </div>
      </div>

      {visibleExtraKeys ? <ExtraKeysBar onKey={sendInput} /> : null}
    </Focusable>
  );
}
