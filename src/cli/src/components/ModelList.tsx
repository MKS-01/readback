import React from "react";
import { Box, Text } from "ink";
import { BLUE, DIM, FG, GREEN, RED, YELLOW } from "../theme";

export interface ModelInfo {
  name: string;
  size_gb: number;
  params: string | null;
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

const FIT_LABEL: Record<ModelInfo["fit"], { text: string; color: string }> = {
  good: { text: "fits", color: GREEN },
  tight: { text: "tight", color: YELLOW },
  no: { text: "too big", color: RED },
};

interface Props {
  resp: ModelsResp;
  active: string;
}

// One list, one model: the pick drives Summary mode AND image / book OCR, so
// the server filters vision-only checkpoints out before we ever see them.
export function ModelList({ resp, active }: Props) {
  const models = resp.models;
  const heading = "models";
  const cmd = "/model";
  const purpose = "Summary mode + image / book OCR";

  if (models.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1} marginBottom={1}>
        <Text color={DIM}>
          no downloaded models found —
          download one with <Text color={BLUE}>hf download {"<id>"}</Text>
        </Text>
      </Box>
    );
  }

  const namePad = Math.max(...models.map((m) => m.name.length));
  const paramPad = Math.max(...models.map((m) => (m.params ?? "—").length));

  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Text color={DIM}>
        {heading} on this mac ({resp.total_ram_gb} GB):
      </Text>
      <Box marginTop={0} flexDirection="column">
        {models.map((m) => {
          const isActive = m.name === active;
          const isRec = m.name === resp.recommended;
          const fit = FIT_LABEL[m.fit];

          const marker = isActive ? "★" : isRec ? "→" : " ";

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
              {isRec && <Text color={BLUE}> recommended</Text>}
            </Box>
          );
        })}
      </Box>
      <Box marginTop={1}>
        <Text color={DIM}>
          <Text color={BLUE}>{cmd} {"<name>"}</Text> to switch · {purpose}
        </Text>
      </Box>
    </Box>
  );
}
