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
  vision: boolean;
}

export interface ModelsResp {
  models: ModelInfo[];
  recommended: string | null;
  current: string;
  total_ram_gb: number;
  error?: string;
}

const FIT_LABEL: Record<ModelInfo["fit"], { text: string; color: string }> = {
  good: { text: "fits", color: GREEN },
  tight: { text: "tight", color: YELLOW },
  no: { text: "too big", color: RED },
};

interface Props {
  resp: ModelsResp;
  active: string;
}

export function ModelList({ resp, active }: Props) {
  const namePad = Math.max(...resp.models.map((m) => m.name.length));
  const paramPad = Math.max(...resp.models.map((m) => (m.params ?? "—").length));

  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Text color={DIM}>
        models on this mac ({resp.total_ram_gb} GB):
      </Text>
      <Box marginTop={0} flexDirection="column">
        {resp.models.map((m) => {
          const isActive = m.name === active;
          const isRec = m.name === resp.recommended;
          const fit = m.chat
            ? FIT_LABEL[m.fit]
            : { text: "embed", color: DIM };

          const marker = isActive ? "★" : isRec ? "→" : " ";
          const tags: string[] = [];
          if (m.vision) tags.push("vision");
          if (isRec) tags.push("recommended");

          return (
            <Box key={m.name}>
              <Text color={isActive ? BLUE : isRec ? BLUE : DIM}>
                {marker}{" "}
              </Text>
              <Text color={isActive ? FG : DIM}>
                {m.name.padEnd(namePad)}
              </Text>
              <Text color={DIM}>
                {"  "}
                {String(m.size_gb).padStart(5)} GB
                {"  "}
                {(m.params ?? "—").padEnd(paramPad)}
                {"  "}
              </Text>
              <Text color={fit.color}>{fit.text.padEnd(7)}</Text>
              {tags.length > 0 && (
                <Text color={BLUE}> {tags.join(" · ")}</Text>
              )}
            </Box>
          );
        })}
      </Box>
      <Box marginTop={1}>
        <Text color={DIM}>
          <Text color={BLUE}>/model {"<name>"}</Text> to switch · Summary mode only
        </Text>
      </Box>
    </Box>
  );
}
