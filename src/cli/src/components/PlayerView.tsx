import React, { useMemo } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { basename } from "node:path";
import type { DoneMsg } from "../ws";
import type { PlayerSnapshot } from "../player";
import { BLUE, DIM, FG } from "../theme";

const SEEK_STEP_SEC = 5;
const TRANSCRIPT_MAX_LINES = 12;

function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function Transcript({
  text,
  elapsed,
  total,
}: {
  text: string;
  elapsed: number;
  total: number;
}) {
  const { stdout } = useStdout();
  const width = Math.max(20, (stdout?.columns ?? 80) - 10);

  const { lines, cumWeights } = useMemo(() => {
    const words = text.split(/\s+/).filter(Boolean);
    const cum: number[] = [];
    let acc = 0;
    for (const w of words) {
      acc += w.length;
      cum.push(acc);
    }
    const ls: string[][] = [];
    let line: string[] = [];
    let len = 0;
    for (const w of words) {
      const add = line.length === 0 ? w.length : len + 1 + w.length;
      if (line.length > 0 && add > width) {
        ls.push(line);
        line = [w];
        len = w.length;
      } else {
        line.push(w);
        len = add;
      }
    }
    if (line.length) ls.push(line);
    return { lines: ls, cumWeights: cum };
  }, [text, width]);

  const totalWeight = cumWeights[cumWeights.length - 1] ?? 0;
  const target = total > 0 ? (elapsed / total) * totalWeight : 0;
  let spoken = 0;
  while (spoken < cumWeights.length && cumWeights[spoken] <= target) spoken++;

  // Scroll window: keep the current spoken word visible with context
  let startLine = 0;
  if (lines.length > TRANSCRIPT_MAX_LINES) {
    let wordIdx = 0;
    for (let li = 0; li < lines.length; li++) {
      wordIdx += lines[li].length;
      if (wordIdx >= spoken) {
        startLine = Math.max(0, li - Math.floor(TRANSCRIPT_MAX_LINES / 3));
        break;
      }
    }
    startLine = Math.min(startLine, lines.length - TRANSCRIPT_MAX_LINES);
  }
  const visibleLines = lines.slice(startLine, startLine + TRANSCRIPT_MAX_LINES);
  const globalWordStart = lines.slice(0, startLine).reduce((s, l) => s + l.length, 0);

  let i = globalWordStart;
  return (
    <Box flexDirection="column">
      {visibleLines.map((line, li) => {
        const start = i;
        i += line.length;
        const blueCount = Math.min(Math.max(spoken - start, 0), line.length);
        const blue = line.slice(0, blueCount).join(" ");
        const dim = line.slice(blueCount).join(" ");
        return (
          <Text key={startLine + li}>
            <Text color={BLUE}>{blue}</Text>
            <Text color={DIM}>{(blue && dim ? " " : "") + dim}</Text>
          </Text>
        );
      })}
      {lines.length > TRANSCRIPT_MAX_LINES && (
        <Text color={DIM}>
          {"  "}⋯ {lines.length - TRANSCRIPT_MAX_LINES} more lines
        </Text>
      )}
    </Box>
  );
}

interface Props {
  result: DoneMsg;
  wavPath: string;
  player: PlayerSnapshot;
  showTranscript: boolean;
  onTogglePause: () => void;
  onToggleTranscript: () => void;
  onSeek: (deltaSec: number) => void;
  onBack: () => void;
}

export function PlayerView({
  result,
  wavPath,
  player,
  showTranscript,
  onTogglePause,
  onToggleTranscript,
  onSeek,
  onBack,
}: Props) {
  const { stdout } = useStdout();
  const timeWidth = 10; // "0:00 " + " 0:00"
  const iconWidth = 3;
  const barWidth = Math.max(16, Math.min((stdout?.columns ?? 80) - 8 - timeWidth - iconWidth, 56));

  useInput((input, key) => {
    if (input === " ") onTogglePause();
    else if (key.leftArrow) onSeek(-SEEK_STEP_SEC);
    else if (key.rightArrow) onSeek(SEEK_STEP_SEC);
    else if (input === "t" && result.text) onToggleTranscript();
    else if (input === "q" || key.escape) onBack();
  });

  const total = result.duration_sec;
  const pos = Math.min(player.elapsed / Math.max(total, 0.01), 1);
  const filled = Math.round(pos * barWidth);
  const icon = player.state === "playing" ? "❚❚" : player.state === "finished" ? "↺ " : "▸ ";
  const modeLabel = result.mode === "summary" ? "Summary" : "Full article";
  const wavName = basename(wavPath);

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color={FG} bold>
        {result.title}
      </Text>
      <Text color={DIM}>
        {modeLabel} · {result.word_count} words · {fmt(total)}
        {result.timings?.total != null && (
          <Text color={DIM}> · {result.timings.total.toFixed(1)}s to generate</Text>
        )}
      </Text>

      <Box marginTop={1}>
        <Text color={FG}>{icon} </Text>
        <Text color={DIM}>{fmt(player.elapsed)} </Text>
        <Text>
          <Text color={BLUE}>{"━".repeat(filled)}</Text>
          <Text color={DIM}>{"─".repeat(Math.max(0, barWidth - filled))}</Text>
        </Text>
        <Text color={DIM}> {fmt(total)}</Text>
      </Box>

      {result.text && showTranscript && (
        <Box borderStyle="round" borderColor={DIM} paddingX={1} paddingY={1} marginTop={1}>
          <Transcript text={result.text} elapsed={player.elapsed} total={total} />
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        <Text color={DIM}>
          <Text color={FG}>space</Text> {player.state === "finished" ? "replay" : "pause/resume"}
          {"  ·  "}
          <Text color={FG}>←/→</Text> ±{SEEK_STEP_SEC}s
          {result.text && (
            <>
              {"  ·  "}
              <Text color={FG}>t</Text> {showTranscript ? "hide" : "show"} transcript
            </>
          )}
          {"  ·  "}
          <Text color={FG}>q</Text> back
        </Text>
        <Text color={DIM}>↓ {wavName}</Text>
      </Box>
    </Box>
  );
}
