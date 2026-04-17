import { test } from '@playwright/test';

test('capture prod console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push('CONSOLE: ' + msg.text()); });
  page.on('pageerror', err => errors.push('PAGEERROR: ' + err.message + '\n' + (err.stack ?? '').split('\n').slice(0, 10).join('\n')));
  await page.goto('https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io', { waitUntil: 'load', timeout: 30000 });
  await page.waitForTimeout(8000);
  console.log('ERROR COUNT:', errors.length);
  errors.forEach(e => console.log(e));
  if (!errors.length) console.log('No errors. Title:', await page.title());
});
