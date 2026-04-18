/**
 * Dashboard Tab Audit Script
 * Visits every tab and sub-tab, captures screenshots, detects blank/empty state.
 * Run: node audit.mjs
 */
import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'fs';
import path from 'path';

const BASE_URL = 'https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';
const OUT_DIR = '/tmp/tab-audit/screenshots';
mkdirSync(OUT_DIR, { recursive: true });

// ── Structure mirrors the new 10-tab consolidation ───────────────────────────
const TABS = [
  { topTab: 'Dashboard',  topLabel: 'Dashboard',  subTabs: [] },
  { topTab: 'Alerts',     topLabel: 'Alerts',     subTabs: [] },
  {
    topTab: 'Resources', topLabel: 'Resources',
    subTabs: ['All Resources', 'Virtual Machines', 'Scale Sets', 'Kubernetes', 'Disks', 'AZ Coverage'],
  },
  {
    topTab: 'Network', topLabel: 'Network',
    subTabs: ['Topology', 'VNet Peerings', 'Load Balancers', 'Private Endpoints'],
  },
  {
    topTab: 'Security', topLabel: 'Security',
    subTabs: ['Security Score', 'Compliance', 'Identity Risk', 'Certificates', 'Backup', 'Storage Security'],
  },
  {
    topTab: 'Cost', topLabel: 'Cost',
    subTabs: ['Cost & Advisor', 'Budgets', 'Quota Usage', 'Capacity', 'Quota Limits'],
  },
  {
    topTab: 'Change', topLabel: 'Change',
    subTabs: ['Patch Management', 'Deployments', 'IaC Drift', 'Maintenance'],
  },
  {
    topTab: 'Operations', topLabel: 'Operations',
    subTabs: ['Runbooks', 'Simulations', 'Observability', 'SLA', 'Quality'],
  },
  {
    topTab: 'Audit', topLabel: 'Audit',
    subTabs: ['Audit Log', 'Agent Traces'],
  },
  {
    topTab: 'Admin', topLabel: 'Admin',
    subTabs: ['Subscriptions', 'Settings', 'Tenant & Admin'],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function slug(str) {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

async function waitForContent(page) {
  // Wait for network to settle, up to 8s
  try {
    await page.waitForLoadState('networkidle', { timeout: 8000 });
  } catch { /* non-fatal */ }
  // Extra 500ms for React renders
  await page.waitForTimeout(500);
}

/**
 * Detect blank / empty / error states in the current viewport.
 * Returns array of issue strings found.
 */
async function detectIssues(page, context) {
  const issues = [];

  const bodyText = await page.evaluate(() => document.body.innerText);
  const lowerText = bodyText.toLowerCase();

  // ── Explicit empty-state indicators ──────────────────────────────────────
  const emptyPhrases = [
    'no data', 'no results', 'no findings', 'no records', 'no items',
    'no alerts', 'no incidents', 'no events', 'no runbooks', 'nothing found',
    'run a scan', 'no scan results', '0 items', '0 findings', '0 results',
    'coming soon', 'not configured', 'not available', 'endpoint env var not configured',
    'failed to load', 'error loading', 'something went wrong', 'unable to fetch',
    'could not load', '500', '502', '503',
  ];
  for (const phrase of emptyPhrases) {
    if (lowerText.includes(phrase)) {
      issues.push(`Empty/error state: "${phrase}" detected in page text`);
      break; // one per category is enough
    }
  }

  // ── Check for visible zeros in stat cards / KPI tiles ────────────────────
  const zeroPattern = /^0$|^0\.0+$|\b0 of \d+\b/;
  const statEls = await page.$$eval(
    '[class*="stat"], [class*="kpi"], [class*="metric"], [class*="card"] h2, [class*="card"] h3',
    els => els.map(el => el.innerText.trim())
  );
  const zeroStats = statEls.filter(t => zeroPattern.test(t));
  if (zeroStats.length > 0) {
    issues.push(`Stat cards showing zero: ${zeroStats.slice(0, 5).join(', ')}`);
  }

  // ── Check for blank/white main content area (very few visible chars) ──────
  const mainText = await page.evaluate(() => {
    const main = document.querySelector('[role="tabpanel"]:not([hidden])')
               || document.querySelector('main')
               || document.body;
    return (main?.innerText || '').trim();
  });
  if (mainText.length < 30) {
    issues.push(`Possibly blank panel — very little text visible (${mainText.length} chars)`);
  }

  // ── Loading spinners still spinning ───────────────────────────────────────
  const spinnerCount = await page.evaluate(() => {
    return document.querySelectorAll('[class*="spinner"], [class*="loading"], [class*="skeleton"]').length;
  });
  if (spinnerCount > 0) {
    issues.push(`${spinnerCount} loading spinner(s) still visible after wait`);
  }

  // ── Console errors ────────────────────────────────────────────────────────
  // (collected via listener below, passed in via context)

  return issues;
}

// ── Main ─────────────────────────────────────────────────────────────────────

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

const consoleErrors = [];
page.on('console', msg => {
  if (msg.type() === 'error') consoleErrors.push(msg.text());
});
page.on('pageerror', err => consoleErrors.push(`PAGE ERROR: ${err.message}`));

// Results store: { tab, subTab, issues[], screenshotPath, consoleErrors[] }
const results = [];

console.log(`\nNavigating to ${BASE_URL} …`);
await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
await waitForContent(page);

// Dismiss any login modal if present (app has auth disabled in prod)
const modalClose = page.locator('button:has-text("Sign in"), button:has-text("Login"), [aria-label="Close"]').first();
if (await modalClose.isVisible({ timeout: 2000 }).catch(() => false)) {
  await modalClose.click();
  await page.waitForTimeout(500);
}

for (const { topTab, subTabs } of TABS) {
  consoleErrors.length = 0; // reset per top-tab

  // ── Click top-level tab ──────────────────────────────────────────────────
  console.log(`\n▶ Tab: ${topTab}`);
  const topTabBtn = page.getByRole('tab', { name: new RegExp(`^${topTab}$`, 'i') }).first();

  try {
    await topTabBtn.waitFor({ state: 'visible', timeout: 5000 });
    await topTabBtn.click();
    await waitForContent(page);
  } catch (e) {
    console.log(`  ⚠ Could not click top tab "${topTab}": ${e.message}`);
    results.push({
      tab: topTab, subTab: null,
      issues: [`Could not find/click top-level tab: ${e.message}`],
      screenshotPath: null,
      consoleErrors: [],
    });
    continue;
  }

  // Screenshot top-level tab (before sub-tab navigation)
  const topSlug = slug(topTab);
  const topScreenshot = `${OUT_DIR}/${topSlug}.png`;
  await page.screenshot({ path: topScreenshot, fullPage: false });

  if (subTabs.length === 0) {
    // No sub-tabs — assess the page directly
    const issues = await detectIssues(page, ctx);
    const errs = [...consoleErrors];
    results.push({ tab: topTab, subTab: null, issues, screenshotPath: topScreenshot, consoleErrors: errs });
    console.log(`  Issues: ${issues.length ? issues.join(' | ') : '✓ none'}`);
    continue;
  }

  // ── Iterate sub-tabs ─────────────────────────────────────────────────────
  for (const subTab of subTabs) {
    consoleErrors.length = 0;
    console.log(`  ↳ Sub-tab: ${subTab}`);

    const subBtn = page.getByRole('button', { name: new RegExp(`^${subTab}$`, 'i') }).first();

    try {
      await subBtn.waitFor({ state: 'visible', timeout: 5000 });
      await subBtn.click();
      await waitForContent(page);
    } catch (e) {
      console.log(`    ⚠ Could not click sub-tab "${subTab}": ${e.message}`);
      results.push({
        tab: topTab, subTab,
        issues: [`Could not find/click sub-tab: ${e.message}`],
        screenshotPath: null,
        consoleErrors: [],
      });
      continue;
    }

    const subSlug = `${topSlug}--${slug(subTab)}`;
    const subScreenshot = `${OUT_DIR}/${subSlug}.png`;
    await page.screenshot({ path: subScreenshot, fullPage: false });

    const issues = await detectIssues(page, ctx);
    const errs = [...consoleErrors];
    results.push({ tab: topTab, subTab, issues, screenshotPath: subScreenshot, consoleErrors: errs });
    console.log(`    Issues: ${issues.length ? issues.join(' | ') : '✓ none'}`);
  }
}

await browser.close();

// ── Write tab-issues.md ───────────────────────────────────────────────────────

const now = new Date().toISOString().replace('T', ' ').slice(0, 19);
let md = `# Dashboard Tab Audit\n\n**Audited:** ${now} UTC  \n**URL:** ${BASE_URL}  \n\n`;

const withIssues = results.filter(r => r.issues.length > 0 || r.consoleErrors.length > 0);
const clean = results.filter(r => r.issues.length === 0 && r.consoleErrors.length === 0);

md += `## Summary\n\n`;
md += `- **Total views tested:** ${results.length}\n`;
md += `- **Views with issues:** ${withIssues.length}\n`;
md += `- **Clean views:** ${clean.length}\n\n`;

if (withIssues.length > 0) {
  md += `## Issues Found\n\n`;
  for (const r of withIssues) {
    const label = r.subTab ? `${r.tab} → ${r.subTab}` : r.tab;
    md += `### ${label}\n`;
    if (r.screenshotPath) md += `**Screenshot:** \`${r.screenshotPath}\`  \n`;
    if (r.issues.length) {
      md += `**UI Issues:**\n`;
      for (const i of r.issues) md += `- ${i}\n`;
    }
    if (r.consoleErrors.length) {
      md += `**Console Errors:**\n`;
      for (const e of r.consoleErrors.slice(0, 5)) md += `- \`${e.slice(0, 200)}\`\n`;
    }
    md += `\n`;
  }
}

if (clean.length > 0) {
  md += `## Clean Views (no issues detected)\n\n`;
  for (const r of clean) {
    const label = r.subTab ? `${r.tab} → ${r.subTab}` : r.tab;
    md += `- ✅ ${label}\n`;
  }
  md += `\n`;
}

const mdPath = '/tmp/tab-audit/tab-issues-raw.md';
writeFileSync(mdPath, md, 'utf8');
console.log(`\n✅ Audit complete. Results: ${mdPath}`);
console.log(`Screenshots: ${OUT_DIR}/`);
