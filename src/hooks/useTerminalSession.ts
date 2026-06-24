import { FitAddon } from "@xterm/addon-fit";
import { Terminal as XTerm } from "@xterm/xterm";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_TERMINAL_COLS,
  DEFAULT_TERMINAL_ROWS,
  POLL_INTERVAL_MS,
} from "../lib/constants";
import { copyTextToClipboard } from "../lib/clipboard";
import { toMessage } from "../lib/errors";
import { showError } from "../lib/toast";
import { FOCUS_DELAY_MS } from "../lib/focus";
import {
  getTerminalConfig,
  getTerminalSessionLinks,
  listTerminalSessions,
  readTerminalSession,
  resizeTerminalSession,
  restartTerminalSession,
  writeTerminalSession,
  type TerminalConfig,
  type TerminalSessionSnapshot,
} from "../api/callables";

const MIN_TERMINAL_COLS = 24;
const MIN_TERMINAL_ROWS = 8;
const AUTO_COPY_DEBOUNCE_MS = 150;

export type UseTerminalSessionResult = {
  config: TerminalConfig | null;
  session: TerminalSessionSnapshot | null;
  initialTerminalOutput: string | null;
  latestAuthLink: string | null;
  error: string | null;
  ready: boolean;
  terminalHostRef: React.MutableRefObject<HTMLDivElement | null>;
  xtermRef: React.MutableRefObject<XTerm | null>;
  setError: (message: string | null) => void;
  setSession: (session: TerminalSessionSnapshot | null) => void;
  clearAuthLink: () => void;
  refitTerminal: () => void;
  restart: () => Promise<void>;
};

/**
 * Owns the full terminal lifecycle for one session id: load config + tail,
 * create/dispose the xterm instance, and poll backend output. Auth links come
 * straight from the backend (already deduped, OAuth/loopback filtered, and
 * suppressed on auth completion) so the client does no link parsing.
 */
export function useTerminalSession(sessionId: string): UseTerminalSessionResult {
  const terminalHostRef = useRef<HTMLDivElement | null>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  // H3 guard: true only while a live, non-disposed xterm is open. The poll loop
  // consults this before writing so it can never write into a disposed terminal
  // during a config-driven recreate.
  const xtermReadyRef = useRef(false);

  const [config, setConfig] = useState<TerminalConfig | null>(null);
  const [session, setSession] = useState<TerminalSessionSnapshot | null>(null);
  const [initialTerminalOutput, setInitialTerminalOutput] = useState<string | null>(null);
  const [latestAuthLink, setLatestAuthLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // M6: a single AbortController drives polling. restart() aborts the in-flight
  // loop and starts a fresh one in place — no meaningless generation counter.
  const pollAbortRef = useRef<AbortController | null>(null);

  const reportError = useCallback((caught: unknown) => {
    setError(toMessage(caught));
    showError(caught);
  }, []);

  const refitTerminal = useCallback(() => {
    const terminal = xtermRef.current;
    const fitAddon = fitAddonRef.current;
    if (!terminal || !fitAddon || !xtermReadyRef.current || !sessionId) {
      return;
    }

    const dims = fitAddon.proposeDimensions();
    if (!dims || !Number.isFinite(dims.cols) || !Number.isFinite(dims.rows)) {
      return;
    }

    const nextCols = Math.max(MIN_TERMINAL_COLS, dims.cols);
    const nextRows = Math.max(MIN_TERMINAL_ROWS, dims.rows);
    terminal.resize(nextCols, nextRows);
    resizeTerminalSession({
      session_id: sessionId,
      cols: nextCols,
      rows: nextRows,
    }).catch(() => undefined);
  }, [sessionId]);

  const runPollLoop = useCallback(
    (signal: AbortSignal) => {
      let timer: number | undefined;

      const stop = () => {
        if (timer !== undefined) {
          window.clearTimeout(timer);
          timer = undefined;
        }
      };
      signal.addEventListener("abort", stop, { once: true });

      const poll = async () => {
        try {
          const result = await readTerminalSession({
            session_id: sessionId,
            max_bytes: 65536,
            timeout_seconds: 0,
          });

          if (signal.aborted) {
            return;
          }

          if (result.data && xtermReadyRef.current) {
            xtermRef.current?.write(result.data);
          }
          // Backend already suppresses links on auth completion and returns the
          // newest first; only the newest link is ever displayed.
          setLatestAuthLink(result.links[0] ?? null);

          setSession(result.session);
          if (!result.session.running) {
            if (xtermReadyRef.current) {
              xtermRef.current?.writeln("");
              xtermRef.current?.writeln("[process exited]");
            }
            return;
          }

          timer = window.setTimeout(poll, POLL_INTERVAL_MS);
        } catch {
          if (signal.aborted) {
            return;
          }
          // A failed read almost always means the session ended or was closed
          // elsewhere — e.g. via the Quick Access panel's close button while
          // this terminal route was still mounted under the overlay. Surface it
          // quietly in the terminal instead of a global "something went wrong"
          // toast, then stop polling.
          if (xtermReadyRef.current) {
            xtermRef.current?.writeln("");
            xtermRef.current?.writeln("[session closed]");
          }
        }
      };

      timer = window.setTimeout(poll, 0);
    },
    [reportError, sessionId],
  );

  // Load config + session list + persisted auth links/output tail.
  useEffect(() => {
    let cancelled = false;
    setConfig(null);
    setInitialTerminalOutput(null);
    setLatestAuthLink(null);
    Promise.all([
      getTerminalConfig(),
      listTerminalSessions(),
      sessionId
        ? getTerminalSessionLinks({ session_id: sessionId })
        : Promise.resolve({ links: [], output_tail: "" }),
    ])
      .then(([nextConfig, result, linkResult]) => {
        if (cancelled) {
          return;
        }
        setConfig(nextConfig);
        setSession(result.sessions.find((item) => item.id === sessionId) ?? null);
        setInitialTerminalOutput(linkResult.output_tail ?? "");
        setLatestAuthLink(linkResult.links[0] ?? null);
        setError(null);
      })
      .catch((caught) => {
        if (!cancelled) {
          reportError(caught);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reportError, sessionId]);

  // Create / dispose the xterm instance. Restart polling whenever the terminal
  // is (re)created so the poll loop and the live xterm always share a lifetime
  // — this is the H3 fix at the structural level.
  useEffect(() => {
    if (!config || initialTerminalOutput === null || !terminalHostRef.current || !sessionId) {
      return;
    }

    const host = terminalHostRef.current;
    const terminal = new XTerm({
      allowProposedApi: true,
      convertEol: true,
      cursorBlink: true,
      cols: DEFAULT_TERMINAL_COLS,
      rows: DEFAULT_TERMINAL_ROWS,
      fontFamily: config.font_family,
      fontSize: config.font_size,
      rightClickSelectsWord: true,
      scrollback: 3000,
      theme: {
        background: "#101418",
        foreground: "#d7dde8",
        cursor: "#f0f3f7",
        selectionBackground: "#335c81",
      },
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(host);
    if (initialTerminalOutput) {
      terminal.write(initialTerminalOutput);
    }
    window.setTimeout(() => terminal.focus(), FOCUS_DELAY_MS);
    xtermRef.current = terminal;
    fitAddonRef.current = fitAddon;
    xtermReadyRef.current = true;
    setReady(true);

    const sendData = terminal.onData((data) => {
      writeTerminalSession({ session_id: sessionId, data }).catch(reportError);
    });

    let autoCopyTimer: number | undefined;
    const selectionSub = terminal.onSelectionChange(() => {
      if (!config.auto_copy_selection || !terminal.hasSelection()) {
        return;
      }
      const selection = terminal.getSelection();
      if (!selection) {
        return;
      }
      if (autoCopyTimer !== undefined) {
        window.clearTimeout(autoCopyTimer);
      }
      autoCopyTimer = window.setTimeout(() => {
        autoCopyTimer = undefined;
        copyTextToClipboard(selection).catch(() => undefined);
      }, AUTO_COPY_DEBOUNCE_MS);
    });

    const resizeToHost = () => {
      refitTerminal();
    };
    refitTerminal();
    const resizeObserver = new ResizeObserver(resizeToHost);
    resizeObserver.observe(host);

    const controller = new AbortController();
    pollAbortRef.current = controller;
    runPollLoop(controller.signal);

    return () => {
      // Abort whichever poll loop is currently active. restart() may have
      // swapped in a newer controller than the one created above, so abort the
      // ref's current controller (if any) as well to avoid leaking a loop.
      controller.abort();
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
      resizeObserver.disconnect();
      sendData.dispose();
      selectionSub.dispose();
      if (autoCopyTimer !== undefined) {
        window.clearTimeout(autoCopyTimer);
      }
      xtermReadyRef.current = false;
      setReady(false);
      terminal.dispose();
      xtermRef.current = null;
      if (fitAddonRef.current === fitAddon) {
        fitAddonRef.current = null;
      }
    };
  }, [config, initialTerminalOutput, refitTerminal, reportError, runPollLoop, sessionId]);

  const clearAuthLink = useCallback(() => {
    setLatestAuthLink(null);
  }, []);

  const restart = useCallback(async () => {
    if (!session) {
      return;
    }
    if (xtermReadyRef.current) {
      xtermRef.current?.clear();
      xtermRef.current?.writeln(`[restarting ${session.display_name}]`);
    }
    setLatestAuthLink(null);
    const result = await restartTerminalSession({ session_id: session.id });
    setSession(result.session);
    setError(null);
    // Restart polling in place against the same live xterm.
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    runPollLoop(controller.signal);
  }, [runPollLoop, session]);

  return {
    config,
    session,
    initialTerminalOutput,
    latestAuthLink,
    error,
    ready,
    terminalHostRef,
    xtermRef,
    setError,
    setSession,
    clearAuthLink,
    refitTerminal,
    restart,
  };
}
