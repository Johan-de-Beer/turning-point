/**
 * Real-browser assertions against delivered API envelopes and actual rendered
 * ball mesh coordinates. No fixture plan, mocked browser clock, or seek API.
 */
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const baseURL = process.env.TP_BASE_URL ?? 'http://127.0.0.1:5173';
const publicRun = new URL(baseURL).protocol === 'https:';
const outputName = publicRun ? 'pitch-functional-public' : 'pitch-functional-local';
await fs.mkdir(path.join(root, '.runtime'), { recursive: true });
let browser;
try { browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--enable-unsafe-swiftshader'] }); }
catch { browser = await chromium.launch({ headless: true, args: ['--enable-unsafe-swiftshader'] }); }
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const scene = page.getByTestId('pitch-scene');
let latest = null;
let metadata = null;
let registryKey = null;
let registry = new Map();
const observedVersions = new Map();
let responseCount = 0;
const errors = [];
const checks = [];
const samples = [];
const boundaryDrains = [];
const seenKinds = new Set();
const seenTeams = new Set();
const seenOutcomes = new Set();
const pending = new Set();

// This registry is independent of the React event cache. Only records actually
// received by the browser may justify a rendered event or animation route.
function ingest(state) {
  if (latest && latest.session_id === state.session_id && (state.generation < latest.generation ||
    (state.generation === latest.generation && (state.playhead_ms < latest.playhead_ms || state.data_epoch < latest.data_epoch || state.preferences_version < latest.preferences_version)))) return;
  const key = `${state.session_id}:${state.generation}`;
  if (registryKey !== key || state.resync_required) registry = new Map();
  registryKey = key;
  for (const envelope of state.events) {
    assert(envelope.available_at_ms <= state.playhead_ms, 'API record ahead of cutoff');
    if (envelope.payload) assert(envelope.payload.event_time_ms <= state.playhead_ms, 'API event ahead of cutoff');
    const current = registry.get(envelope.event_id);
    if (!current || envelope.revision >= current.revision) registry.set(envelope.event_id, envelope);
    observedVersions.set(`${key}:${envelope.event_id}@${envelope.revision}`, envelope);
  }
  latest = state;
}

page.on('pageerror', (error) => errors.push(error.message));
page.on('response', (response) => {
  if (!response.url().includes('/api/')) return;
  const promise = (async () => {
    try {
      const value = await response.json();
      responseCount++;
      if (response.status() >= 400) errors.push(`HTTP${response.status()} ${new URL(response.url()).pathname}: ${value.code ?? 'unknown'}`);
      if (value.matches) metadata = value.matches[0];
      if (value.session_id && value.snapshot && Array.isArray(value.events) && value.status) ingest(value);
    } catch (error) { errors.push(error.message); }
  })();
  pending.add(promise);
  promise.finally(() => pending.delete(promise));
});

const close = (a, b, message, epsilon = .025) => assert(Math.abs(a - b) <= epsilon, `${message}: ${a} vs ${b}`);
function orientedWorld(point, event) {
  const forward = (event.team_id === metadata.home.team_id) === (event.period === 1);
  const x = forward ? point.x : 100 - point.x;
  const y = forward ? point.y : 100 - point.y;
  return { x: (x / 100 - .5) * 105, z: (y / 100 - .5) * 68 };
}
function routeFor(event) {
  if (event.kind === 'PASS' || event.kind === 'CARRY') return { start: event.detail.start, end: event.detail.end };
  if (event.kind === 'SHOT') return { start: event.detail.position, end: event.detail.target ?? event.detail.position };
  if (event.kind === 'POSSESSION') return { start: event.detail.start, end: event.detail.start };
  if (event.kind === 'TACKLE') return { start: event.detail.position, end: event.detail.position };
  return null;
}

async function sampleMesh() {
  const data = await scene.evaluate((element) => {
    const actor = element.querySelector('.pitch-player-label:not(.recipient)');
    const recipient = element.querySelector('.pitch-player-label.recipient');
    return { ...element.dataset, actorLabel: actor?.textContent ?? '', recipientLabel: recipient?.textContent ?? '',
      actorLabelVisible: actor ? !actor.hidden : false, recipientLabelVisible: recipient ? !recipient.hidden : false };
  });
  const eventId = data.activeEventId;
  if (!eventId) return null;
  assert(latest && metadata, 'Mesh preceded API session');
  const envelope = data.playbackMode === 'inspection'
    ? observedVersions.get(`${registryKey}:${eventId}@${Number(data.activeEventRevision)}`)
    : registry.get(eventId);
  assert(envelope?.payload && envelope.operation !== 'delete', `Rendered event not in delivered records: ${eventId}`);
  const event = envelope.payload;
  assert.equal(data.activeEventKind, event.kind);
  assert.equal(data.activeEventTeam, event.team_id ?? '');
  assert.equal(Number(data.activeEventTime), event.event_time_ms);
  assert.equal(Number(data.activeEventRevision), envelope.revision);
  assert.equal(Number(data.activeEventPeriod), event.period);
  const renderedCutoff = Number(data.observedCutoffMs);
  assert(Number.isFinite(renderedCutoff) && renderedCutoff <= latest.playhead_ms, 'Rendering cutoff comes from delivered state');
  assert(event.event_time_ms <= renderedCutoff && envelope.available_at_ms <= renderedCutoff, 'Rendered future event');
  if (data.playbackMode === 'live') assert(event.period <= Number(data.observedPeriod), 'Rendered queue does not enter a future period');
  const route = routeFor(event);
  const progress = Number(data.animationProgress);
  assert(Number.isFinite(progress) && progress >= 0 && progress <= 1, 'Animation progress bounds');
  if (route && data.ballVisible === 'true') {
    const actorName = metadata.roster.find((player) => player.player_id === event.player_id)?.display_name;
    if (actorName) { assert.equal(data.actorLabel, actorName); assert(data.actorLabelVisible, 'Observed actor label visible'); }
    if (event.kind === 'PASS' && event.detail.completed) {
      const recipientName = metadata.roster.find((player) => player.player_id === event.detail.recipient_id)?.display_name;
      assert.equal(data.recipientLabel, recipientName);
      assert(data.recipientLabelVisible, 'Completed pass recipient label visible');
    }
    const from = orientedWorld(route.start, event), to = orientedWorld(route.end, event);
    close(Number(data.routeStartX), from.x, `${event.kind} recorded start X`);
    close(Number(data.routeStartZ), from.z, `${event.kind} recorded start Z`);
    close(Number(data.routeEndX), to.x, `${event.kind} recorded end X`);
    close(Number(data.routeEndZ), to.z, `${event.kind} recorded end Z`);
    // Elevation may arc, but X/Z must follow the recorded oriented route.
    close(Number(data.ballX), from.x + (to.x - from.x) * progress, 'Ball mesh X follows recorded route');
    close(Number(data.ballZ), from.z + (to.z - from.z) * progress, 'Ball mesh Z follows recorded route');
  }
  seenKinds.add(event.kind);
  if (event.team_id) seenTeams.add(event.team_id);
  if (event.kind === 'SHOT') seenOutcomes.add(event.detail.outcome);
  const sample = { event_id: eventId, revision: envelope.revision, kind: event.kind, team: event.team_id,
    period: event.period, event_time_ms: event.event_time_ms, observed_cutoff_ms: renderedCutoff,
    progress, ball_visible: data.ballVisible === 'true', ball_x: Number(data.ballX), ball_z: Number(data.ballZ),
    mode: data.playbackMode, replay_key: data.replayKey };
  samples.push(sample);
  return sample;
}

async function waitState(predicate, description, timeout = 60_000) {
  await expect.poll(() => !!latest && predicate(latest), { message: description, timeout }).toBeTruthy();
}
async function observeFor(milliseconds) {
  const until = Date.now() + milliseconds;
  while (Date.now() < until) {
    await sampleMesh();
    await page.waitForTimeout(75);
  }
}
async function drainBoundary(period) {
  const started = Date.now();
  const initialQueued = Number(await scene.getAttribute('data-queued-events'));
  for (;;) {
    await sampleMesh();
    const data = await scene.evaluate((element) => ({ ...element.dataset }));
    if (data.queuedEvents === '0' && data.activeEventKind === 'PERIOD_END' && data.ballVisible === 'false') break;
    assert(Date.now() - started < 30_000, `Delivered period ${period} queue failed to drain in 30 seconds`);
    await page.waitForTimeout(50);
  }
  boundaryDrains.push({ period, initial_queued_events: initialQueued, drain_ms: Date.now() - started });
}
async function captureFunctionalScreens() {
  const directory = path.join(root, 'docs', 'screenshots');
  await fs.mkdir(directory, { recursive: true });
  await scene.scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(directory, 'desktop-functional-event.png'), fullPage: true });
  await scene.screenshot({ path: path.join(directory, 'desktop-functional-pitch.png') });
  await page.setViewportSize({ width: 360, height: 1000 });
  await scene.scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  await scene.screenshot({ path: path.join(directory, 'mobile-functional-pitch.png') });
  await page.screenshot({ path: path.join(directory, 'mobile-functional-event.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await scene.scrollIntoViewIfNeeded();
}

try {
  console.log('Functional pitch QA: waiting for instrumented live event renderer');
  await page.goto(baseURL, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: 'Start replay', exact: true })).toBeVisible();
  // These checks instrument the WebGL meshes, so select the 3D stadium (2D is the default).
  await page.getByRole('button', { name: '3D stadium', exact: true }).click();
  await page.getByRole('checkbox', { name: /Pause when a new insight arrives/ }).uncheck();
  await page.getByRole('button', { name: 'Start replay', exact: true }).click();
  await waitState((state) => state.status === 'playing', 'Playback starts');
  await expect(scene).toHaveAttribute('data-stadium-loaded', 'true', { timeout: 20_000 });
  await scene.scrollIntoViewIfNeeded();
  await page.getByLabel('Replay speed', { exact: true }).selectOption('12');
  await waitState((state) => state.speed === 12, 'Readable twelve-speed playback');
  await observeFor(25_000);
  assert(seenKinds.has('PASS') && seenKinds.has('CARRY'), 'Observed both passing and carrying mesh routes');
  checks.push('Delivered event identity/type/team/time/revision and actual mesh X/Z follow recorded oriented pass/carry routes');

  await expect.poll(async () => {
    const data = await scene.evaluate((element) => ({ ...element.dataset }));
    return ['PASS', 'CARRY', 'SHOT'].includes(data.activeEventKind) && Number(data.animationProgress) > 0 && Number(data.animationProgress) < 1;
  }, { timeout: 10_000, intervals: [25] }).toBeTruthy();
  await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
  await waitState((state) => state.status === 'paused', 'Authoritative pause');
  await page.waitForTimeout(150);
  const pausedCutoff = latest.playhead_ms;
  const pausedA = await sampleMesh();
  await page.waitForTimeout(350);
  const pausedB = await sampleMesh();
  assert(pausedA && pausedB, 'Active observed ball during pause');
  assert.equal(latest.playhead_ms, pausedCutoff);
  assert.equal(pausedB.event_id, pausedA.event_id);
  close(pausedB.ball_x, pausedA.ball_x, 'Pause freezes actual ball X', .0001);
  close(pausedB.ball_z, pausedA.ball_z, 'Pause freezes actual ball Z', .0001);
  close(pausedB.progress, pausedA.progress, 'Pause freezes route progress', .0001);
  checks.push('Authoritative pause freezes cutoff, active event and actual ball mesh/progress');
  await captureFunctionalScreens();

  await page.getByLabel('Replay speed', { exact: true }).selectOption('60');
  await waitState((state) => state.speed === 60 && state.status === 'paused', 'Speed edit remains paused');
  const speedPaused = await sampleMesh();
  close(speedPaused.ball_x, pausedB.ball_x, 'Paused speed edit preserves ball X', .0001);
  close(speedPaused.ball_z, pausedB.ball_z, 'Paused speed edit preserves ball Z', .0001);
  const movements = [...registry.values()].filter((envelope) => {
    const event = envelope.payload;
    if (!event || !['PASS', 'CARRY', 'SHOT'].includes(event.kind) || envelope.event_id === pausedB.event_id) return false;
    const route = routeFor(event);
    return route && (route.start.x !== route.end.x || route.start.y !== route.end.y);
  }).sort((a, b) => b.payload.event_time_ms - a.payload.event_time_ms);
  let oldSpatial;
  for (const envelope of movements) {
    if (await page.locator(`[data-event-id="${envelope.event_id}"]`).count()) { oldSpatial = envelope; break; }
  }
  assert(oldSpatial, 'An observed movement record is available for explicit historical replay');
  {
    await page.locator(`[data-event-id="${oldSpatial.event_id}"]`).first().click();
    await scene.scrollIntoViewIfNeeded();
    await expect(scene).toHaveAttribute('data-playback-mode', 'inspection');
    const inspected = await sampleMesh();
    assert.equal(inspected.event_id, oldSpatial.event_id);
    assert.equal(inspected.revision, oldSpatial.revision);
    await scene.getByRole('button', { name: 'Replay this event', exact: true }).click();
    await expect.poll(async () => {
      const progress = Number(await scene.getAttribute('data-animation-progress'));
      return progress > 0 && progress < 1;
    }, { timeout: 3_000, intervals: [25] }).toBeTruthy();
    await observeFor(150);
    await scene.getByRole('button', { name: 'Pause event', exact: true }).click();
    await page.waitForTimeout(80);
    const previewA = await sampleMesh();
    await page.waitForTimeout(180);
    const previewB = await sampleMesh();
    assert.equal(previewB.event_id, oldSpatial.event_id);
    close(previewA.ball_x, previewB.ball_x, 'Historical preview pause freezes ball X', .0001);
    close(previewA.ball_z, previewB.ball_z, 'Historical preview pause freezes ball Z', .0001);
    assert.equal(latest.playhead_ms, pausedCutoff, 'Historical animation cannot advance server clock');
    await scene.getByRole('button', { name: 'Replay this event', exact: true }).click();
    await expect.poll(async () => Number(await scene.getAttribute('data-animation-progress')), { timeout: 3_000 }).toBe(1);
    await expect(scene.getByRole('button', { name: 'Replay this event', exact: true })).toBeVisible();
    const endpointA = await sampleMesh();
    await page.waitForTimeout(400);
    const endpointB = await sampleMesh();
    assert.equal(endpointB.event_id, oldSpatial.event_id);
    assert.equal(endpointA.progress, 1);
    assert.equal(endpointB.progress, 1);
    close(endpointA.ball_x, endpointB.ball_x, 'Historical replay remains at recorded endpoint without looping', .0001);
    close(endpointA.ball_z, endpointB.ball_z, 'Historical replay endpoint Z is stable', .0001);
    assert.equal(latest.playhead_ms, pausedCutoff, 'Completed historical replay leaves server cutoff unchanged');
    await page.getByRole('button', { name: 'Clear highlighted event', exact: true }).click();
    await expect(scene).toHaveAttribute('data-playback-mode', 'live');
    const restored = await sampleMesh();
    assert.equal(restored.event_id, speedPaused.event_id);
    close(restored.ball_x, speedPaused.ball_x, 'Inspection restores paused live ball X', .0001);
    close(restored.ball_z, speedPaused.ball_z, 'Inspection restores paused live ball Z', .0001);
    checks.push('Historical inspection/replay/pause reach recorded endpoint once without looping, preserve server clock and restore paused live event/mesh');
  }
  const sessionBeforeReload = latest.session_id;
  await Promise.all([...pending]);
  latest = null;
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitState((state) => state.session_id === sessionBeforeReload && state.status === 'paused', 'Same-session paused reload');
  await expect(scene).toHaveAttribute('data-stadium-loaded', 'true', { timeout: 20_000 });
  await scene.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  const reloadA = await sampleMesh();
  await page.waitForTimeout(350);
  const reloadB = await sampleMesh();
  assert(reloadA && reloadB);
  assert.equal(reloadA.event_id, reloadB.event_id);
  close(reloadA.ball_x, reloadB.ball_x, 'Reloaded paused ball X is frozen', .0001);
  close(reloadA.ball_z, reloadB.ball_z, 'Reloaded paused ball Z is frozen', .0001);
  checks.push('Reload reconnects same paused session and freezes reconstructed actual ball without replaying history');
  await page.getByRole('button', { name: 'Play replay', exact: true }).click();
  await waitState((state) => state.status === 'playing', 'Replay resumes at sixty-speed');
  checks.push('Speed changes preserve frozen route; resume uses same server session');

  console.log('Functional pitch QA: observing shot outcomes and first-half routes');
  const firstHalfDeadline = Date.now() + 65_000;
  while (latest.status !== 'half_time') {
    assert(Date.now() < firstHalfDeadline, 'First half failed to reach real server boundary');
    await sampleMesh();
    await page.waitForTimeout(75);
  }
  assert.equal(latest.playhead_ms, 2_700_000);
  await drainBoundary(1);
  checks.push('Half-time finishes delivered action queue and removes ball at the actual period-end marker');
  const periodOne = samples.filter((sample) => sample.period === 1);
  assert(periodOne.some((sample) => sample.team === metadata.home.team_id) && periodOne.some((sample) => sample.team === metadata.away.team_id), 'Both team orientations observed in first half');
  await page.getByRole('button', { name: 'Continue second half', exact: true }).click();
  await waitState((state) => state.status === 'playing' && state.period === 2, 'Second half starts');
  console.log('Functional pitch QA: observing second-half orientation and full-time');
  const secondHalfDeadline = Date.now() + 65_000;
  while (latest.status !== 'ended') {
    assert(Date.now() < secondHalfDeadline, 'Second half failed to reach real server boundary');
    await sampleMesh();
    await page.waitForTimeout(75);
  }
  assert.equal(latest.playhead_ms, 5_400_000);
  await drainBoundary(2);
  checks.push('Full-time finishes delivered action queue and removes ball at the final marker');
  const periodTwo = samples.filter((sample) => sample.period === 2);
  assert(periodTwo.some((sample) => sample.team === metadata.home.team_id) && periodTwo.some((sample) => sample.team === metadata.away.team_id), 'Both switched orientations observed in second half');
  assert(seenKinds.has('SHOT'), 'At least one observed shot mesh checked');
  for (const outcome of ['goal', 'saved', 'blocked', 'off_target']) assert(seenOutcomes.has(outcome), `No actual mesh sample for ${outcome} shot outcome`);
  checks.push('Observed shots/outcomes follow delivered position/optional recorded target; both teams switch physical ends at halftime; no future record rendered');

  await page.getByRole('button', { name: 'Restart replay', exact: true }).first().click();
  const restartDialog = page.getByRole('dialog', { name: 'Restart the replay?' });
  const previousGeneration = latest.generation;
  await restartDialog.getByRole('button', { name: 'Restart replay', exact: true }).click();
  await waitState((state) => state.generation > previousGeneration && state.playhead_ms === 0, 'Restart generation reset');
  await expect(scene).toHaveAttribute('data-ball-visible', 'false');
  await expect(scene).toHaveAttribute('data-queued-events', '0');
  checks.push('Restart clears old-generation ball, route and queue');
  await page.getByRole('button', { name: 'Play replay', exact: true }).click();
  await waitState((state) => state.status === 'playing' && state.generation > previousGeneration, 'Restarted generation plays');
  await observeFor(5_000);
  await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
  await waitState((state) => state.status === 'paused', 'Restarted replay pauses');
  assert(samples.at(-1).period === 1, 'Restarted routes return to first-half physical orientation');
  checks.push('Restarted replay animates new generation from first-half event routes');
  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  const result = { status: 'passed', base_url: baseURL, checks, api_responses_checked: responseCount,
    actual_mesh_samples: samples.length, boundary_drains: boundaryDrains, observed_kinds: [...seenKinds], observed_teams: [...seenTeams],
    observed_shot_outcomes: [...seenOutcomes], errors,
    scope: 'Independent real-browser delivered-event/actual-mesh checks using real replay controls; no seek, fixture-plan injection or mocked client clock' };
  await fs.writeFile(path.join(root, '.runtime', `${outputName}.json`), JSON.stringify(result, null, 2));
  await fs.writeFile(path.join(root, '.runtime', `${outputName}-samples.json`), JSON.stringify(samples, null, 2));
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  await fs.writeFile(path.join(root, '.runtime', `${outputName}-failure.json`), JSON.stringify({ status: 'failed', error: error.message, checks, errors, sample_count: samples.length, recent_samples: samples.slice(-10) }, null, 2));
  throw error;
} finally { await browser.close(); }
