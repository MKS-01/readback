/* Design system entry point — imports all components and registers them
   on the global namespace so UI kits and templates can access them.
   Built with: bun build _ds_entry.jsx --outfile _ds_bundle.js --format iife --external react */

import React from "react";

import { Badge } from "./components/feedback/Badge.jsx";
import { Button } from "./components/core/Button.jsx";
import { Caret, PromptLine } from "./components/core/PromptLine.jsx";
import { SearchInput } from "./components/forms/SearchInput.jsx";
import { SeekBar } from "./components/player/SeekBar.jsx";
import { WaveformPlayer } from "./components/player/WaveformPlayer.jsx";
import { ReadCard } from "./components/content/ReadCard.jsx";
import { Wordmark } from "./components/brand/Wordmark.jsx";
import { SectionHeader } from "./components/layout/SectionHeader.jsx";

const NS = {
  Badge,
  Button,
  Caret,
  PromptLine,
  SearchInput,
  SeekBar,
  WaveformPlayer,
  ReadCard,
  Wordmark,
  SectionHeader,
};

window.ReadbackDesignSystem_7af2ab = NS;
