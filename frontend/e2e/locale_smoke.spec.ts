import { expect, test, type Browser, type Page } from "@playwright/test";

const LOCALE_STORAGE_KEY = "calendardiff.locale";
const LOCALE_COOKIE_KEY = "calendardiff_locale";
const BASE_URL = process.env.REAL_FLOW_FRONTEND_BASE || "http://127.0.0.1:3000";
const BACKEND_HEALTH_URL = process.env.REAL_FLOW_BACKEND_HEALTH || "http://127.0.0.1:8200/health";
const REGISTERED_EMAIL = `locale-smoke-${Date.now()}@example.com`;
const REGISTERED_PASSWORD = "LocaleSmokePass!234";

function appUrl(route: string) {
  return new URL(route, BASE_URL).toString();
}

async function backendAvailable() {
  try {
    const response = await fetch(BACKEND_HEALTH_URL);
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForSettled(page: Page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
}

async function expectDocumentLocale(page: Page, locale: "en" | "zh-CN") {
  await expect
    .poll(async () => page.evaluate(() => document.documentElement.lang))
    .toBe(locale);
}

async function switchAuthLocale(page: Page, locale: "en" | "zh-CN") {
  const button = page.getByTestId(`auth-locale-${locale}`);
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expectDocumentLocale(page, locale);
}

async function expectAuthValues(page: Page, values: { email: string; password: string; confirmPassword?: string }) {
  await expect(page.locator("#email-auth")).toHaveValue(values.email);
  await expect(page.locator("#password-auth")).toHaveValue(values.password);
  if (values.confirmPassword !== undefined) {
    await expect(page.locator("#password-confirm-auth")).toHaveValue(values.confirmPassword);
  }
}

async function submitAuth(page: Page, mode: "login" | "register") {
  const form = page.locator("form");
  await form.getByRole("button", { name: mode === "login" ? /^Sign in$|^登录$/ : /^Create account$|^创建账号$/ }).click();
}

async function expectLegalMetadataFromLink(page: Page, linkLabel: string, expectedTitle: string) {
  await Promise.all([
    page.waitForURL(/\/privacy|\/terms/, { timeout: 30_000 }),
    page.getByRole("link", { name: linkLabel }).click(),
  ]);
  await waitForSettled(page);
  await expect(page.getByTestId("legal-page")).toBeVisible();
  await expect.poll(async () => page.title()).toBe(`${expectedTitle} | CalendarDIFF`);
  const summary = await page.getByTestId("legal-page").locator("h1 + p").first().innerText();
  await expect
    .poll(async () =>
      page.locator('meta[name="description"]').evaluate((node) => node.getAttribute("content") || ""),
    )
    .toBe(summary);
}

async function openPreviewRoute(page: Page, route: string, locale: "en" | "zh-CN", marker: string) {
  await page.goto("/preview");
  await page.evaluate(
    ([storageKey, nextLocale]) => {
      window.localStorage.setItem(storageKey, nextLocale);
    },
    [LOCALE_STORAGE_KEY, locale] as const,
  );
  await page.goto(route);
  await waitForSettled(page);
  await expect(page.getByText(marker, { exact: false }).first()).toBeVisible();
}

async function expectPreviewRouteFromStoredLocale(
  browser: Browser,
  route: string,
  locale: "en" | "zh-CN",
  marker: string,
  settingsLabel?: string,
) {
  const context = await browser.newContext();
  await context.addCookies([{ name: LOCALE_COOKIE_KEY, value: locale, url: BASE_URL }]);
  await context.addInitScript(
    ([storageKey, nextLocale]) => {
      window.localStorage.setItem(storageKey, nextLocale);
    },
    [LOCALE_STORAGE_KEY, locale] as const,
  );

  try {
    const page = await context.newPage();
    await page.goto(appUrl(route));
    await waitForSettled(page);
    await expect(page.getByText(marker, { exact: false }).first()).toBeVisible();
    if (settingsLabel) {
      await expect(page.getByTestId("settings-locale-switch")).toContainText(settingsLabel);
    }
  } finally {
    await context.close();
  }
}

test.describe.serial("locale smoke", () => {
  test.setTimeout(120_000);

  test("public auth locale toggle and legal metadata", async ({ page }) => {
    await page.goto(appUrl("/register"));
    await waitForSettled(page);

    await page.locator("#email-auth").fill(REGISTERED_EMAIL);
    await page.locator("#password-auth").fill(REGISTERED_PASSWORD);
    await page.locator("#password-confirm-auth").fill(REGISTERED_PASSWORD);

    await switchAuthLocale(page, "zh-CN");
    await expect(page.getByTestId("auth-locale-switch")).toContainText("语言");
    await expectAuthValues(page, {
      email: REGISTERED_EMAIL,
      password: REGISTERED_PASSWORD,
      confirmPassword: REGISTERED_PASSWORD,
    });

    await expectLegalMetadataFromLink(page, "隐私政策", "隐私政策");
    await page.goBack();
    await waitForSettled(page);
    await switchAuthLocale(page, "zh-CN");

    await expectLegalMetadataFromLink(page, "服务条款", "服务条款");
    await page.goBack();
    await waitForSettled(page);
  });

  test("register persists zh locale through onboarding", async ({ page }) => {
    test.skip(!(await backendAvailable()), "Backend unavailable for register/onboarding smoke");

    await page.goto(appUrl("/register"));
    await waitForSettled(page);
    await switchAuthLocale(page, "zh-CN");
    await page.locator("#email-auth").fill(REGISTERED_EMAIL);
    await page.locator("#password-auth").fill(REGISTERED_PASSWORD);
    await page.locator("#password-confirm-auth").fill(REGISTERED_PASSWORD);

    await submitAuth(page, "register");
    await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
    await waitForSettled(page);

    await expect(page.getByTestId("onboarding-wizard")).toBeVisible();
    await expectDocumentLocale(page, "zh-CN");
    await expect(page.getByRole("heading", { name: /先接好来源/ })).toBeVisible();
  });

  test("preview respects stored locale", async ({ browser }) => {
    await expectPreviewRouteFromStoredLocale(browser, "/preview", "zh-CN", "现在先做什么");
    await expectPreviewRouteFromStoredLocale(browser, "/preview/agent", "zh-CN", "先看现在最该处理什么。");
    await expectPreviewRouteFromStoredLocale(browser, "/preview/agent", "en", "Follow the next best action.");
    await expectPreviewRouteFromStoredLocale(browser, "/preview/changes", "zh-CN", "按课程分组的收件区");
    await expectPreviewRouteFromStoredLocale(browser, "/preview/settings", "zh-CN", "账号与时区", "语言");
    await expectPreviewRouteFromStoredLocale(browser, "/preview/settings", "en", "Account and timezone", "Language");
  });

  test("login writes en locale back to session", async ({ page }) => {
    test.skip(!(await backendAvailable()), "Backend unavailable for login/session smoke");

    await page.goto(appUrl("/login"));
    await waitForSettled(page);
    await switchAuthLocale(page, "zh-CN");
    await page.locator("#email-auth").fill(REGISTERED_EMAIL);
    await page.locator("#password-auth").fill(REGISTERED_PASSWORD);

    await switchAuthLocale(page, "zh-CN");
    await expectAuthValues(page, { email: REGISTERED_EMAIL, password: REGISTERED_PASSWORD });

    await switchAuthLocale(page, "en");
    await expect(page.getByTestId("auth-locale-switch")).toContainText("Language");
    await expectAuthValues(page, { email: REGISTERED_EMAIL, password: REGISTERED_PASSWORD });

    await expectLegalMetadataFromLink(page, "Privacy policy", "Privacy Policy");
    await page.goBack();
    await waitForSettled(page);
    await switchAuthLocale(page, "en");
    await page.locator("#email-auth").fill(REGISTERED_EMAIL);
    await page.locator("#password-auth").fill(REGISTERED_PASSWORD);

    await expectLegalMetadataFromLink(page, "Terms of service", "Terms of Service");
    await page.goBack();
    await waitForSettled(page);
    await switchAuthLocale(page, "en");
    await page.locator("#email-auth").fill(REGISTERED_EMAIL);
    await page.locator("#password-auth").fill(REGISTERED_PASSWORD);

    await submitAuth(page, "login");
    await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
    await waitForSettled(page);

    await expect(page.getByTestId("onboarding-wizard")).toBeVisible();
    await expectDocumentLocale(page, "en");
    await expect(page.getByRole("heading", { name: /Connect your Canvas ICS link/ })).toBeVisible();
  });
});
