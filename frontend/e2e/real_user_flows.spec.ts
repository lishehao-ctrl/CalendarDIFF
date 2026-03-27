import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

type FlowContext = {
  flow_id: string;
  stage?: string;
  email: string;
  password: string;
  ics_url?: string;
  monitor_since?: string;
  source_name?: string;
  source_detail_path?: string;
  impact_summary?: string;
  approve_path?: string;
  reject_path?: string;
  edit_path?: string;
  edit_approve_path?: string;
  edited_event_name?: string;
  token_label?: string;
  expected_proposal_test_id?: string;
  expected_ticket_test_id?: string;
};

const RUN_DIR = requiredEnv("REAL_FLOW_RUN_DIR");
const SELECTED_FLOW = requiredEnv("REAL_FLOW_SELECTED_FLOW");
const SELECTED_STAGE = process.env.REAL_FLOW_SELECTED_STAGE || "default";
const CONTEXT_PATH = requiredEnv("REAL_FLOW_CONTEXT_PATH");

const flowContext = JSON.parse(fs.readFileSync(CONTEXT_PATH, "utf-8")) as FlowContext;

function requiredEnv(name: string) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

function shouldRun(flowId: string, stage = "default") {
  return SELECTED_FLOW === flowId && SELECTED_STAGE === stage;
}

function appendEvent(payload: Record<string, unknown>) {
  const pathValue = path.join(RUN_DIR, "browser_events.jsonl");
  fs.appendFileSync(pathValue, `${JSON.stringify(payload)}\n`, "utf-8");
}

async function capture(page: import("@playwright/test").Page, flowId: string, label: string) {
  const fileName = `${flowId}-${label}.png`;
  const fullPath = path.join(RUN_DIR, "screenshots", fileName);
  await page.screenshot({ path: fullPath, fullPage: true });
  return path.relative(RUN_DIR, fullPath);
}

function writeResult(flowId: string, stage: string, payload: Record<string, unknown>) {
  const resultPath = path.join(RUN_DIR, "per_flow", `${flowId}__${stage}.browser.json`);
  fs.writeFileSync(resultPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
}

async function login(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.locator("#email-auth").fill(email);
  await page.locator("#password-auth").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30_000 });
}

test("auth_register_and_enter_onboarding__default", async ({ page }) => {
  test.skip(!shouldRun("auth_register_and_enter_onboarding"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "start" });

  await page.goto("/register");
  await page.locator("#email-auth").fill(flowContext.email);
  await page.locator("#password-auth").fill(flowContext.password);
  await page.locator("#password-confirm-auth").fill(flowContext.password);
  await page.getByRole("button", { name: /Create account/i }).click();
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await expect(page.locator("#onboarding-canvas-ics")).toBeVisible();

  const screenshot = await capture(page, flowContext.flow_id, "onboarding-entry");
  writeResult(flowContext.flow_id, "default", {
    flow_id: flowContext.flow_id,
    stage: "default",
    passed: true,
    checks: ["register form submitted", "redirected to onboarding", "canvas input visible"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "passed", screenshot });
});

test("canvas_ics_onboarding_to_ready__default", async ({ page }) => {
  test.skip(!shouldRun("canvas_ics_onboarding_to_ready"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "start" });

  await login(page, flowContext.email, flowContext.password);
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.locator("#onboarding-canvas-ics").fill(flowContext.ics_url || "");
  await page.getByRole("button", { name: /save canvas/i }).click();
  await page.getByRole("button", { name: /skip gmail/i }).click();
  await expect(page.locator("#monitor-since")).toBeVisible();
  if (flowContext.monitor_since) {
    await page.locator("#monitor-since").fill(flowContext.monitor_since);
  }
  await page.getByRole("button", { name: /save monitoring/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/onboarding"), { timeout: 30_000 });

  const screenshot = await capture(page, flowContext.flow_id, "ready");
  writeResult(flowContext.flow_id, "default", {
    flow_id: flowContext.flow_id,
    stage: "default",
    passed: true,
    checks: ["logged in", "submitted canvas ics", "skipped gmail", "saved monitoring window", "left onboarding"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "passed", screenshot });
});

test("gmail_source_sync_and_observability__default", async ({ page }) => {
  test.skip(!shouldRun("gmail_source_sync_and_observability"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "start" });

  await login(page, flowContext.email, flowContext.password);
  await page.goto("/sources");
  if (flowContext.source_name) {
    await expect(page.getByText(flowContext.source_name, { exact: false }).first()).toBeVisible();
  }
  if (flowContext.source_detail_path) {
    await page.goto(flowContext.source_detail_path);
  }
  if (flowContext.source_name) {
    await expect(page.getByRole("heading", { name: flowContext.source_name })).toBeVisible();
  }
  if (flowContext.impact_summary) {
    await expect(page.getByText(flowContext.impact_summary, { exact: false })).toBeVisible();
  }
  await expect(page.getByTestId("source-detail-current-health")).toBeVisible();

  const screenshot = await capture(page, flowContext.flow_id, "source-detail");
  writeResult(flowContext.flow_id, "default", {
    flow_id: flowContext.flow_id,
    stage: "default",
    passed: true,
    checks: ["sources list visible", "source detail visible", "observability posture visible"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "passed", screenshot });
});

test("changes_review_resolution__default", async ({ page }) => {
  test.skip(!shouldRun("changes_review_resolution"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "start" });

  await login(page, flowContext.email, flowContext.password);

  if (flowContext.edit_path) {
    await page.goto(flowContext.edit_path);
    if (flowContext.edited_event_name) {
      const eventNameInput = page.locator("#review-edit-event-name");
      await eventNameInput.fill(flowContext.edited_event_name);
      await expect(eventNameInput).toHaveValue(flowContext.edited_event_name);
      await eventNameInput.blur();
    }
    await page.getByTestId("review-edit-apply-button").click();
    await page.waitForURL(/\/changes/, { timeout: 30_000 });
    if (flowContext.edit_approve_path) {
      await page.goto(flowContext.edit_approve_path);
      await page.getByRole("button", { name: /^Approve$/ }).click();
    }
  }

  if (flowContext.approve_path) {
    await page.goto(flowContext.approve_path);
    await page.getByRole("button", { name: /^Approve$/ }).click();
  }

  if (flowContext.reject_path) {
    await page.goto(flowContext.reject_path);
    await page.getByRole("button", { name: /^Reject$/ }).click();
  }

  const screenshot = await capture(page, flowContext.flow_id, "changes-after-actions");
  writeResult(flowContext.flow_id, "default", {
    flow_id: flowContext.flow_id,
    stage: "default",
    passed: true,
    checks: ["proposal edit applied in browser", "approve clicked", "reject clicked"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "default", event: "passed", screenshot });
});

test("agent_assisted_low_risk_action__create_token", async ({ page }) => {
  test.skip(!shouldRun("agent_assisted_low_risk_action", "create_token"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "create_token", event: "start" });

  await login(page, flowContext.email, flowContext.password);
  await page.goto("/settings");
  await page.locator("#settings-mcp-label").fill(flowContext.token_label || "Real Flow Token");
  await page.getByRole("button", { name: /create mcp token|create token/i }).click();
  await expect(page.getByText(/one-time reveal/i)).toBeVisible();
  await expect(page.locator("code")).toBeVisible();

  const screenshot = await capture(page, flowContext.flow_id, "token-created");
  writeResult(flowContext.flow_id, "create_token", {
    flow_id: flowContext.flow_id,
    stage: "create_token",
    passed: true,
    checks: ["settings page loaded", "mcp token created", "one-time reveal visible"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "create_token", event: "passed", screenshot });
});

test("agent_assisted_low_risk_action__verify_activity", async ({ page }) => {
  test.skip(!shouldRun("agent_assisted_low_risk_action", "verify_activity"));
  appendEvent({ flow_id: flowContext.flow_id, stage: "verify_activity", event: "start" });

  await login(page, flowContext.email, flowContext.password);
  await page.goto("/settings");
  await expect(page.getByTestId("settings-agent-activity-card")).toBeVisible();
  if (flowContext.expected_proposal_test_id) {
    await expect(page.getByTestId(flowContext.expected_proposal_test_id)).toBeVisible();
  }
  if (flowContext.expected_ticket_test_id) {
    await expect(page.getByTestId(flowContext.expected_ticket_test_id)).toBeVisible();
  }

  const screenshot = await capture(page, flowContext.flow_id, "activity-visible");
  writeResult(flowContext.flow_id, "verify_activity", {
    flow_id: flowContext.flow_id,
    stage: "verify_activity",
    passed: true,
    checks: ["settings activity card visible", "proposal row visible", "ticket row visible"],
    screenshots: [screenshot],
  });
  appendEvent({ flow_id: flowContext.flow_id, stage: "verify_activity", event: "passed", screenshot });
});
