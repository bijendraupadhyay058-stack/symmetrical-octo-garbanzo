-- FIN TAX PRO – CashBook: device synchronisation RPC and private file storage

-- sync_push: idempotent, version-checked upsert used by the app's sync engine.
--   * new id               -> insert
--   * same data already    -> ok (a retried push after a lost response)
--   * version matches      -> update (version + 1)
--   * version mismatch     -> 'conflict' with the server copy; nothing written
-- Runs as the caller (SECURITY INVOKER) so Row Level Security applies fully.
create or replace function public.sync_push(p_table text, p_row jsonb, p_base_version integer)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_id uuid := (p_row ->> 'id')::uuid;
  v_cols text[];
  v_collist text;
  v_existing jsonb;
  v_incoming jsonb;
  v_result jsonb;
  v_same boolean;
begin
  if p_table not in ('business_profiles','accounts','opening_balances','categories','clients','transactions',
                     'fee_bills','fee_allocations','recurring_templates','attachments','audit_logs') then
    raise exception 'Table % cannot be synchronised', p_table using errcode = '22023';
  end if;
  if v_id is null then
    raise exception 'Row id is required' using errcode = '22023';
  end if;

  select array_agg(column_name::text order by ordinal_position) into v_cols
  from information_schema.columns
  where table_schema = 'public' and table_name = p_table
    and is_generated = 'NEVER'
    and column_name not in ('sync_seq', 'version', 'updated_at', 'actor_id', 'source')
    and p_row ? column_name;
  select string_agg(quote_ident(c), ', ') into v_collist from unnest(v_cols) c;

  execute format('select to_jsonb(t) from public.%I t where id = $1 for update', p_table)
    into v_existing using v_id;

  if v_existing is null then
    execute format('insert into public.%1$I (%2$s) select %2$s from jsonb_populate_record(null::public.%1$I, $1) returning to_jsonb(%1$I.*)',
                   p_table, v_collist)
      into v_result using p_row;
    return jsonb_build_object('status', 'ok', 'row', v_result - 'actor_id');
  end if;

  if p_table = 'audit_logs' then
    -- append-only: a retry of an existing entry is simply acknowledged
    return jsonb_build_object('status', 'ok', 'row', v_existing - 'actor_id');
  end if;

  execute format('select to_jsonb(r) from jsonb_populate_record(null::public.%I, $1) r', p_table)
    into v_incoming using p_row;
  select bool_and((v_existing -> c) is not distinct from (v_incoming -> c)) into v_same
  from unnest(v_cols) c
  where c not in ('created_at', 'owner_id');
  if v_same then
    return jsonb_build_object('status', 'ok', 'row', v_existing - 'actor_id');
  end if;

  -- base 0 = the device created this row and never received the server's
  -- reply; it is the same device's row as long as nobody else changed it (v1).
  if (v_existing ->> 'version')::int <> greatest(p_base_version, 1) then
    return jsonb_build_object('status', 'conflict', 'row', v_existing - 'actor_id');
  end if;

  execute format('update public.%1$I t set (%2$s) = (select %2$s from jsonb_populate_record(null::public.%1$I, $1)) where t.id = $2 returning to_jsonb(t.*)',
                 p_table, v_collist)
    into v_result using p_row, v_id;
  if v_result is null then
    raise exception 'Not permitted' using errcode = '42501';
  end if;
  return jsonb_build_object('status', 'ok', 'row', v_result - 'actor_id');
end;
$$;
revoke all on function public.sync_push(text, jsonb, integer) from public, anon;
grant execute on function public.sync_push(text, jsonb, integer) to authenticated;

-- Private bucket for bill photos and receipts. Files live under
-- <business_id>/<transaction_id>/<attachment_id> and are only reachable by
-- members of that business via short-lived signed URLs.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('attachments', 'attachments', false, 5242880, array['image/jpeg','image/png','image/webp','application/pdf'])
    on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

    execute $p$create policy attachments_read on storage.objects for select to authenticated
      using (bucket_id = 'attachments' and public.is_business_member(((storage.foldername(name))[1])::uuid))$p$;
    execute $p$create policy attachments_write on storage.objects for insert to authenticated
      with check (bucket_id = 'attachments' and public.is_business_member(((storage.foldername(name))[1])::uuid, array['owner','accountant']))$p$;
  end if;
end $$;
