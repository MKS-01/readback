import React, { useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { BLUE, DIM } from "../theme";

interface Props {
  onSubmit: (value: string) => void;
  onQuit?: () => void;
  /** A digit typed into the EMPTY field picks that numbered item from the
   * latest list. Guarded on `value === ""` so a digit inside a URL or a path
   * still types normally. */
  onPick?: (n: number) => void;
  pickCount?: number;
}

export function UrlInput({ onSubmit, onQuit, onPick, pickCount = 0 }: Props) {
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
          // 'q' when the field is empty → quit shortcut
          else if (v === "q" && value === "") onQuit?.();
          // 1..N on an empty field → read that pick from the latest list
          else if (value === "" && pickCount > 0 && /^[1-9]$/.test(v) && Number(v) <= pickCount)
            onPick?.(Number(v));
          else setValue(v);
        }}
        onSubmit={submit}
        placeholder="Paste a URL or image path…  (/help for commands)"
      />
    </Box>
  );
}
