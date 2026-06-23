import React from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { BLUE, DIM, FG, RED } from "../theme";
import type { PlayerSnapshot } from "../player";

export interface LibraryItem {
  id: string;
  title: string;
  mode: string;
  voice: string;
  duration_sec: number;
  word_count: number;
  audio_filename: string;
  created_at: string;
  summary: string | null;
}

interface Props {
  items: LibraryItem[];
  total: number;
  cursor: number;
  confirmDelete: boolean;
  player: PlayerSnapshot;
  previewId: string | null;
  onMove: (delta: number) => void;
  onPlay: (item: LibraryItem) => void;
  onPreview: (item: LibraryItem) => void;
  onDelete: (item: LibraryItem) => void;
  onLoadMore: () => void;
  onBack: () => void;
}

function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d.getDate()} ${months[d.getMonth()]}`;
}

export function LibraryView({
  items,
  total,
  cursor,
  confirmDelete,
  player,
  previewId,
  onMove,
  onPlay,
  onPreview,
  onDelete,
  onLoadMore,
  onBack,
}: Props) {
  const { stdout } = useStdout();
  const termWidth = (stdout?.columns ?? 80) - 4;

  useInput((input, key) => {
    if (key.upArrow) { onMove(-1); return; }
    if (key.downArrow) { onMove(1); return; }
    if (key.return && items.length > 0) { onPlay(items[cursor]); return; }
    if (input === " " && items.length > 0) { onPreview(items[cursor]); return; }
    if (input === "n") { onLoadMore(); return; }
    if (input === "d" && items.length > 0) { onDelete(items[cursor]); return; }
    if (input === "q" || key.escape) { onBack(); return; }
  });

  const hasMore = items.length < total;
  const selected = items[cursor] ?? null;

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text>
        <Text color={FG} bold>library</Text>
        <Text color={DIM}> — {total} reads</Text>
      </Text>

      <Box flexDirection="column" marginTop={1}>
        {items.length === 0 && (
          <Text color={DIM}>no reads yet — paste a URL on the input screen</Text>
        )}
        {items.map((item, i) => {
          const active = i === cursor;
          const meta = `${item.mode === "summary" ? "summary" : "full"} · ${fmt(item.duration_sec)} · ${item.word_count} words · ${fmtDate(item.created_at)}`;
          const maxTitle = termWidth - meta.length - 6;
          const title =
            item.title.length > maxTitle
              ? item.title.slice(0, maxTitle - 1) + "…"
              : item.title;
          return (
            <Box key={item.id}>
              <Text color={active ? BLUE : DIM}>
                {previewId === item.id && player.state === "playing" ? "♫ " : active ? "▸ " : "  "}
              </Text>
              <Text color={active ? FG : DIM} bold={active}>{title}</Text>
              <Text color={active ? BLUE : DIM} dimColor={!active}>{"  "}{meta}</Text>
              {previewId === item.id && player.state === "playing" && (
                <Text color={BLUE}>{"  "}{fmt(player.elapsed)}</Text>
              )}
            </Box>
          );
        })}
      </Box>

      {selected?.summary && (
        <Box marginTop={1} paddingX={2}>
          <Text color={DIM} dimColor>
            {selected.summary.length > termWidth * 2
              ? selected.summary.slice(0, termWidth * 2 - 1) + "…"
              : selected.summary}
          </Text>
        </Box>
      )}

      {confirmDelete && selected && (
        <Box marginTop={1}>
          <Text color={RED}>
            delete "{selected.title.slice(0, 40)}"? press{" "}
          </Text>
          <Text color={FG}>d</Text>
          <Text color={RED}> again</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color={DIM}>
          <Text color={FG}>↑↓</Text> navigate{"  ·  "}
          <Text color={FG}>space</Text> preview{"  ·  "}
          <Text color={FG}>enter</Text> play{"  ·  "}
          <Text color={FG}>d</Text> delete
          {hasMore && (
            <>
              {"  ·  "}
              <Text color={FG}>n</Text> more
            </>
          )}
          {"  ·  "}
          <Text color={FG}>esc</Text> back
        </Text>
      </Box>
    </Box>
  );
}
