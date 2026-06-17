import React, { useEffect, useState } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { BLUE, DIM, FG, RED } from "../theme";

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

const PHASE_LABELS: Record<string, string> = {
  connecting: "connecting",
  loading: "loading models",
  fetching: "fetching article",
  summarizing: "summarizing",
  synthesizing: "synthesizing",
};

interface Props {
  phase: string;
  progress: { done: number; total: number } | null;
  onCancel: () => void;
}

export function BusyView({ phase, progress, onCancel }: Props) {
  const [frame, setFrame] = useState(0);
  const { stdout } = useStdout();
  const barWidth = Math.max(20, Math.min((stdout?.columns ?? 80) - 8, 72));

  useEffect(() => {
    const t = setInterval(() => setFrame((f) => (f + 1) % SPINNER.length), 90);
    return () => clearInterval(t);
  }, []);

  useInput((_input, key) => {
    if (key.escape) onCancel();
  });

  const label = PHASE_LABELS[phase] ?? phase;
  const pct = progress ? Math.round((progress.done / Math.max(progress.total, 1)) * 100) : 0;
  const filled = progress ? Math.round((progress.done / Math.max(progress.total, 1)) * barWidth) : 0;

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Box>
        <Text color={BLUE}>{SPINNER[frame]} </Text>
        <Text color={FG}>{label}</Text>
        {progress && (
          <Text color={DIM}>
            {"  "}
            {progress.done}/{progress.total}
            {"  "}
            <Text color={BLUE}>{pct}%</Text>
          </Text>
        )}
      </Box>

      <Box marginTop={1}>
        <Text>
          <Text color={BLUE}>{"━".repeat(filled)}</Text>
          <Text color={DIM}>{"─".repeat(Math.max(0, barWidth - filled))}</Text>
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color={DIM}>
          press <Text color={RED}>esc</Text> to cancel
        </Text>
      </Box>
    </Box>
  );
}
