import React from "react";
import { Box, Text } from "ink";
import { BLUE, DIM, FG, GREEN, RED, YELLOW } from "../theme";

export interface ModelInfo {
  name: string;
  size_gb: number;
  params: string | null;
  quant: string | null;
  fit: "good" | "tight" | "no";
  chat: boolean;
}

export interface ModelsResp {
  models: ModelInfo[];
  recommended: string | null;
  current: string;
  total_ram_gb: number;
  error?: string;
}

const FIT: Record<ModelInfo["fit"], { text: string; color: string }> = {
  good: { text: "fits", color: GREEN },
  tight: { text: "tight fit — will squeeze other apps", color: YELLOW },
  no: { text: "too big — would swap/thrash", color: RED },
};

interface Props {
  resp: ModelsResp;
  active: string;
}

export function ModelList({ resp, active }: Props) {
  const pad = Math.max(...resp.models.map((m) => m.name.length));
  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Text color={DIM}>models on this mac ({resp.total_ram_gb} GB):</Text>
      {resp.models.map((m) => {
        const isActive = m.name === active;
        const isRec = m.name === resp.recommended;
        const fit = m.chat
          ? FIT[m.fit]
          : { text: "embedding model — not for summaries", color: DIM };
        return (
          <Box key={m.name}>
            <Text color={isRec ? BLUE : FG}>
              {isActive ? "★" : isRec ? "→" : " "}{" "}
            </Text>
            <Text color={isActive ? FG : DIM}>{m.name.padEnd(pad)}</Text>
            <Text color={DIM}>
              {"  "}
              {String(m.size_gb).padStart(5)} GB · {m.params ?? "—"} ·{" "}
            </Text>
            <Text color={fit.color}>{fit.text}</Text>
            {isRec && <Text color={BLUE}> — recommended for summaries</Text>}
          </Box>
        );
      })}
      <Box marginTop={1}>
        <Text color={DIM}>
          <Text color={BLUE}>/model {"<name>"}</Text> to switch · used by Summary
          mode only
        </Text>
      </Box>
    </Box>
  );
}
