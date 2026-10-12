import { test, expect } from '@playwright/test';

const prefix = process.env.EVIDENCE_PREFIX || 'seatlock';

test('discover, filter and search real events', async ({ page }, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Less scrolling. More living.' })).toBeVisible();
  await expect(page.locator('.event-card')).toHaveCount(4);
  await page.screenshot({
    path: `../docs/screenshots/e2e/${prefix}-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: 'Comedy', exact: true }).click();
  await expect(page.locator('.event-card')).toHaveCount(1);
  await expect(page.locator('.event-card')).toContainText('Funny Business');
  await page.getByRole('button', { name: 'All events', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search events' }).fill('no-matching-show');
  await expect(page.getByText('No events found', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('.event-card')).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('hold, reload, confirm, view and cancel a booking', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on('pageerror', (error) => consoleErrors.push(error.message));
  await page.goto('/');
  await page.locator('.event-card').first().click();
  await expect(page.getByRole('heading', { name: 'Pick your seats' })).toBeVisible();
  await page.locator('.seat.available').first().click();
  await page.screenshot({
    path: `../docs/screenshots/e2e/${prefix}-seats-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: 'Hold my seats' }).click();
  await expect(page.getByText('Your seats are held.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Confirm demo booking' })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm demo booking' }).click();
  await expect(page.getByText('Your demo booking is confirmed. No payment was taken.')).toBeVisible();
  await expect(page.locator('.receipt')).toContainText('SL-');
  await page.screenshot({
    path: `../docs/screenshots/e2e/${prefix}-confirmed-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('link', { name: 'View my tickets' }).click();
  await expect(page.locator('.receipt')).toHaveCount(1);
  await page.getByRole('button', { name: 'Cancel booking', exact: true }).click();
  await page.getByRole('button', { name: 'Yes, cancel booking' }).click();
  await expect(page.locator('.status-pill')).toHaveText('cancelled');
  expect(consoleErrors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
