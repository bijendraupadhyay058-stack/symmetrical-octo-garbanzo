-- FIN TAX PRO – CashBook: integrity rules, audit triggers and Row Level Security

-- ------------------------------------------------------------ membership
create or replace function public.is_business_member(p_business uuid, p_roles text[] default null)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.business_members m
    where m.business_id = p_business
      and m.user_id = auth.uid()
      and (p_roles is null or m.role = any (p_roles))
  );
$$;
revoke all on function public.is_business_member(uuid, text[]) from public;
grant execute on function public.is_business_member(uuid, text[]) to authenticated;

-- ------------------------------------------------- server-managed columns
create or replace function public.tg_server_fields()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    new.version := 1;
    new.created_at := least(coalesce(new.created_at, now()), now());
  else
    if new.id <> old.id then raise exception 'id is immutable'; end if;
    -- (business_profiles.business_id is a generated column, NULL inside BEFORE triggers)
    if tg_table_name <> 'business_profiles' and new.business_id is distinct from old.business_id then
      raise exception 'business_id is immutable';
    end if;
    new.version := old.version + 1;
    new.created_at := old.created_at;
  end if;
  new.updated_at := now();
  new.sync_seq := nextval('public.sync_seq');
  return new;
end;
$$;

create or replace function public.tg_prevent_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception 'Accounting records cannot be deleted. Cancel or deactivate them instead.'
    using errcode = 'P0001';
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['business_profiles','accounts','opening_balances','categories','clients',
                           'transactions','fee_bills','fee_allocations','recurring_templates','attachments','audit_logs']
  loop
    execute format('create trigger a_server_fields before insert or update on public.%I
                    for each row execute function public.tg_server_fields()', t);
    execute format('create trigger z_prevent_delete before delete on public.%I
                    for each row execute function public.tg_prevent_delete()', t);
  end loop;
end $$;

-- ------------------------------------------------------- business owner
create or replace function public.tg_business_owner()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    new.owner_id := coalesce(auth.uid(), new.owner_id);
  elsif new.owner_id is distinct from old.owner_id then
    raise exception 'owner cannot be changed';
  end if;
  return new;
end;
$$;
create trigger b_business_owner before insert or update on public.business_profiles
  for each row execute function public.tg_business_owner();

create or replace function public.tg_business_membership()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.business_members (business_id, user_id, role)
  values (new.id, new.owner_id, 'owner')
  on conflict do nothing;
  return new;
end;
$$;
create trigger c_business_membership after insert on public.business_profiles
  for each row execute function public.tg_business_membership();

-- --------------------------------------------------- audit trail is append-only
create or replace function public.tg_audit_append_only()
returns trigger
language plpgsql
as $$
begin
  raise exception 'Audit log entries cannot be modified' using errcode = 'P0001';
end;
$$;
create trigger b_audit_append_only before update on public.audit_logs
  for each row execute function public.tg_audit_append_only();

-- Database-side audit (cannot be skipped by a client).
create or replace function public.tg_db_audit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_action text;
begin
  v_action := case when tg_op = 'INSERT' then 'create' else 'update' end;
  if tg_op = 'UPDATE' and tg_table_name in ('transactions', 'fee_bills') then
    if to_jsonb(old) ->> 'status' = 'active' and to_jsonb(new) ->> 'status' = 'cancelled' then v_action := 'cancel';
    elsif to_jsonb(old) ->> 'status' = 'cancelled' and to_jsonb(new) ->> 'status' = 'active' then v_action := 'restore';
    end if;
  end if;
  insert into public.audit_logs (business_id, entity, entity_id, action, summary, before_data, after_data, source)
  values (new.business_id, tg_table_name, new.id, v_action,
          format('%s %s (server v%s)', initcap(v_action), tg_table_name, new.version),
          case when tg_op = 'UPDATE' then to_jsonb(old) - 'sync_seq' end,
          to_jsonb(new) - 'sync_seq', 'db');
  return null;
end;
$$;
create trigger z_db_audit after insert or update on public.transactions for each row execute function public.tg_db_audit();
create trigger z_db_audit after insert or update on public.fee_bills for each row execute function public.tg_db_audit();
create trigger z_db_audit after insert or update on public.opening_balances for each row execute function public.tg_db_audit();
create trigger z_db_audit after insert or update on public.fee_allocations for each row execute function public.tg_db_audit();

-- ------------------------------------------------------ voucher numbering
-- Vouchers look like CR/26-27/001. If two offline devices picked the same
-- number, the later one is renumbered here instead of being rejected or
-- duplicated; the device receives the final number when it syncs.
create or replace function public.next_voucher_no(p_business uuid, p_prefix text, p_fy text)
returns text
language sql
stable
as $$
  select p_prefix || '/' || p_fy || '/' || lpad((coalesce(max(substring(voucher_no from '\d+$')::int), 0) + 1)::text, 3, '0')
  from public.transactions
  where business_id = p_business and voucher_no like p_prefix || '/' || p_fy || '/%';
$$;

-- ------------------------------------------------- transaction validation
create or replace function public.cash_first_negative(p_account uuid, p_from date)
returns table (day date, balance bigint)
language sql
stable
as $$
  with ob as (
    select amount_paise from public.opening_balances
    where account_id = p_account order by created_at desc, sync_seq desc limit 1
  ),
  mv as (
    select txn_date as d,
           sum(case when (type = 'income' and account_id = p_account) or (type = 'contra' and to_account_id = p_account)
                    then amount_paise else -amount_paise end) as net
    from public.transactions
    where status = 'active'
      and (account_id = p_account or to_account_id = p_account)
    group by txn_date
  ),
  running as (
    select d, coalesce((select amount_paise from ob), 0) + sum(net) over (order by d) as bal from mv
  )
  select d, bal::bigint from running where bal < 0 and d >= p_from order by d limit 1;
$$;

create or replace function public.tg_transaction_rules()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_acc public.accounts;
  v_to public.accounts;
  v_cat public.categories;
  v_lock date;
  v_prefix text;
  v_fy int;
  v_fy_txt text;
begin
  select * into v_acc from public.accounts where id = new.account_id;
  if v_acc.business_id is distinct from new.business_id then raise exception 'Account does not belong to this business'; end if;
  if new.type = 'contra' then
    select * into v_to from public.accounts where id = new.to_account_id;
    if v_to.business_id is distinct from new.business_id then raise exception 'Destination account does not belong to this business'; end if;
  else
    select * into v_cat from public.categories where id = new.category_id;
    if v_cat.business_id is distinct from new.business_id or v_cat.kind <> new.type then
      raise exception 'Category does not match this business or entry type';
    end if;
    -- Cash must post to the Cash Book only; UPI/bank must never touch physical cash.
    if (new.payment_method = 'cash') <> (v_acc.kind = 'cash') then
      raise exception 'Payment method % cannot post to a % account', new.payment_method, v_acc.kind;
    end if;
  end if;
  if new.client_id is not null and not exists (select 1 from public.clients c where c.id = new.client_id and c.business_id = new.business_id) then
    raise exception 'Client does not belong to this business';
  end if;

  -- Locked books
  select nullif(settings->>'books_locked_until', '')::date into v_lock from public.business_profiles where id = new.business_id;
  if v_lock is not null and (new.txn_date <= v_lock or (tg_op = 'UPDATE' and old.txn_date <= v_lock)) then
    raise exception 'Books are locked up to %', v_lock using errcode = 'P0001';
  end if;

  -- Voucher number uniqueness (renumber on collision)
  if exists (select 1 from public.transactions t where t.business_id = new.business_id and t.voucher_no = new.voucher_no and t.id <> new.id)
     or new.voucher_no !~ '^[A-Z]{2}/\d{2}-\d{2}/\d+$' then
    v_prefix := case when new.type = 'contra' then 'CT'
                     when new.type = 'income' then case when v_acc.kind = 'cash' then 'CR' else 'BR' end
                     else case when v_acc.kind = 'cash' then 'CP' else 'BP' end end;
    v_fy := case when extract(month from new.txn_date) >= 4 then extract(year from new.txn_date)::int else extract(year from new.txn_date)::int - 1 end;
    v_fy_txt := lpad((v_fy % 100)::text, 2, '0') || '-' || lpad(((v_fy + 1) % 100)::text, 2, '0');
    new.voucher_no := public.next_voucher_no(new.business_id, v_prefix, v_fy_txt);
  end if;
  return new;
end;
$$;
create trigger b_transaction_rules before insert or update on public.transactions
  for each row execute function public.tg_transaction_rules();

-- Cash may not go negative because of an entry (checked after the write so it
-- sees the final state). An earlier shortfall caused by an authorised opening
-- balance correction does not block unrelated later entries.
create or replace function public.tg_cash_not_negative()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_acc uuid;
  v_from date;
  v_neg record;
begin
  v_from := case when tg_op = 'UPDATE' then least(old.txn_date, new.txn_date) else new.txn_date end;
  for v_acc in
    select a.id from public.accounts a
    where a.kind = 'cash'
      and a.id in (new.account_id, new.to_account_id,
                   case when tg_op = 'UPDATE' then old.account_id end,
                   case when tg_op = 'UPDATE' then old.to_account_id end)
  loop
    if exists (select 1 from public.cash_first_negative(v_acc, '0001-01-01'::date) f where f.day < v_from) then
      continue;
    end if;
    select * into v_neg from public.cash_first_negative(v_acc, v_from);
    if found then
      raise exception 'Insufficient cash: balance would be % paise on %', v_neg.balance, v_neg.day
        using errcode = 'P0001';
    end if;
  end loop;
  return null;
end;
$$;
create constraint trigger y_cash_not_negative after insert or update on public.transactions
  for each row execute function public.tg_cash_not_negative();

-- Fee allocations: same client, never more than the bill's outstanding or the receipt amount.
create or replace function public.tg_allocation_rules()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_bill public.fee_bills;
  v_txn public.transactions;
  v_bill_total bigint;
  v_txn_total bigint;
begin
  select * into v_bill from public.fee_bills where id = new.fee_bill_id;
  select * into v_txn from public.transactions where id = new.transaction_id;
  if v_bill.business_id <> new.business_id or v_txn.business_id <> new.business_id then
    raise exception 'Allocation crosses businesses';
  end if;
  if v_txn.type <> 'income' or v_txn.client_id is distinct from v_bill.client_id then
    raise exception 'Only a receipt from the same client can be adjusted against this bill';
  end if;
  select coalesce(sum(a.amount_paise), 0) into v_bill_total
  from public.fee_allocations a join public.transactions t on t.id = a.transaction_id
  where a.fee_bill_id = new.fee_bill_id and t.status = 'active';
  if v_bill_total > v_bill.amount_paise then
    raise exception 'Adjustments exceed bill % amount', v_bill.bill_no using errcode = 'P0001';
  end if;
  select coalesce(sum(amount_paise), 0) into v_txn_total from public.fee_allocations where transaction_id = new.transaction_id;
  if v_txn_total > v_txn.amount_paise then
    raise exception 'Adjustments exceed receipt % amount', v_txn.voucher_no using errcode = 'P0001';
  end if;
  return null;
end;
$$;
create constraint trigger y_allocation_rules after insert or update on public.fee_allocations
  for each row execute function public.tg_allocation_rules();

-- ----------------------------------------------------- row level security
alter table public.business_profiles enable row level security;
alter table public.business_members enable row level security;

create policy business_select on public.business_profiles for select to authenticated
  using (owner_id = auth.uid() or public.is_business_member(id));
create policy business_insert on public.business_profiles for insert to authenticated
  with check (owner_id = auth.uid());
create policy business_update on public.business_profiles for update to authenticated
  using (public.is_business_member(id, array['owner'])) with check (public.is_business_member(id, array['owner']));

create policy members_select on public.business_members for select to authenticated
  using (user_id = auth.uid() or public.is_business_member(business_id, array['owner']));

do $$
declare t text;
begin
  foreach t in array array['accounts','opening_balances','categories','clients','transactions','fee_bills',
                           'fee_allocations','recurring_templates','attachments']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy member_select on public.%I for select to authenticated using (public.is_business_member(business_id))', t);
    execute format('create policy member_insert on public.%I for insert to authenticated with check (public.is_business_member(business_id, array[''owner'',''accountant'']))', t);
    execute format('create policy member_update on public.%I for update to authenticated using (public.is_business_member(business_id, array[''owner'',''accountant''])) with check (public.is_business_member(business_id, array[''owner'',''accountant'']))', t);
    -- no delete policy: deletes are refused for every client role
  end loop;
end $$;

alter table public.audit_logs enable row level security;
create policy audit_select on public.audit_logs for select to authenticated using (public.is_business_member(business_id));
create policy audit_insert on public.audit_logs for insert to authenticated
  with check (public.is_business_member(business_id) and source = 'app');

-- Least privilege for the API roles.
revoke all on all tables in schema public from anon;
revoke delete, truncate on all tables in schema public from authenticated;
grant select, insert, update on public.business_profiles, public.accounts, public.opening_balances, public.categories,
  public.clients, public.transactions, public.fee_bills, public.fee_allocations, public.recurring_templates,
  public.attachments to authenticated;
grant select, insert on public.audit_logs to authenticated;
grant select on public.business_members to authenticated;
grant usage on sequence public.sync_seq to authenticated;
