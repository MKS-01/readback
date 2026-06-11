import React from "react";
import { Box, Text } from "ink";
import { DIM, FG } from "../theme";

interface Props {
  model: string;
  origin: "attached" | "spawned";
  voiceLabel: string;
  mode: "full" | "summary";
}

export function StatusLine({ model, origin, voiceLabel, mode }: Props) {
  return (
    <Box paddingX={1}>
      <Text color={DIM}>
        {"model "}
        <Text color={FG}>{model}</Text>
        {"  ·  voice "}
        <Text color={FG}>{voiceLabel}</Text>
        {"  ·  mode "}
        <Text color={FG}>{mode}</Text>
        {"  ·  server "}
        <Text color={FG}>{origin}</Text>
      </Text>
    </Box>
  );
}
