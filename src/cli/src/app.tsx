import React, { useEffect, useReducer, useRef, useState } from "react";
import { Box, Text, useApp } from "ink";
import { homedir } from "node:os";
import { join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";
import type { ServerHandle } from "./server";
import { ReadbackSocket, type DoneMsg, type ServerMsg } from "./ws";
import * as player from "./player";
import type { PlayerSnapshot } from "./player";
import { savePrefs, type Prefs } from "./prefs";
import { DIM, RED } from "./theme";
import { Header } from "./components/Header";
import { UrlInput } from "./components/UrlInput";
import { StatusLine } from "./components/StatusLine";
import { BusyView } from "./components/BusyView";
import { PlayerView } from "./components/PlayerView";
import { ModelList, type ModelsResp } from "./components/ModelList";
import { LibraryView, type LibraryItem } from "./components/LibraryView";
import { HelpView } from "./components/HelpView";

interface State {
  screen: "input" | "busy" | "player" | "library" | "quitting";
  error: string | null;
  notice: string | null;
  modelList: ModelsResp | null;
  phase: string;
  progress: { done: number; total: number } | null;
  result: DoneMsg | null;
  wavPath: string;
  player: PlayerSnapshot;
  showTranscript: boolean;
  voice: string;
  mode: "full" | "summary";
  model: string;
  libraryItems: LibraryItem[];
  libraryTotal: number;
  libraryOffset: number;
  libraryCursor: number;
  confirmDelete: boolean;
  showHelp: boolean;
}

type Action =
  | { type: "submit" }
  | { type: "phase"; value: string }
  | { type: "progress"; done: number; total: number }
  | { type: "done"; result: DoneMsg; wavPath: string }
  | { type: "error"; message: string }
  | { type: "back" }
  | { type: "player"; snap: PlayerSnapshot }
  | { type: "toggleTranscript" }
  | { type: "setVoice"; voice: string }
  | { type: "setMode"; mode: "full" | "summary" }
  | { type: "setModel"; model: string }
  | { type: "notice"; text: string | null }
  | { type: "modelList"; resp: ModelsResp }
  | { type: "toggleHelp" }
  | { type: "openLibrary"; items: LibraryItem[]; total: number }
  | { type: "libraryLoaded"; items: LibraryItem[]; total: number; offset: number }
  | { type: "libraryMove"; delta: number }
  | { type: "libraryDeleteItem"; id: string }
  | { type: "libraryConfirmDelete" }
  | { type: "libraryClearConfirm" }
  | { type: "quitting" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "submit":
      return {
        ...state,
        screen: "busy",
        phase: "connecting",
        progress: null,
        error: null,
        notice: null,
        modelList: null,
        showHelp: false,
      };
    case "phase":
      return { ...state, phase: action.value };
    case "progress":
      return { ...state, progress: { done: action.done, total: action.total } };
    case "done":
      return {
        ...state,
        screen: "player",
        result: action.result,
        wavPath: action.wavPath,
        showTranscript: false,
        player: { state: "playing", elapsed: 0 },
      };
    case "error":
      return { ...state, screen: "input", error: action.message, notice: null, modelList: null };
    case "back":
      return { ...state, screen: "input", error: null };
    case "player":
      return { ...state, player: action.snap };
    case "toggleTranscript":
      return { ...state, showTranscript: !state.showTranscript };
    case "setVoice":
      return { ...state, voice: action.voice, error: null };
    case "setMode":
      return { ...state, mode: action.mode, error: null };
    case "setModel":
      return { ...state, model: action.model, error: null };
    case "notice":
      return { ...state, notice: action.text, error: null, modelList: null, showHelp: false };
    case "modelList":
      return { ...state, modelList: action.resp, notice: null, error: null, showHelp: false };
    case "toggleHelp":
      return { ...state, showHelp: !state.showHelp, notice: null, error: null, modelList: null };
    case "openLibrary":
      return {
        ...state,
        screen: "library",
        libraryItems: action.items,
        libraryTotal: action.total,
        libraryOffset: action.items.length,
        libraryCursor: 0,
        confirmDelete: false,
        error: null,
        notice: null,
        modelList: null,
      };
    case "libraryLoaded":
      return {
        ...state,
        libraryItems: [...state.libraryItems, ...action.items],
        libraryTotal: action.total,
        libraryOffset: action.offset,
      };
    case "libraryMove": {
      const next = Math.max(0, Math.min(state.libraryCursor + action.delta, state.libraryItems.length - 1));
      return { ...state, libraryCursor: next, confirmDelete: false };
    }
    case "libraryDeleteItem":
      return {
        ...state,
        libraryItems: state.libraryItems.filter((i) => i.id !== action.id),
        libraryTotal: Math.max(0, state.libraryTotal - 1),
        libraryCursor: Math.min(state.libraryCursor, Math.max(0, state.libraryItems.length - 2)),
        confirmDelete: false,
      };
    case "libraryConfirmDelete":
      return { ...state, confirmDelete: true };
    case "libraryClearConfirm":
      return { ...state, confirmDelete: false };
    case "quitting":
      return { ...state, screen: "quitting" };
  }
}

const SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function QuittingView() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setFrame((f) => (f + 1) % SPIN_FRAMES.length), 80);
    return () => clearInterval(t);
  }, []);
  return (
    <Box paddingX={1} marginY={1}>
      <Text color={DIM}>{SPIN_FRAMES[frame]} quitting…</Text>
    </Box>
  );
}

async function resolveWav(base: string, audioUrl: string, audioDir?: string): Promise<string> {
  const fname = audioUrl.split("/").pop()!;
  // Same-machine shortcut: play the server-written WAV directly (no download).
  // The server reports its output_dir via the config message (audio_dir).
  if (audioDir) {
    const local = join(audioDir, fname);
    if (existsSync(local)) return local;
  }
  // Otherwise (remote server, or file missing) download into a CLI-only cache —
  // deliberately NOT under the server's audio dir.
  const dir = join(homedir(), ".readback", "cli-cache");
  mkdirSync(dir, { recursive: true });
  const dest = join(dir, fname);
  const res = await fetch(base + audioUrl);
  if (!res.ok) throw new Error(`audio download failed (${res.status})`);
  await Bun.write(dest, res);
  return dest;
}

interface Props {
  handle: ServerHandle;
  prefs: Prefs;
  onQuit: () => void;
}

export function App({ handle, prefs, onQuit }: Props) {
  const { exit } = useApp();
  const cfg = handle.config;
  const voiceIds = cfg.voices_available.map((v) => v.id);

  const [state, dispatch] = useReducer(reducer, {
    screen: "input" as const,
    error: null,
    notice: null,
    modelList: null,
    phase: "connecting",
    progress: null,
    result: null,
    wavPath: "",
    player: { state: "stopped" as const, elapsed: 0 },
    showTranscript: false,
    voice: prefs.voice && voiceIds.includes(prefs.voice) ? prefs.voice : cfg.voice,
    mode: prefs.mode ?? cfg.default_mode,
    model: prefs.model ?? cfg.model,
    libraryItems: [],
    libraryTotal: 0,
    libraryOffset: 0,
    libraryCursor: 0,
    confirmDelete: false,
    showHelp: false,
  });

  const sockRef = useRef<ReadbackSocket | null>(null);
  const modelsRef = useRef<ModelsResp | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const sock = new ReadbackSocket(
      handle.base,
      (msg: ServerMsg) => {
        switch (msg.type) {
          case "phase":
            dispatch({ type: "phase", value: msg.value });
            break;
          case "progress":
            dispatch({ type: "progress", done: msg.done, total: msg.total });
            break;
          case "done":
            resolveWav(handle.base, msg.audio_url, cfg.audio_dir)
              .then((wavPath) => {
                dispatch({ type: "done", result: msg, wavPath });
                player.play(wavPath, msg.duration_sec);
              })
              .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
            break;
          case "error":
            dispatch({ type: "error", message: msg.message });
            break;
        }
      },
      () => dispatch({ type: "error", message: "lost connection to the readback server" }),
    );
    sockRef.current = sock;
    sock.connect().catch(() => dispatch({ type: "error", message: "could not connect to /ws" }));
    player.onPlayerChange((snap) => dispatch({ type: "player", snap }));
    return () => {
      player.onPlayerChange(null);
      sock.close();
    };
  }, [handle.base]);

  const quit = () => {
    onQuit();
    exit();
  };

  const startQuit = () => {
    dispatch({ type: "quitting" });
    setTimeout(quit, 300);
  };

  const persist = (voice: string, mode: "full" | "summary", model: string) =>
    savePrefs({ voice, mode, model });

  const fetchModels = async (): Promise<ModelsResp> => {
    const res = await fetch(handle.base + "/api/models");
    if (!res.ok) throw new Error(`model list failed (${res.status})`);
    const resp = (await res.json()) as ModelsResp;
    if (resp.error) throw new Error(resp.error);
    modelsRef.current = resp;
    return resp;
  };

  const fetchLibrary = async (offset: number): Promise<{ items: LibraryItem[]; total: number }> => {
    const res = await fetch(handle.base + `/api/library?sort=newest&limit=20&offset=${offset}`);
    if (!res.ok) throw new Error(`library fetch failed (${res.status})`);
    const data = (await res.json()) as { items: LibraryItem[]; total: number };
    return data;
  };

  const openLibrary = () => {
    fetchLibrary(0)
      .then(({ items, total }) => dispatch({ type: "openLibrary", items, total }))
      .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
  };

  const loadMoreLibrary = () => {
    if (state.libraryItems.length >= state.libraryTotal) return;
    fetchLibrary(state.libraryOffset)
      .then(({ items, total }) =>
        dispatch({ type: "libraryLoaded", items, total, offset: state.libraryOffset + items.length })
      )
      .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
  };

  const deleteLibraryItem = (item: LibraryItem) => {
    if (!stateRef.current.confirmDelete) {
      dispatch({ type: "libraryConfirmDelete" });
      return;
    }
    fetch(handle.base + `/api/library/${item.id}`, { method: "DELETE" })
      .then(() => dispatch({ type: "libraryDeleteItem", id: item.id }))
      .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
  };

  const handleModelCommand = (arg: string | undefined) => {
    if (!arg) {
      fetchModels()
        .then((resp) => dispatch({ type: "modelList", resp }))
        .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
      return;
    }
    const cached = modelsRef.current
      ? Promise.resolve(modelsRef.current)
      : fetchModels();
    cached
      .then((resp) => {
        if (!resp.models.some((m) => m.name === arg)) {
          dispatch({ type: "error", message: `unknown model "${arg}" — /model to list` });
          return;
        }
        dispatch({ type: "setModel", model: arg });
        dispatch({ type: "notice", text: `model → ${arg}` });
        persist(stateRef.current.voice, stateRef.current.mode, arg);
      })
      .catch((err) => dispatch({ type: "error", message: String(err.message ?? err) }));
  };

  const handleCommand = (raw: string) => {
    const [cmd, arg] = raw.slice(1).split(/\s+/, 2);
    switch (cmd) {
      case "help":
        dispatch({ type: "toggleHelp" });
        break;
      case "quit":
      case "exit":
        startQuit();
        break;
      case "mode":
        if (!arg) {
          dispatch({ type: "notice", text: `mode is ${state.mode} — /mode full | summary` });
        } else if (arg === "full" || arg === "summary") {
          dispatch({ type: "setMode", mode: arg });
          dispatch({ type: "notice", text: `mode → ${arg}` });
          persist(state.voice, arg, state.model);
        } else {
          dispatch({ type: "error", message: `unknown mode "${arg}" — use full or summary` });
        }
        break;
      case "voice":
        if (!arg) {
          const list = cfg.voices_available
            .map((v) => `${v.id === state.voice ? "★" : " "} ${v.id}  —  ${v.label}`)
            .join("\n");
          dispatch({ type: "notice", text: `voices:\n${list}\n\n/voice <id> to switch` });
        } else if (voiceIds.includes(arg)) {
          dispatch({ type: "setVoice", voice: arg });
          dispatch({ type: "notice", text: `voice → ${arg}` });
          persist(arg, state.mode, state.model);
        } else {
          dispatch({ type: "error", message: `unknown voice "${arg}" — /voice to list` });
        }
        break;
      case "model":
        handleModelCommand(arg);
        break;
      case "library":
      case "lib":
        openLibrary();
        break;
      default:
        dispatch({ type: "error", message: `unknown command /${cmd} — /help` });
    }
  };

  const handleSubmit = (value: string) => {
    if (process.env.READBACK_CLI_DEBUG)
      require("node:fs").appendFileSync("/tmp/rbcli.log", `submit: ${JSON.stringify(value)}\n`);
    const isGlob = /[*?]/.test(value);
    // Slash commands are single-segment (/voice, /model, /help, …). Multi-segment
    // paths (/Users/…) and globs are not commands even if they start with /.
    const isSlashCommand = value.startsWith("/") && !value.slice(1).includes("/") && !isGlob;
    if (isSlashCommand) {
      handleCommand(value);
      return;
    }
    const isUrl = /^https?:\/\//i.test(value);
    const isLocalPath = value.startsWith("/") || isGlob || /^~/.test(value);
    if (!isUrl && !isLocalPath) {
      dispatch({ type: "error", message: "paste a URL, image path, or folder/glob (~/… or /path/to/)" });
      return;
    }
    player.stop();
    dispatch({ type: "submit" });
    sockRef.current?.read(value, state.mode, state.voice, state.model);
  };

  const voiceLabel =
    cfg.voices_available.find((v) => v.id === state.voice)?.label ?? state.voice;

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Header intro={state.screen === "input"} />

      <Box marginTop={1} flexDirection="column">
        {state.screen === "input" && (
          <>
            {state.modelList && <ModelList resp={state.modelList} active={state.model} />}
            {state.showHelp && <HelpView />}
            {state.notice && (
              <Box paddingX={1} marginBottom={1}>
                <Text color={DIM}>{state.notice}</Text>
              </Box>
            )}
            {state.error && (
              <Box paddingX={1} marginBottom={1}>
                <Text color={RED}>{state.error}</Text>
              </Box>
            )}
            <UrlInput onSubmit={handleSubmit} onQuit={startQuit} />
            <Box marginTop={1}>
              <StatusLine
                model={state.model}
                origin={handle.origin}
                voiceLabel={voiceLabel}
                mode={state.mode}
              />
            </Box>
          </>
        )}

        {state.screen === "busy" && (
          <BusyView
            phase={state.phase}
            progress={state.progress}
            onCancel={() => {
              sockRef.current?.cancel();
              dispatch({ type: "back" });
            }}
          />
        )}

        {state.screen === "player" && state.result && (
          <PlayerView
            result={state.result}
            wavPath={state.wavPath}
            player={state.player}
            showTranscript={state.showTranscript}
            onTogglePause={() => {
              const s = stateRef.current;
              if (s.player.state === "finished" && s.result) {
                player.play(s.wavPath, s.result.duration_sec);
              } else {
                player.togglePause();
              }
            }}
            onToggleTranscript={() => dispatch({ type: "toggleTranscript" })}
            onSeek={(delta) => player.seek(delta)}
            onBack={() => {
              player.stop();
              dispatch({ type: "back" });
            }}
          />
        )}

        {state.screen === "quitting" && <QuittingView />}

        {state.screen === "library" && (
          <LibraryView
            items={state.libraryItems}
            total={state.libraryTotal}
            cursor={state.libraryCursor}
            confirmDelete={state.confirmDelete}
            onMove={(delta) => dispatch({ type: "libraryMove", delta })}
            onPlay={(item) => {
              const result: DoneMsg = {
                type: "done",
                title: item.title,
                audio_url: `/audio/${item.audio_filename}`,
                duration_sec: item.duration_sec,
                word_count: item.word_count,
                mode: item.mode,
                text: item.summary ?? null,
              };
              resolveWav(handle.base, result.audio_url, cfg.audio_dir)
                .then((wavPath) => {
                  dispatch({ type: "done", result, wavPath });
                  player.play(wavPath, result.duration_sec);
                })
                .catch((err) =>
                  dispatch({ type: "error", message: String(err.message ?? err) })
                );
            }}
            onDelete={(item) => deleteLibraryItem(item)}
            onLoadMore={loadMoreLibrary}
            onBack={() => dispatch({ type: "back" })}
          />
        )}
      </Box>
    </Box>
  );
}
