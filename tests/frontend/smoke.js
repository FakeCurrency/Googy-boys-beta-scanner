// Frontend smoke test — boots the site in headless Chromium and walks the
// core flows (boot skeleton, top-list ranking, scorecard, search) with no
// test framework: plain node + playwright, exit 1 on any failure.
//
//   BASE_URL        server to test (default http://localhost:8766)
//   CHROMIUM_PATH   optional browser binary, for sandboxes where Playwright's
//                   own download is unavailable (CI leaves this unset)
//
// Only uncaught page exceptions (pageerror) fail the test. Console/resource
// errors are ignored on purpose: map tiles and other third-party requests
// are routinely blocked in CI sandboxes and say nothing about the app code.

const { chromium } = require("playwright");

const BASE_URL = process.env.BASE_URL || "http://localhost:8766";

let failures = 0;
const pass = msg => console.log(`PASS  ${msg}`);
const fail = msg => { failures++; console.error(`FAIL  ${msg}`); };

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  try {
    // desktop viewport: keeps the search input inline (it hides behind a
    // toggle below 900px) and the info panel expanded
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const pageErrors = [];
    page.on("pageerror", err => pageErrors.push(err));

    console.log(`Loading ${BASE_URL} …`);
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

    // boot skeleton gets class "done" once the data is painted, then removes
    // itself 500ms later — wait for the removal (it never happens on a boot
    // error, so the timeout catches broken data loads too)
    await page.waitForSelector("#boot.done", { timeout: 20000 });
    await page.waitForSelector("#boot", { state: "detached", timeout: 5000 });
    pass("boot skeleton finished");

    // first visit (fresh browser profile) shows the coach marks ~700ms after
    // boot — dismiss them so they don't sit over the UI we're about to click
    const skip = await page.waitForSelector("#coachSkip", { timeout: 4000 }).catch(() => null);
    if (skip) {
      await skip.click();
      await page.waitForSelector("#coach", { state: "detached", timeout: 5000 });
      console.log("      (dismissed first-visit coach marks)");
    }

    // (a) no uncaught exceptions during load
    if (pageErrors.length === 0) pass("no page errors during load");
    else fail(`${pageErrors.length} page error(s) during load: ${pageErrors.map(e => e.message).join(" | ")}`);
    const errorsAtLoad = pageErrors.length;

    // (b) the ranked top list is populated
    const rows = await page.$$("#topList li[data-code]");
    if (rows.length >= 5) pass(`top list has ${rows.length} suburb rows`);
    else fail(`top list has ${rows.length} suburb rows (expected >= 5)`);

    // (c) clicking a row renders the scorecard: suburb name + 3 ring gauges
    if (rows.length) {
      await rows[0].click();
      const name = await page.waitForSelector("#scorecard .sc-name", { timeout: 5000 })
        .then(el => el.textContent()).catch(() => "");
      const rings = await page.$$("#scorecard .ring");
      if (name && name.trim()) pass(`scorecard renders "${name.trim()}"`);
      else fail("scorecard .sc-name is missing or empty");
      if (rings.length === 3) pass("scorecard shows 3 ring gauges");
      else fail(`scorecard shows ${rings.length} ring gauges (expected 3)`);
    } else {
      fail("scorecard check skipped — no top-list row to click");
    }

    // (d) search finds a known suburb
    await page.fill("#search", "Carlton");
    const res = await page.waitForSelector("#results .res", { timeout: 5000 }).catch(() => null);
    if (res) pass(`search "Carlton" returned ${(await page.$$("#results .res")).length} result(s)`);
    else fail('search "Carlton" returned no results');

    // late errors: anything the clicks/typing above threw
    if (pageErrors.length > errorsAtLoad) {
      const late = pageErrors.slice(errorsAtLoad);
      fail(`${late.length} page error(s) during interaction: ${late.map(e => e.message).join(" | ")}`);
    }
  } catch (err) {
    fail(`unexpected error: ${err.message}`);
  } finally {
    await browser.close();
  }

  if (failures) { console.error(`\n${failures} check(s) failed`); process.exit(1); }
  console.log("\nAll checks passed");
})();
