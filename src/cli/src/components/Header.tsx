import React from "react";
import { Box, Text } from "ink";
import { BLUE, DIM, FG } from "../theme";
import { version } from "../../package.json";

// Half-block wordmark — plain Unicode block elements, renders in any mono font.
// "read" in white, "back" in blue. The lettering is the design; no icon art.
const MARK: Array<[read: string, back: string]> = [
  ["█▀█ █▀▀ ▄▀█ █▀▄ ", "█▄▄ ▄▀█ █▀▀ █▄▀"],
  ["█▀▄ ██▄ █▀█ █▄▀ ", "█▄█ █▀█ █▄▄ █ █"],
];

interface Props {
  /** Show the tagline + hint rows (input screen only — busy/player stay compact). */
  intro: boolean;
}

export function Header({ intro }: Props) {
  return (
    <Box flexDirection="column" paddingX={1}>
      <Box flexDirection="column">
        {MARK.map(([read, back], i) => (
          <Box key={i}>
            <Text color={FG}>{read}</Text>
            <Text color={BLUE}>{back}</Text>
          </Box>
        ))}
      </Box>
      <Box marginTop={1}>
        <Text color={DIM}>offline article reader · </Text>
        <Text color={BLUE}>v{version}</Text>
      </Box>
      {intro && (
        <Box flexDirection="column" marginTop={1}>
          <Text color={DIM}>
            turn any article or image into spoken audio — all on-device.
          </Text>
          <Box marginTop={1}>
            <Text color={DIM}>
              paste a <Text color={FG}>URL</Text>, <Text color={FG}>image</Text>, or{" "}
              <Text color={FG}>folder</Text> · <Text color={BLUE}>/lib</Text> ·{" "}
              <Text color={BLUE}>/voice</Text> · <Text color={BLUE}>/model</Text> ·{" "}
              <Text color={BLUE}>/mode</Text> · <Text color={BLUE}>/help</Text>
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}
