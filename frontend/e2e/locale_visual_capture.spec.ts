import { expect, test, type Browser, type Page, type TestInfo } from "@playwright/test";

const LOCALE_STORAGE_KEY = "calendardiff.locale";
const LOCALE_COOKIE_KEY = "calendardiff_locale";
const BASE_URL = process.env.REAL_FLOW_FRONTEND_BASE || "http://127.0.0.1:3000";
const BACKEND_HEALTH_URL = process.env.REAL_FLOW_BACKEND_HEALTH || "http://127.0.0.1:8200/health";
const VIEWPORTS = [
  { width: 390, height: 844, label: "390x844" },
  { width: 834, height: 1194, label: "834x1194" },
  { width: 1180, height: 820, label: "1180x820" },
  { width: 1440, height: 900, label: "1440x900" },
] as const;
const LOCALES = ["en", "zh-CN"] as const;

const PREVIEW_ROUTES = [
  { route: "/preview", markers: { en: "What to do next", "zh-CN": "现在先做什么" } },
  { route: "/preview/agent", markers: { en: "Turn a request into confirmable steps.", "zh-CN": "先把想做的事拆成可确认的步骤。" } },
  { route: "/preview/sources", markers: { en: "Connected sources", "zh-CN": "已接入的来源" } },
  { route: "/preview/sources/1", markers: { en: "Source detail", "zh-CN": "来源详情" } },
  { route: "/preview/changes", markers: { en: "Course-grouped inbox", "zh-CN": "按课程分组的收件区" } },
  { route: "/preview/families", markers: { en: "Keep labels aligned.", "zh-CN": "整理原始标签和标准归类。" } },
  { route: "/preview/manual", markers: { en: "Manual events", "zh-CN": "兜底事件" } },
  { route: "/preview/settings", markers: { en: "Account and timezone", "zh-CN": "账号与时区" } },
] as const;

const PUBLIC_ROUTES = [
  { route: "/login", markers: { en: "Sign in", "zh-CN": "登录" }, viaToggle: true },
  { route: "/register", markers: { en: "Create account", "zh-CN": "创建账号" }, viaToggle: true },
  {
    route: "/privacy",
    markers: { en: "Privacy Policy", "zh-CN": "隐私政策" },
    viaToggle: true,
    authLinkLabels: { en: "Privacy policy", "zh-CN": "隐私政策" },
  },
  {
    route: "/terms",
    markers: { en: "Terms of Service", "zh-CN": "服务条款" },
    viaToggle: true,
    authLinkLabels: { en: "Terms of service", "zh-CN": "服务条款" },
  },
] as const;

test.use({ trace: "off", screenshot: "off" });
test.setTimeout(240_000);

function sanitizeRoute(route: string) {
  return route.replace(/^\/+/, "").replace(/[\/:?=&]+/g, "-") || "root";
}

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

async function captureFullPage(page: Page, testInfo: TestInfo, route: string, locale: "en" | "zh-CN", viewportLabel: string) {
  const fileName = `${sanitizeRoute(route)}__${locale}__${viewportLabel}.png`;
  const screenshotPath = testInfo.outputPath(fileName);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  await testInfo.attach(fileName, { path: screenshotPath, contentType: "image/png" });
}

async function openPreviewRoute(
  browser: Browser,
  testInfo: TestInfo,
  route: string,
  locale: "en" | "zh-CN",
  marker: string,
  viewport: { width: number; height: number; label: string },
) {
  const context = await browser.newContext({
    baseURL: BASE_URL,
    viewport: { width: viewport.width, height: viewport.height },
  });
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
    await captureFullPage(page, testInfo, route, locale, viewport.label);
  } finally {
    await context.close();
  }
}

async function openPublicRoute(
  browser: Browser,
  testInfo: TestInfo,
  route: string,
  locale: "en" | "zh-CN",
  marker: string,
  viaToggle: boolean,
  authLinkLabel: string | null,
  viewport: { width: number; height: number; label: string },
) {
  const context = await browser.newContext({
    baseURL: BASE_URL,
    viewport: { width: viewport.width, height: viewport.height },
  });
  await context.addInitScript(
    ([storageKey]) => {
      window.localStorage.setItem(storageKey, "en");
    },
    [LOCALE_STORAGE_KEY] as const,
  );

  try {
    const page = await context.newPage();
    await page.goto(appUrl(authLinkLabel ? "/login" : route));
    await waitForSettled(page);
    if (viaToggle) {
      await switchAuthLocale(page, locale);
    }
    if (authLinkLabel) {
      await Promise.all([
        page.waitForURL(new RegExp(route.replace("/", "\\/")), { timeout: 30_000 }),
        page.getByRole("link", { name: authLinkLabel }).click(),
      ]);
      await waitForSettled(page);
    }
    const markerLocator = authLinkLabel
      ? page.getByTestId("legal-page").getByText(marker, { exact: false }).first()
      : page.getByText(marker, { exact: false }).first();
    await expect(markerLocator).toBeVisible();
    await captureFullPage(page, testInfo, route, locale, viewport.label);
  } finally {
    await context.close();
  }
}

async function openOnboardingForLocale(
  browser: Browser,
  testInfo: TestInfo,
  locale: "en" | "zh-CN",
  marker: string,
) {
  const email = `locale-capture-${locale}-${Date.now()}@example.com`;
  const password = "LocaleCapturePass!234";

  for (const [index, viewport] of VIEWPORTS.entries()) {
    const context = await browser.newContext({
      baseURL: BASE_URL,
      viewport: { width: viewport.width, height: viewport.height },
    });
    await context.addInitScript(
      ([storageKey]) => {
        window.localStorage.setItem(storageKey, "en");
      },
      [LOCALE_STORAGE_KEY] as const,
    );

    try {
      const page = await context.newPage();
      await page.goto(appUrl(index === 0 ? "/register" : "/login"));
      await waitForSettled(page);
      await switchAuthLocale(page, locale);
      await page.locator("#email-auth").fill(email);
      await page.locator("#password-auth").fill(password);
      if (index === 0) {
        await page.locator("#password-confirm-auth").fill(password);
        await page.locator("form").getByRole("button", { name: /^Create account$|^创建账号$/ }).click();
      } else {
        await page.locator("form").getByRole("button", { name: /^Sign in$|^登录$/ }).click();
      }
      await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
      await waitForSettled(page);
      await expect(page.getByTestId("onboarding-wizard")).toBeVisible();
      await expectDocumentLocale(page, locale);
      await expect(page.getByText(marker, { exact: false }).first()).toBeVisible();
      await captureFullPage(page, testInfo, "/onboarding", locale, viewport.label);
    } finally {
      await context.close();
    }
  }
}

test.describe("locale visual capture", () => {
  test.describe.configure({ mode: "serial" });

  for (const routeConfig of PREVIEW_ROUTES) {
    for (const locale of LOCALES) {
      test(`preview capture ${routeConfig.route} [${locale}]`, async ({ browser }, testInfo) => {
        for (const viewport of VIEWPORTS) {
          await openPreviewRoute(browser, testInfo, routeConfig.route, locale, routeConfig.markers[locale], viewport);
        }
      });
    }
  }

  for (const routeConfig of PUBLIC_ROUTES) {
    for (const locale of LOCALES) {
      test(`public capture ${routeConfig.route} [${locale}]`, async ({ browser }, testInfo) => {
        for (const viewport of VIEWPORTS) {
          await openPublicRoute(
            browser,
            testInfo,
            routeConfig.route,
            locale,
            routeConfig.markers[locale],
            routeConfig.viaToggle,
            "authLinkLabels" in routeConfig ? routeConfig.authLinkLabels[locale] : null,
            viewport,
          );
        }
      });
    }
  }

  for (const locale of LOCALES) {
    test(`public capture /onboarding [${locale}]`, async ({ browser }, testInfo) => {
      test.skip(!(await backendAvailable()), "Backend unavailable for onboarding capture");
      await openOnboardingForLocale(
        browser,
        testInfo,
        locale,
        locale === "en"
          ? "Connect your Canvas ICS link"
          : "连接你的 Canvas ICS 链接",
      );
    });
  }
});
