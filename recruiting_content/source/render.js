// Usage: node render.js <file.html> [out.png]
// Renders a 1080x1350 graphic to a 2160x2700 PNG (@2x). Run from the /source folder.
const { chromium } = require('playwright');
const path = require('path');
const file = process.argv[2];
if (!file) { console.error('Usage: node render.js <file.html> [out.png]'); process.exit(1); }
const out = process.argv[3] || file.replace(/\.html$/, '.png');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 2 });
  await page.goto('file://' + path.resolve(file));
  await page.waitForTimeout(400);
  await (await page.$('.card')).screenshot({ path: out });
  await browser.close();
  console.log('wrote', out);
})();
