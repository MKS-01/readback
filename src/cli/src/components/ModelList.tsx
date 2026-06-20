import React from "react";
import { Box, Text } from "ink";
import { BLUE, DIM, FG, GREEN, RED, YELLOW } from "../theme";

export interface ModelInfo {
  name: string;
  size_gb: number;
  params: string | null;
  fit: "good" | "tight" | "no";
  chat: boolean;
  vision: boolean;
}

export interface ModelsResp {
  models: ModelInfo[];
  recommended: string | null;
  current: string;
  current_vision: string;
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
  // "chat" → /model (summary LLM); "vision" → /vision (image/book OCR).
  kind?: "chat" | "vision";
}

export function ModelList({ resp, active, kind = "chat" }: Props) {
  const models = resp.models.filter((m) => (kind === "vision" ? m.vision : m.chat));
  const heading = kind === "vision" ? "vision (OCR) models" : "models";
  const cmd = kind === "vision" ? "/vision" : "/model";
  const purpose = kind === "vision" ? "image / book OCR" : "Summary mode only";

  if (models.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1} marginBottom={1}>
        <Text color={DIM}>
          no downloaded {kind === "vision" ? "vision" : "chat"} models found —
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
          // The summary recommendation only applies to the chat picker.
          const isRec = kind === "chat" && m.name === resp.recommended;
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
