import React, { useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { BLUE, DIM } from "../theme";

interface Props {
  onSubmit: (value: string) => void;
}

export function UrlInput({ onSubmit }: Props) {
  const [value, setValue] = useState("");

  const submit = (v: string) => {
    const trimmed = v.trim();
    if (!trimmed) return;
    setValue("");
    onSubmit(trimmed);
  };

  return (
    <Box borderStyle="round" borderColor={DIM} paddingX={1}>
      <Text color={BLUE}>{"❯ "}</Text>
      <TextInput
        value={value}
        onChange={(v) => {
          // a paste with a trailing newline should submit, not insert
          if (/[\r\n]/.test(v)) submit(v.replace(/[\r\n]+/g, " "));
          else setValue(v);
        }}
        onSubmit={submit}
        placeholder="Paste an article URL…  (/help for commands)"
      />
    </Box>
  );
}
