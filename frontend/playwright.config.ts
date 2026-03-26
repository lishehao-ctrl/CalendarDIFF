import path from "node:path";
import { defineConfig } from "@playwright/test";

const runDir = process.env.REAL_FLOW_RUN_DIR || "";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"]],
  outputDir: runDir ? path.join(runDir, "playwright-output") : path.join(process.cwd(), ".playwright-output"),
  use: {
    baseURL: process.env.REAL_FLOW_FRONTEND_BASE || "http://127.0.0.1:3000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
});
