import React from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { BLUE, DIM, FG, RED } from "../theme";

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
  onMove: (delta: number) => void;
  onPlay: (item: LibraryItem) => void;
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
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function LibraryView({
  items,
  total,
  cursor,
  confirmDelete,
  onMove,
  onPlay,
  onDelete,
  onLoadMore,
  onBack,
}: Props) {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  // leave room for prefix + meta suffix
  const titleWidth = Math.max(10, termWidth - 36);

  useInput((input, key) => {
    if (key.upArrow) { onMove(-1); return; }
    if (key.downArrow) { onMove(1); return; }
    if (key.return && items.length > 0) { onPlay(items[cursor]); return; }
    if (input === "n") { onLoadMore(); return; }
    if (input === "d" && items.length > 0) { onDelete(items[cursor]); return; }
    if (input === "q" || key.escape) { onBack(); return; }
  });

  const hasMore = items.length < total;

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color={DIM}>
        library — {items.length} of {total} reads
      </Text>

      <Box flexDirection="column" marginTop={1}>
        {items.length === 0 && (
          <Text color={DIM}>no reads yet — paste a URL on the input screen to get started</Text>
        )}
        {items.map((item, i) => {
          const active = i === cursor;
          const title =
            item.title.length > titleWidth
              ? item.title.slice(0, titleWidth - 1) + "…"
              : item.title.padEnd(titleWidth);
          const meta = `${item.mode === "summary" ? "sum" : "full"}  ${fmt(item.duration_sec)}  ${fmtDate(item.created_at)}`;
          return (
            <Box key={item.id}>
              <Text color={active ? BLUE : DIM}>{active ? "▸ " : "  "}</Text>
              <Text color={active ? FG : DIM}>{title}</Text>
              <Text color={DIM}>  {meta}</Text>
            </Box>
          );
        })}
      </Box>

      {confirmDelete && items[cursor] && (
        <Box marginTop={1}>
          <Text color={RED}>delete "{items[cursor].title}"? press </Text>
          <Text color={FG}>d</Text>
          <Text color={RED}> again to confirm</Text>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        <Text color={DIM}>
          <Text color={FG}>↑↓</Text> navigate{"  ·  "}
          <Text color={FG}>enter</Text> play{"  ·  "}
          <Text color={FG}>d</Text> delete{"  ·  "}
          {hasMore && (
            <>
              <Text color={FG}>n</Text>
              {" "}load more{"  ·  "}
            </>
          )}
          <Text color={FG}>esc</Text> back
        </Text>
      </Box>
    </Box>
  );
}
