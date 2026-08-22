import React from "react";
import { Box, Text, useStdout } from "ink";
import { BLUE, DIM, FG } from "../theme";

export interface FeedItem {
  title: string;
  url: string;
  source: string;
  published: string | null;
}

interface Props {
  items: FeedItem[];
  loading: boolean;
  error: string | null;
}

// "2h" / "3d" / "1w" — a pick line has room for two characters of recency, and
// an exact timestamp tells you nothing useful about a blog post.
function age(published: string | null): string {
  if (!published) return "new";
  const ms = Date.now() - new Date(published).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "new";
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return "now";
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return d < 7 ? `${d}d` : `${Math.floor(d / 7)}w`;
}

export function PickList({ items, loading, error }: Props) {
  const { stdout } = useStdout();
  const width = (stdout?.columns ?? 80) - 4;

  if (error) {
    return (
      <Box paddingX={1} marginBottom={1}>
        <Text color={DIM}>picks unavailable — {error}</Text>
      </Box>
    );
  }
  if (loading && items.length === 0) {
    return (
      <Box paddingX={1} marginBottom={1}>
        <Text color={DIM}>fetching the latest…</Text>
      </Box>
    );
  }
  if (items.length === 0) return null;

  // The meta column is right-aligned as a block: titles are padded to the
  // widest (truncated) title so `source · age` lines up down the list instead
  // of ragging along the ends of the headlines.
  const metas = items.map((it) => `${it.source} · ${age(it.published)}`);
  const metaWidth = Math.max(...metas.map((m) => m.length));
  const maxTitle = Math.max(20, width - metaWidth - 6);
  const titles = items.map((it) =>
    it.title.length > maxTitle ? it.title.slice(0, maxTitle - 1) + "…" : it.title
  );
  const titleWidth = Math.max(...titles.map((t) => t.length));

  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Text>
        <Text color={FG} bold>latest</Text>
        <Text color={DIM}>{"  —  press a number to hear the summary"}</Text>
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {items.map((it, i) => (
          <Box key={it.url}>
            <Text color={BLUE}>{` ${i + 1} `}</Text>
            <Text color={FG}>{titles[i].padEnd(titleWidth)}</Text>
            <Text color={DIM}>{"  " + metas[i].padStart(metaWidth)}</Text>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
