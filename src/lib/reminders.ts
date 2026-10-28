import { formatDate } from './dates'
import { formatINR } from './money'
import { DEFAULT_SETTINGS, type BusinessProfile, type Client, type FeeBill } from './types'

/** Fills the reminder template from Settings: {client} {amount} {bill} {date} {business}. */
export function reminderText(profile: BusinessProfile | null, client: Client | undefined, bill: FeeBill, outstanding: number): string {
  const tpl = profile?.settings?.reminder_message || DEFAULT_SETTINGS.reminder_message
  return tpl
    .replaceAll('{client}', client?.name ?? 'Sir/Madam')
    .replaceAll('{amount}', formatINR(outstanding))
    .replaceAll('{bill}', bill.bill_no)
    .replaceAll('{date}', formatDate(bill.bill_date))
    .replaceAll('{business}', profile?.name ?? '')
}
