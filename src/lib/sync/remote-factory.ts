import { getSupabase } from '../supabase/client'
import type { Remote } from './engine'
import { supabaseRemote } from './supabase-remote'

export function createRemote(): Remote | null {
  const sb = getSupabase()
  return sb ? supabaseRemote(sb) : null
}
