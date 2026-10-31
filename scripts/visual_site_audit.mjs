import { chromium } from "playwright";
import { mkdir, writeFile, appendFile } from "node:fs/promises";

const base = process.env.MATCH_SIGNAL_BASE_URL || "https://match-signal.pages.dev";
const routes = [
  "/", "/index.html", "/upcoming.html", "/qualified-best.html",
  "/odds-builder.html", "/football.html", "/tennis.html", "/basketball.html",
  "/darts.html", "/table-tennis.html",
  "/league.html?sport=football&league=England%20Amateur%20-%20U21%20Professional%20Development%20League",
  "/reports.html", "/live.html", "/expansion.html", "/expansion-update.html",
  "/virtual-lab/", "/virtual-lab", "/virtual-lab.html", "/research.html",
  "/analyst.html", "/match-tracker.html", "/match-tracker-v2.html", "/match-tracker-v3.html",
  "/performance.html", "/performance-tight.html", "/premium.html",
  "/api-access.html", "/api-terms.html", "/payment-success.html"
];
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 }
];
const results = [];
const failures = [];
await mkdir("visual-site-audit", { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  for (const route of routes) {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport, locale: "en-NG", reducedMotion: "reduce" });
      const pageErrors = [];
      const failedResponses = [];
      page.on("pageerror", error => pageErrors.push(String(error?.message || error)));
      page.on("response", response => {
        const responseUrl = new URL(response.url());
        const expectedProtectedApiGate = response.status() === 401 && responseUrl.pathname.startsWith("/api/analyst");
        if (response.status() >= 400 && responseUrl.origin === new URL(base).origin && !expectedProtectedApiGate) {
          failedResponses.push({ status: response.status(), url: response.url() });
        }
      });
      const url = new URL(route, base).toString();
      let navigationStatus = null;
      let navigationError = null;
      try {
        const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 25000 });
        navigationStatus = response?.status() ?? null;
        await page.waitForTimeout(1200);
        await page.evaluate(() => document.fonts?.ready);
      } catch (error) {
        navigationError = String(error?.message || error);
      }
      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const body = document.body;
        const visible = element => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" &&
            Number(style.opacity) > 0 && rect.width > 0 && rect.height > 0;
        };
        const brokenImages = Array.from(document.images)
          .filter(image => image.complete && image.naturalWidth === 0 && image.currentSrc)
          .map(image => ({ src: image.currentSrc, alt: image.alt || "" }));
        const overflowNodes = Array.from(body?.querySelectorAll("*") || [])
          .filter(element => {
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 &&
              (rect.right > innerWidth + 8 || rect.left < -8) &&
              !element.closest("[data-horizontal-scroll],.results-table-wrap,.results-table-scroll,.table-scroll,.overflow-x-auto");
          })
          .slice(0, 8)
          .map(element => ({
            tag: element.tagName.toLowerCase(),
            className: String(element.className?.baseVal || element.className || "").slice(0, 100),
            left: Math.round(element.getBoundingClientRect().left),
            right: Math.round(element.getBoundingClientRect().right)
          }));
        return {
          title: document.title || "",
          body_text_length: (body?.innerText || "").trim().length,
          body_height: body?.scrollHeight || 0,
          viewport_width: innerWidth,
          document_width: Math.max(root?.scrollWidth || 0, body?.scrollWidth || 0),
          horizontal_overflow: Math.max(root?.scrollWidth || 0, body?.scrollWidth || 0) > innerWidth + 8,
          overflow_nodes: overflowNodes,
          visible_images: Array.from(document.images).filter(visible).length,
          broken_images: brokenImages,
          stylesheet_count: document.styleSheets.length,
          visible_navigation: Array.from(document.querySelectorAll("nav,header,[role=navigation]")).filter(visible).length,
          main_regions: Array.from(document.querySelectorAll("main,[role=main]")).filter(visible).length
        };
      }).catch(error => ({ evaluation_error: String(error?.message || error) }));
      const screenshotName = (route.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "home") + "-" + viewport.name + ".png";
      let screenshotError = null;
      try {
        await page.screenshot({
          path: "visual-site-audit/" + screenshotName,
          // Very long data-heavy dashboards can exceed Chromium's full-page
          // screenshot texture limits. Keep the audit screenshot reliable by
          // capturing the viewport on pages taller than 18,000 CSS pixels.
          fullPage: Number(layout.body_height || 0) <= 18000,
          animations: "disabled",
          timeout: 15000
        });
      } catch (error) {
        screenshotError = String(error?.message || error);
      }
      const item = {
        route, viewport: viewport.name, url, navigation_status: navigationStatus,
        navigation_error: navigationError, page_errors: pageErrors,
        failed_same_origin_responses: failedResponses, layout, screenshot: screenshotName,
        screenshot_error: screenshotError
      };
      results.push(item);
      const problems = [];
      if (navigationError || (navigationStatus !== null && navigationStatus >= 400)) problems.push("NAVIGATION_FAILED");
      if (!layout.title || layout.body_text_length < 40) problems.push("PAGE_EMPTY_OR_MISSING_TITLE");
      if (layout.horizontal_overflow) problems.push("HORIZONTAL_OVERFLOW");
      if (layout.broken_images?.length) problems.push("BROKEN_IMAGES");
      if (layout.stylesheet_count < 1) problems.push("NO_STYLESHEETS");
      if (pageErrors.length) problems.push("BROWSER_RUNTIME_ERRORS");
      if (failedResponses.length) problems.push("SAME_ORIGIN_HTTP_ERRORS");
      if (screenshotError) problems.push("SCREENSHOT_FAILED");
      if (problems.length) failures.push({ route, viewport: viewport.name, problems, item });
      await page.close();
    }
  }
} finally {
  await browser.close();
}
const report = {
  audit: "Match Signal full-site responsive browser audit",
  base_url: base,
  completed_at: new Date().toISOString(),
  routes_checked: routes.length,
  viewports_checked: viewports.map(({ name, width, height }) => ({ name, width, height })),
  page_view_checks: results.length,
  failed_checks: failures.length,
  failures,
  results
};
await writeFile("visual-site-audit/report.json", JSON.stringify(report, null, 2) + "\n", "utf8");
if (process.env.GITHUB_STEP_SUMMARY) {
  const rows = results.map(item => {
    const status = failures.some(f => f.route === item.route && f.viewport === item.viewport) ? "FAIL" : "PASS";
    const overflow = item.layout?.horizontal_overflow ? "overflow" : "no overflow";
    const js = item.page_errors.length ? item.page_errors.length + " JS error(s)" : "no JS errors";
    return "| " + item.route + " | " + item.viewport + " | " + (item.navigation_status ?? "ERR") + " | " + status + " | " + overflow + " | " + js + " |";
  });
  const summary = [
    "## Match Signal full-site responsive browser audit", "",
    "- Routes: **" + routes.length + "** · desktop/mobile checks: **" + results.length + "**",
    "- Failed page/viewport checks: **" + failures.length + "**",
    "- Screenshots and the complete JSON report are attached as a workflow artifact.", "",
    "| Route | Viewport | HTTP | Result | Layout | Runtime |",
    "|---|---|---:|---|---|---|",
    ...rows
  ].join("\n");
  await appendFile(process.env.GITHUB_STEP_SUMMARY, summary + "\n", "utf8");
}
console.log(JSON.stringify({
  audit: report.audit,
  routes_checked: report.routes_checked,
  page_view_checks: report.page_view_checks,
  failed_checks: report.failed_checks,
  failures: failures.map(f => ({
    route: f.route, viewport: f.viewport, problems: f.problems,
    layout: f.item.layout, page_errors: f.item.page_errors,
    http_errors: f.item.failed_same_origin_responses
  }))
}, null, 2));
if (failures.length) process.exitCode = 1;
