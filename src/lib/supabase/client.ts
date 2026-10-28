import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = process.env.NEXT_PUBLIC_SUPABASE_URL
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

let client: SupabaseClient | null = null

export function isSupabaseConfigured(): boolean {
  return !!url && !!anonKey && !url.includes('your-project-ref')
}

/** Local (device-only) mode is allowed only when explicitly enabled or when Supabase is not configured in development. */
export function isLocalModeAllowed(): boolean {
  return process.env.NEXT_PUBLIC_ALLOW_LOCAL_MODE === 'true' || !isSupabaseConfigured()
}

/**
 * Browser Supabase client using ONLY the public anon key. Every query is
 * restricted by Row Level Security in the database; the service-role key
 * must never be shipped to the browser.
 */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured()) return null
  if (!client) {
    client = createClient(url!, anonKey!, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
      },
    })
  }
  return client
}
