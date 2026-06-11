import React, { useEffect, useReducer, useRef } from "react";
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

const HELP = `/voice            list voices
/voice <id>       switch voice
/mode             show mode
/mode full        read the whole article
/mode summary     spoken summary (local LLM)
/quit             exit

player keys: space pause/resume · ←/→ seek ±5s · t transcript · q back`;

interface State {
  screen: "input" | "busy" | "player";
  error: string | null;
  notice: string | null;
  phase: string;
  progress: { done: number; total: number } | null;
  result: DoneMsg | null;
  wavPath: string;
  player: PlayerSnapshot;
  showTranscript: boolean;
  voice: string;
  mode: "full" | "summary";
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
  | { type: "notice"; text: string | null };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "submit":
      return { ...state, screen: "busy", phase: "connecting", progress: null, error: null, notice: null };
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
      return { ...state, screen: "input", error: action.message, notice: null };
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
    case "notice":
      return { ...state, notice: action.text, error: null };
  }
}

async function resolveWav(base: string, audioUrl: string): Promise<string> {
  const fname = audioUrl.split("/").pop()!;
  const local = join(homedir(), ".readback", "reader", fname);
  if (existsSync(local)) return local;
  const dir = join(homedir(), ".readback", "reader", "cli");
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
    phase: "connecting",
    progress: null,
    result: null,
    wavPath: "",
    player: { state: "stopped" as const, elapsed: 0 },
    showTranscript: false,
    voice: prefs.voice && voiceIds.includes(prefs.voice) ? prefs.voice : cfg.voice,
    mode: prefs.mode ?? cfg.default_mode,
  });

  const sockRef = useRef<ReadbackSocket | null>(null);
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
            resolveWav(handle.base, msg.audio_url)
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

  const persist = (voice: string, mode: "full" | "summary") => savePrefs({ voice, mode });

  const handleCommand = (raw: string) => {
    const [cmd, arg] = raw.slice(1).split(/\s+/, 2);
    switch (cmd) {
      case "help":
        dispatch({ type: "notice", text: HELP });
        break;
      case "quit":
      case "exit":
        quit();
        break;
      case "mode":
        if (!arg) {
          dispatch({ type: "notice", text: `mode is ${state.mode} — /mode full | summary` });
        } else if (arg === "full" || arg === "summary") {
          dispatch({ type: "setMode", mode: arg });
          dispatch({ type: "notice", text: `mode → ${arg}` });
          persist(state.voice, arg);
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
          persist(arg, state.mode);
        } else {
          dispatch({ type: "error", message: `unknown voice "${arg}" — /voice to list` });
        }
        break;
      default:
        dispatch({ type: "error", message: `unknown command /${cmd} — /help` });
    }
  };

  const handleSubmit = (value: string) => {
    if (process.env.READBACK_CLI_DEBUG)
      require("node:fs").appendFileSync("/tmp/rbcli.log", `submit: ${JSON.stringify(value)}\n`);
    if (value.startsWith("/")) {
      handleCommand(value);
      return;
    }
    if (!/^https?:\/\//i.test(value)) {
      dispatch({ type: "error", message: "that doesn't look like a URL (https://…)" });
      return;
    }
    player.stop();
    dispatch({ type: "submit" });
    sockRef.current?.read(value, state.mode, state.voice);
  };

  const voiceLabel =
    cfg.voices_available.find((v) => v.id === state.voice)?.label ?? state.voice;

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Header intro={state.screen === "input"} />

      <Box marginTop={1} flexDirection="column">
        {state.screen === "input" && (
          <>
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
            <UrlInput onSubmit={handleSubmit} />
            <Box marginTop={1}>
              <StatusLine
                model={cfg.model}
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
      </Box>
    </Box>
  );
}
