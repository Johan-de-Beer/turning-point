import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'docs', 'screenshots');
const baseURL = process.env.TP_BASE_URL ?? 'http://127.0.0.1:5173';
const publicRun = new URL(baseURL).protocol === 'https:';
const connectIP = process.env.TP_CONNECT_IP;
if (connectIP && !/^\d{1,3}(\.\d{1,3}){3}$/.test(connectIP)) throw new Error('TP_CONNECT_IP must be an IPv4 address');
const browserArgs = ['--enable-unsafe-swiftshader', ...(connectIP ? [`--host-resolver-rules=MAP ${new URL(baseURL).hostname} ${connectIP}`] : [])];
const resultName = publicRun ? 'browser-qa-public' : 'browser-qa';
const quick = process.argv.includes('--quick');
await fs.mkdir(output, { recursive: true });
await fs.mkdir(path.join(root, '.runtime'), { recursive: true });
let browser;
try { browser = await chromium.launch({ channel: 'msedge', headless: true, args: browserArgs }); }
catch { browser = await chromium.launch({ headless: true, args: browserArgs }); }
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const pageErrors = [];
const responseErrors = [];
const checks = [];
const screenshots = [];
const patterns = new Set();
let latestState = null;
let responseCount = 0;
let match;
const pendingResponses = new Set();

function cutoffSafe(state) {
  assert(state.snapshot.as_of_ms <= state.playhead_ms, 'Snapshot ahead of server cutoff');
  for (const envelope of state.events) {
    assert(envelope.available_at_ms <= state.playhead_ms, 'Undelivered future event');
    if (envelope.payload) assert(envelope.payload.event_time_ms <= state.playhead_ms, 'Future event time');
  }
  for (const insight of state.insights) {
    assert(insight.observed_window.end_ms <= state.playhead_ms, 'Future insight');
    if (['ready', 'corrected'].includes(insight.status)) patterns.add(insight.pattern);
  }
  if (state.status !== 'ended') assert(state.recaps.full_time.status === 'locked', 'Full-time recap leaked early');
  if (state.overlay) {
    assert.equal(state.overlay.generation, state.generation);
    assert.equal(state.overlay.data_epoch, state.data_epoch);
    assert(state.overlay.valid_from_ms <= state.playhead_ms && state.playhead_ms < state.overlay.valid_until_ms, 'Expired overlay returned');
  }
  const prohibited = ['"seed":', '"phase_plan":', '"assertion_manifest":', '"final_score":'];
  const serialized = JSON.stringify(state);
  assert(!prohibited.some((field) => serialized.includes(field)), 'Private fixture metadata exposed');
}

page.on('pageerror', (error) => pageErrors.push(error.message));
page.on('response', (response) => {
  if (!response.url().includes('/api/')) return;
  const promise = (async () => {
    try {
      const data = await response.json();
      responseCount++;
      if (data.matches) match = data.matches[0];
      if (data.session_id && data.snapshot && data.events && Array.isArray(data.insights)) {
        cutoffSafe(data);
        latestState = data;
      }
      if (data.session_id && data.snapshot && data.insight) {
        assert(data.snapshot.as_of_ms <= data.playhead_ms, 'Evidence snapshot ahead of cutoff');
        assert(data.insight.observed_window.end_ms <= data.playhead_ms, 'Future evidence insight');
        for (const envelope of data.events) assert(envelope.available_at_ms <= data.playhead_ms, 'Future evidence record');
      }
      if (response.status() >= 400) responseErrors.push(`${response.status()} ${new URL(response.url()).pathname}: ${data.code ?? 'unknown'}`);
    } catch (error) { responseErrors.push(error.message); }
  })();
  pendingResponses.add(promise);
  promise.finally(() => pendingResponses.delete(promise));
});

async function shot(name) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, name), fullPage: true, animations: 'disabled' });
  screenshots.push(name);
}

async function noOverflow() {
  const dimensions = await page.evaluate(() => ({ width: innerWidth, body: document.documentElement.scrollWidth }));
  assert(dimensions.body <= dimensions.width + 1, `Page overflows horizontally: ${dimensions.body}/${dimensions.width}`);
}

async function waitState(predicate, description, timeout = 60_000) {
  await expect.poll(() => !!latestState && predicate(latestState), { timeout, message: description }).toBeTruthy();
}

function composedPixelDifference(first, second) {
  const output = execFileSync(process.env.TP_IMAGE_PYTHON ?? 'python',
    [path.join(root, 'scripts', 'compare_rendered_frames.py'), first, second], { encoding: 'utf8' });
  return JSON.parse(output);
}

try {
  console.log('Browser QA: loading start screen');
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await expect(page.getByRole('button', { name: 'Start replay', exact: true })).toBeVisible();
  await expect(page.getByTestId('pitch-scene')).toHaveAttribute('data-stadium-loaded', 'true', { timeout: 20_000 });
  await noOverflow();
  await shot('desktop-1440-start.png');
  // A paused new insight can be inspected without violating its expiry interval.
  await page.getByRole('checkbox', { name: /Pause when a new insight arrives/ }).check();
  await page.getByRole('button', { name: 'Start replay', exact: true }).click();
  await expect(page.getByTestId('pitch-scene')).toHaveAttribute('data-stadium-loaded', 'true', { timeout: 20_000 });
  await waitState((state) => state.status === 'playing' && state.events.length > 2, 'Live observed graphics', 10_000);
  const liveCanvas = page.getByTestId('pitch-scene').locator('canvas');
  const liveFrameA = await liveCanvas.screenshot();
  await page.waitForTimeout(250);
  const liveFrameB = await liveCanvas.screenshot();
  await fs.writeFile(path.join(root, '.runtime', 'pitch-live-a.png'), liveFrameA);
  await fs.writeFile(path.join(root, '.runtime', 'pitch-live-b.png'), liveFrameB);
  const livePixels = composedPixelDifference(path.join(root, '.runtime', 'pitch-live-a.png'), path.join(root, '.runtime', 'pitch-live-b.png'));
  assert(livePixels.max_channel_delta > 2 || livePixels.changed_percent > .05, 'Playing observed graphics must visibly change');
  await waitState((state) => state.insights.some((insight) => insight.status === 'ready'), 'First evidence-backed insight', 30_000);
  await waitState((state) => state.status === 'paused', 'Pause on insight');
  await expect(page.getByRole('button', { name: 'Why this insight?', exact: true })).toBeVisible();
  const insightFontSize = await page.locator('.insight-explanation').evaluate((element) => getComputedStyle(element).fontSize);
  assert.equal(insightFontSize, '16px', 'Core explanation body text must be 16px');
  await noOverflow();
  assert.equal(latestState.preferences.mode, 'casual');
  assert(latestState.overlay, 'Pause-on-insight should preserve eligible overlay');
  await shot('desktop-1440-match.png');
  checks.push('Start -> 60x server replay -> reviewed insight -> pause-on-insight');
  const pitch = page.getByTestId('pitch-scene');
  const canvas = pitch.locator('canvas');
  await pitch.getByRole('button', { name: 'Motion on', exact: true }).click();
  await expect(pitch.getByRole('button', { name: 'Motion off', exact: true })).toHaveAttribute('aria-pressed', 'false');
  // Let drag/landing camera damping settle before comparing event animation.
  await page.waitForTimeout(2000);
  const pausedFrameA = await canvas.screenshot();
  await page.waitForTimeout(250);
  const pausedFrameB = await canvas.screenshot();
  await fs.writeFile(path.join(root, '.runtime', 'pitch-paused-a.png'), pausedFrameA);
  await fs.writeFile(path.join(root, '.runtime', 'pitch-paused-b.png'), pausedFrameB);
  const pausedFramebuffer = composedPixelDifference(path.join(root, '.runtime', 'pitch-paused-a.png'), path.join(root, '.runtime', 'pitch-paused-b.png'));
  assert(pausedFramebuffer.max_channel_delta <= 2 && pausedFramebuffer.changed_percent <= .05,
    `Paused motion-off stadium has visible motion: ${JSON.stringify(pausedFramebuffer)}`);
  await fs.writeFile(path.join(root, '.runtime', 'pitch-paused-measurement.json'), JSON.stringify({ live: livePixels, paused: pausedFramebuffer, method: 'Browser-composed PNG pixels; tolerate <=0.05% changed pixels and <=2/255 channel delta when paused' }, null, 2));
  await pitch.getByRole('button', { name: 'Top view', exact: true }).click();
  await expect(pitch.getByRole('button', { name: 'Broadcast', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const topFrame = await canvas.screenshot();
  assert(!topFrame.equals(pausedFrameB), 'Top view must change camera');
  await pitch.getByRole('button', { name: 'Broadcast', exact: true }).click();
  const broadcastFrame = await canvas.screenshot();
  assert(!broadcastFrame.equals(topFrame), 'Broadcast view must restore perspective');
  const canvasBox = await canvas.boundingBox();
  await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + canvasBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(canvasBox.x + canvasBox.width / 2 + 90, canvasBox.y + canvasBox.height / 2 + 25, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const draggedFrame = await canvas.screenshot();
  assert(!draggedFrame.equals(broadcastFrame), 'Dragging must orbit the stadium');
  await pitch.getByRole('button', { name: 'Reset pitch camera', exact: true }).click();
  await page.waitForTimeout(300);
  const resetFrame = await canvas.screenshot();
  assert(!resetFrame.equals(draggedFrame), 'Camera reset must restore viewpoint');
  await pitch.getByRole('button', { name: 'Expand pitch', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.getAttribute('data-testid'))).toBe('pitch-scene');
  await pitch.getByRole('button', { name: 'Close expanded pitch', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBeTruthy();
  await pitch.getByRole('button', { name: 'Expand pitch', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.getAttribute('data-testid'))).toBe('pitch-scene');
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBeTruthy();
  await pitch.getByRole('button', { name: 'Motion off', exact: true }).click();
  checks.push('Blender GLB loaded; live canvas changes; motion off and pause stationary; top/broadcast view, drag orbit, reset, native fullscreen enter/button exit/Escape exit');

  console.log('Browser QA: evidence, overlay, and personalization');
  const evidenceButton = page.getByRole('button', { name: 'Why this insight?', exact: true });
  await evidenceButton.click();
  const evidenceDialog = page.getByRole('dialog', { name: 'The evidence behind the insight.' });
  await expect(evidenceDialog).toBeVisible();
  await expect(evidenceDialog.getByText('Measured facts', { exact: true })).toBeVisible();
  await expect(evidenceDialog.getByRole('table')).toHaveCount(2);
  await shot('desktop-1440-evidence.png');
  await page.keyboard.press('Escape');
  await expect(evidenceDialog).not.toBeVisible();
  await expect(evidenceButton).toBeFocused();
  await evidenceButton.click();
  await evidenceDialog.getByRole('button', { name: /^Show evt_/ }).first().click();
  await expect(page.getByRole('button', { name: 'Clear highlighted event' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear highlighted event' }).click();
  await page.getByRole('button', { name: 'Overlay JSON' }).click();
  const overlayDialog = page.getByRole('dialog', { name: 'A story ready to render.' });
  await expect(overlayDialog).toBeVisible();
  const overlay = JSON.parse(await overlayDialog.locator('pre').innerText());
  assert.equal(overlay.session_id, latestState.session_id);
  assert(overlay.fact_ids.length > 0);
  assert(overlay.valid_from_ms <= latestState.playhead_ms && latestState.playhead_ms < overlay.valid_until_ms);
  await shot('desktop-1440-overlay.png');
  await page.keyboard.press('Escape');
  const factualBefore = JSON.stringify({ score: latestState.score, team_metrics: latestState.snapshot.team_metrics });
  await page.getByRole('button', { name: 'Analyst', exact: true }).click();
  await waitState((state) => state.preferences.mode === 'analyst', 'Analyst preference');
  assert.equal(JSON.stringify({ score: latestState.score, team_metrics: latestState.snapshot.team_metrics }), factualBefore);
  await expect(page.locator('.analyst-facts')).toBeVisible();
  await page.getByRole('button', { name: 'Open preferences', exact: true }).last().click();
  const preferences = page.getByRole('dialog', { name: 'Make the match yours.' });
  await expect(preferences).toBeVisible();
  await preferences.getByLabel('Favorite club', { exact: true }).selectOption(match.home.team_id);
  const player = match.roster.find((item) => item.team_id === match.home.team_id && item.position === 'GK');
  await preferences.getByLabel('Search players', { exact: true }).fill(player.display_name);
  await preferences.getByLabel('Favorite player', { exact: true }).selectOption(player.player_id);
  await preferences.getByRole('checkbox', { name: /Pause when a new insight arrives/ }).uncheck();
  await preferences.getByRole('button', { name: 'Save preferences' }).click();
  await expect(preferences).not.toBeVisible();
  await waitState((state) => state.preferences.favorite_player_id === player.player_id && !state.preferences.pause_on_insight, 'Favorite-player selection');
  assert.equal(JSON.stringify({ score: latestState.score, team_metrics: latestState.snapshot.team_metrics }), factualBefore);
  await expect(page.locator('#player-focus')).toContainText(player.display_name);
  await shot('desktop-1440-analyst-player.png');
  checks.push('Evidence facts/rules/event version table; selected marker; Escape focus restoration; eligible overlay JSON');
  checks.push('Casual/Analyst differ while score/team metrics remain equal; searchable favorite-player selection');

  for (const width of [768, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(await page.locator('.insight-explanation').evaluate((element) => getComputedStyle(element).fontSize), '16px', `Core explanation at ${width}px`);
    await noOverflow();
    await shot(`${width === 360 ? 'mobile' : 'tablet'}-${width}-match.png`);
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches));
  await expect(pitch.getByRole('button', { name: 'Motion off', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await shot('mobile-360-reduced-motion.png');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => { document.body.style.zoom = '2'; });
  await noOverflow();
  await shot('desktop-1440-200-percent.png');
  await page.evaluate(() => { document.body.style.zoom = ''; });
  checks.push('1440/768/360px layouts have no page horizontal overflow; reduced-motion preference; 200% zoom layout');

  const sessionBeforeReload = latestState.session_id;
  await page.reload({ waitUntil: 'networkidle' });
  await waitState((state) => state.session_id === sessionBeforeReload && state.status === 'paused', 'Reconnect same session');
  await expect(page.getByRole('button', { name: 'Play replay', exact: true })).toBeVisible();
  if (quick) {
    await Promise.all([...pendingResponses]);
    assert.deepEqual(pageErrors, []);
    assert.deepEqual(responseErrors, []);
    checks.push('Core insight explanation computes to 16px; same-session reconnect stays paused');
    const result = { status: 'passed', base_url: baseURL, checks, screenshots, paused_framebuffer: pausedFramebuffer, core_prose_font_size: insightFontSize, api_responses_checked: responseCount, page_errors: pageErrors, response_errors: responseErrors, scope: 'Quick browser regression after visual refinement; original complete replay result retained separately' };
    await fs.writeFile(path.join(root, '.runtime', `${resultName}-quick.json`), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
    await browser.close();
    process.exit(0);
  }
  await page.getByRole('button', { name: 'Play replay', exact: true }).click();
  console.log('Browser QA: waiting for the observed halftime marker');
  await waitState((state) => state.status === 'half_time', 'Halftime server boundary', 60_000);
  assert.equal(latestState.playhead_ms, 2_700_000);
  assert.equal(latestState.recaps.full_time.status, 'locked');
  assert.equal(latestState.recaps.half_time.status, 'ready');
  assert(!latestState.events.some((envelope) => envelope.payload?.period === 2));
  await page.getByRole('button', { name: 'Open half-time recap' }).click();
  const half = page.getByRole('dialog', { name: 'The half-time story.' });
  await expect(half).toBeVisible();
  await expect(half).toContainText('Observed through 45:00');
  await shot('desktop-1440-halftime.png');
  await page.keyboard.press('Escape');
  checks.push('Reconnect preserves paused session; halftime stops exactly; second-half events/full recap remain locked; evidence-linked halftime recap');

  await page.getByRole('button', { name: 'Continue second half', exact: true }).click();
  console.log('Browser QA: waiting for the observed fulltime marker');
  await waitState((state) => state.status === 'ended', 'Fulltime server boundary', 60_000);
  assert.equal(latestState.playhead_ms, 5_400_000);
  assert.equal(latestState.recaps.full_time.status, 'ready');
  assert.equal(latestState.overlay, null);
  await page.getByRole('button', { name: 'Open full-time recap' }).click();
  const full = page.getByRole('dialog', { name: 'The full-time story.' });
  await expect(full).toBeVisible();
  await expect(full).toContainText('Observed through 90:00');
  await shot('desktop-1440-fulltime.png');
  for (const pattern of ['sustained_pressure', 'sterile_possession', 'end_to_end']) assert(patterns.has(pattern), `Missing ${pattern} during working replay`);
  await Promise.all([...pendingResponses]);
  assert.deepEqual(pageErrors, [], 'Browser uncaught errors');
  assert.deepEqual(responseErrors, [], 'Network/cutoff failures');
  checks.push('Complete working replay confirms all three patterns; fulltime recap unlocks only after final marker; no eligible overlay after end');
  const result = { status: 'passed', browser: browser.browserType().name(), base_url: baseURL, connection_override: connectIP ?? null, checks, screenshots, paused_framebuffer: pausedFramebuffer, core_prose_font_size: insightFontSize, observed_patterns: [...patterns], api_responses_checked: responseCount, page_errors: pageErrors, response_errors: responseErrors, scope: `${publicRun ? 'HTTPS public-serving' : 'Local'} mock browser integration; automated responsive checks and screenshots; human visual/accessibility review remains separate` };
  await fs.writeFile(path.join(root, '.runtime', `${resultName}.json`), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  await shot('browser-qa-failure.png').catch(() => {});
  await fs.writeFile(path.join(root, '.runtime', `${resultName}-failure.json`), JSON.stringify({ status: 'failed', error: error.message, checks, screenshots, page_errors: pageErrors, response_errors: responseErrors, last_cutoff: latestState?.playhead_ms }, null, 2));
  throw error;
} finally { await browser.close(); }
