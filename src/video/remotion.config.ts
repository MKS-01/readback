import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
// GIF export uses --codec=gif from the npm script; H.264 is the default for MP4.
