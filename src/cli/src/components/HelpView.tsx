import React from "react";
import { Box, Text } from "ink";
import { BLUE, DIM, FG } from "../theme";

const CMDS: Array<[cmd: string, desc: string]> = [
  ["/voice",          "list voices"],
  ["/voice <id>",     "switch voice"],
  ["/model",          "list models (RAM fit + suggestion)"],
  ["/model <name>",   "switch summary model"],
  ["/mode",           "show current mode"],
  ["/mode full",      "read the whole article"],
  ["/mode summary",   "spoken summary (local LLM)"],
  ["/lib",            "browse past reads"],
  ["/quit",           "exit"],
];

const KEYS: Array<[key: string, desc: string]> = [
  ["space",  "pause / resume"],
  ["← →",   "seek ±5s"],
  ["t",      "toggle transcript"],
  ["q",      "back"],
];

export function HelpView() {
  const cmdPad = Math.max(...CMDS.map(([c]) => c.length)) + 2;

  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Text color={FG} bold>commands</Text>
      <Box flexDirection="column" marginTop={0}>
        {CMDS.map(([cmd, desc]) => (
          <Text key={cmd}>
            <Text color={BLUE}>{cmd.padEnd(cmdPad)}</Text>
            <Text color={DIM}>{desc}</Text>
          </Text>
        ))}
      </Box>

      <Box marginTop={1}>
        <Text color={FG} bold>player</Text>
      </Box>
      <Box flexDirection="column" marginTop={0}>
        {KEYS.map(([key, desc]) => (
          <Text key={key}>
            <Text color={FG}>{key.padEnd(8)}</Text>
            <Text color={DIM}>{desc}</Text>
          </Text>
        ))}
      </Box>
    </Box>
  );
}
