import { expect, test, type Page } from '@playwright/test'

async function setUp(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Business name').fill('E2E Tax Consultants')
  await page.getByLabel('App password (to unlock this app)').fill('secret-pass-1')
  await page.getByLabel('Confirm password').fill('secret-pass-1')
  await page.getByRole('button', { name: 'Start using CashBook' }).click()
  await page.waitForURL('**/dashboard')
}

async function money(page: Page, value: string) {
  await page.getByLabel('Amount', { exact: true }).fill(value)
}

test('daily cash workflow on a phone', async ({ page, context }) => {
  await setUp(page)
  await expect(page.getByText('Start by entering the opening cash')).toBeVisible()

  // Opening cash balance
  await page.goto('/settings/accounts')
  await page.getByRole('button', { name: 'Set opening' }).first().click()
  await page.getByRole('dialog').locator('input[type=date]').fill('2026-04-01')
  await page.getByRole('dialog').locator('input[inputmode=decimal]').fill('10000')
  await page.getByRole('button', { name: 'Save opening balance' }).click()
  await expect(page.getByText('Opening balance saved')).toBeVisible()

  // Cash income
  await page.goto('/add/income')
  await page.getByLabel('Received from (name)').fill('Walk-in client')
  await page.getByLabel('Service provided *').selectOption({ label: 'GST Return Filing Fees' })
  await money(page, '5000')
  await page.getByRole('button', { name: 'Save receipt' }).click()
  await expect(page.getByRole('dialog', { name: 'Saved' })).toContainText('CR/')
  await page.getByRole('button', { name: 'Done' }).click()

  // Cash expense
  await page.goto('/add/expense')
  await page.getByLabel('Paid to *').fill('Stationery Mart')
  await page.getByLabel('Expense category *').selectOption({ label: 'Printing and Stationery' })
  await money(page, '1500')
  await page.getByRole('button', { name: 'Save expense' }).click()
  await expect(page.getByRole('dialog', { name: 'Saved' })).toContainText('CP/')
  await page.getByRole('button', { name: 'Done' }).click()

  // Dashboard balances come from saved entries
  await page.waitForURL('**/dashboard')
  await expect(page.getByText("Today's Closing Cash").locator('..').locator('..')).toContainText('₹13,500.00')

  // Overspending cash is blocked
  await page.goto('/add/expense')
  await page.getByLabel('Paid to *').fill('Landlord')
  await page.getByLabel('Expense category *').selectOption({ label: 'Office Rent' })
  await money(page, '20000')
  await page.getByRole('button', { name: 'Save expense' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Insufficient cash' }).first()).toBeVisible()

  // UPI expense does not touch cash
  await page.getByRole('radio', { name: 'UPI' }).click()
  await money(page, '999')
  await page.getByRole('button', { name: 'Save expense' }).click()
  await expect(page.getByRole('dialog', { name: 'Saved' })).toContainText('BP/')
  await page.getByRole('button', { name: 'Done' }).click()

  // Cash Book shows running balance and closing
  await page.goto('/cashbook')
  await page.getByRole('radio', { name: 'Current FY' }).click()
  await expect(page.getByText('Closing Balance').first()).toBeVisible()
  await expect(page.locator('body')).toContainText('13,500.00')

  // Offline capture still saves (data lives in IndexedDB)
  await context.setOffline(true)
  await page.goto('/add/income').catch(() => {})
  await context.setOffline(false)
  await page.goto('/add/income')
  await context.setOffline(true)
  await page.getByLabel('Received from (name)').fill('Offline client')
  await page.getByLabel('Service provided *').selectOption({ label: 'Accounting Fees' })
  await money(page, '700')
  await page.getByRole('button', { name: 'Save receipt' }).click()
  await expect(page.getByRole('dialog', { name: 'Saved' })).toBeVisible()
  await context.setOffline(false)

  // Cancel an entry with a reason; it remains listed as cancelled
  await page.goto('/transactions')
  await page.getByText('Offline client').first().click()
  await page.getByRole('button', { name: 'Cancel entry' }).click()
  await page.getByLabel('Reason for cancellation').fill('Entered by mistake')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel entry' }).last().click()
  await expect(page.getByText(/cancelled$/).first()).toBeVisible()

  // Reports render and export buttons exist
  await page.goto('/reports/view?r=income-register')
  await expect(page.getByRole('heading', { name: 'Income Register' }).first()).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Excel' }).click()
  expect((await download).suggestedFilename()).toMatch(/\.xlsx$/)

  // No horizontal scrolling on the phone screen
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('sample data is separate and shows correct balances', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Explore with sample data' }).click()
  await page.waitForURL('**/dashboard')
  await expect(page.getByText('SAMPLE DATA – demo workspace')).toBeVisible()
  await expect(page.getByText("Today's Closing Cash").locator('..').locator('..')).toContainText('₹11,400.00')
  await expect(page.getByText('Bank & UPI Balance').locator('..').locator('..')).toContainText('₹58,501.00')
})

test('installed app opens offline after first visit (service worker)', async ({ page, context }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Explore with sample data' }).click()
  await page.waitForURL('**/dashboard')
  await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready
    return !!reg.active
  })
  // Give the worker time to cache all screens and their assets.
  await page.waitForTimeout(4000)
  await context.setOffline(true)
  await page.goto('/cashbook')
  await expect(page.getByRole('heading', { name: 'Cash Book & Bank Book' })).toBeVisible()
  await page.goto('/reports')
  await expect(page.getByRole('heading', { name: 'Reports' })).toBeVisible()
  await context.setOffline(false)
})
