// Thin client over the readback library REST API. Same origin in production
// (FastAPI serves this SPA at /); the Vite dev server proxies /api + /audio.

export type Sort = "newest" | "oldest";

// One library card (shape of GET /api/library rows).
export interface Read {
  id: string;
  title: string;
  summary: string | null;
  excerpt: string;
  source_url: string;
  mode: "full" | "summary";
  voice: string;
  duration_sec: number;
  word_count: number;
  audio_filename: string;
  created_at: string;
}

// A page of library cards (shape of GET /api/library).
export interface Page {
  items: Read[];
  total: number;
  limit: number;
  offset: number;
}

export async function listReads(
  q: string,
  sort: Sort,
  limit: number,
  offset: number,
): Promise<Page> {
  const params = new URLSearchParams({ sort, limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  const res = await fetch(`/api/library?${params}`);
  if (!res.ok) throw new Error(`library list failed: ${res.status}`);
  return res.json();
}

export async function deleteRead(id: string): Promise<void> {
  const res = await fetch(`/api/library/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

export function audioUrl(filename: string): string {
  return `/audio/${filename}`;
}
