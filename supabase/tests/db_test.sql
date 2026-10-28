-- Database tests for migrations: RLS isolation, accounting rules, sync RPC.
-- Each block raises an exception (failing the run) when an expectation is not met.
\set ON_ERROR_STOP 1

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'owner@example.com'),
  ('00000000-0000-0000-0000-00000000000b', 'other@example.com');

create or replace function pg_temp.act_as(p_user uuid) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claim.sub', p_user::text, false);
  execute 'set role authenticated';
end $$;

create or replace function pg_temp.expect_error(p_sql text, p_like text) returns void language plpgsql as $$
begin
  begin
    execute p_sql;
  exception when others then
    if sqlerrm not ilike '%' || p_like || '%' then
      raise exception 'Expected error like "%" but got "%"', p_like, sqlerrm;
    end if;
    return;
  end;
  raise exception 'Expected an error like "%" for: %', p_like, p_sql;
end $$;

create or replace function pg_temp.push(p_table text, p_row jsonb, p_base int default 0) returns jsonb language sql as $$
  select public.sync_push(p_table, p_row, p_base)
$$;

-- ---------------------------------------------------------------- setup (user A)
select pg_temp.act_as('00000000-0000-0000-0000-00000000000a');

do $$
declare r jsonb;
begin
  r := pg_temp.push('business_profiles', jsonb_build_object(
    'id', '10000000-0000-0000-0000-000000000001', 'name', 'FIN TAX PRO', 'owner_id', null, 'settings', '{}'::jsonb));
  if r->>'status' <> 'ok' then raise exception 'business insert failed: %', r; end if;
  if (r->'row'->>'owner_id') <> '00000000-0000-0000-0000-00000000000a' then raise exception 'owner not set from auth.uid()'; end if;
  if not public.is_business_member('10000000-0000-0000-0000-000000000001', array['owner']) then
    raise exception 'owner membership not created';
  end if;
end $$;

do $$
declare b text := '10000000-0000-0000-0000-000000000001';
begin
  perform pg_temp.push('accounts', jsonb_build_object('id','20000000-0000-0000-0000-000000000001','business_id',b,'name','Cash in Hand','kind','cash'));
  perform pg_temp.push('accounts', jsonb_build_object('id','20000000-0000-0000-0000-000000000002','business_id',b,'name','Bank','kind','bank'));
  perform pg_temp.push('accounts', jsonb_build_object('id','20000000-0000-0000-0000-000000000003','business_id',b,'name','UPI','kind','upi'));
  perform pg_temp.push('categories', jsonb_build_object('id','30000000-0000-0000-0000-000000000001','business_id',b,'kind','income','name','GST Return Filing Fees'));
  perform pg_temp.push('categories', jsonb_build_object('id','30000000-0000-0000-0000-000000000002','business_id',b,'kind','expense','name','Printing and Stationery'));
  perform pg_temp.push('clients', jsonb_build_object('id','40000000-0000-0000-0000-000000000001','business_id',b,'code','C-0001','name','Sharma Traders'));
  perform pg_temp.push('opening_balances', jsonb_build_object('id','50000000-0000-0000-0000-000000000001','business_id',b,
    'account_id','20000000-0000-0000-0000-000000000001','as_of_date','2026-04-01','amount_paise',1000000,'reason',''));
end $$;

-- ------------------------------------------------------------- transactions
do $$
declare b text := '10000000-0000-0000-0000-000000000001'; r jsonb; n int;
begin
  -- cash receipt ₹5,000
  r := pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000001','business_id',b,
    'type','income','voucher_no','CR/26-27/001','txn_date','2026-04-02','amount_paise',500000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000001',
    'client_id','40000000-0000-0000-0000-000000000001'));
  if r->>'status' <> 'ok' or (r->'row'->>'version')::int <> 1 then raise exception 'insert failed: %', r; end if;

  -- retrying the identical push must not duplicate
  r := pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000001','business_id',b,
    'type','income','voucher_no','CR/26-27/001','txn_date','2026-04-02','amount_paise',500000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000001',
    'client_id','40000000-0000-0000-0000-000000000001'));
  select count(*) into n from public.transactions;
  if r->>'status' <> 'ok' or n <> 1 then raise exception 'idempotent retry failed: % rows=%', r, n; end if;

  -- cash payment ₹1,500
  r := pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000002','business_id',b,
    'type','expense','voucher_no','CP/26-27/001','txn_date','2026-04-03','amount_paise',150000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000002','party','Stationery Mart'));
  if r->>'status' <> 'ok' then raise exception 'expense failed: %', r; end if;
end $$;

-- cash payment larger than cash available (10,000 + 5,000 - 1,500 = 13,500)
select pg_temp.expect_error($q$
  select pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000003','business_id','10000000-0000-0000-0000-000000000001',
    'type','expense','voucher_no','CP/26-27/002','txn_date','2026-04-04','amount_paise',1400000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000002','party','X'))
$q$, 'Insufficient cash');

-- back-dated payment that would make a LATER day negative is also refused
select pg_temp.expect_error($q$
  select pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000004','business_id','10000000-0000-0000-0000-000000000001',
    'type','expense','voucher_no','CP/26-27/002','txn_date','2026-04-01','amount_paise',1100000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000002','party','X'))
$q$, 'Insufficient cash');

-- UPI receipt must not be posted to the cash account
select pg_temp.expect_error($q$
  select pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000005','business_id','10000000-0000-0000-0000-000000000001',
    'type','income','voucher_no','BR/26-27/001','txn_date','2026-04-04','amount_paise',150000,'payment_method','upi',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000001','party','Y'))
$q$, 'cannot post');

-- contra must not carry a category
select pg_temp.expect_error($q$
  select pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000006','business_id','10000000-0000-0000-0000-000000000001',
    'type','contra','voucher_no','CT/26-27/001','txn_date','2026-04-04','amount_paise',100000,'payment_method','other',
    'account_id','20000000-0000-0000-0000-000000000001','to_account_id','20000000-0000-0000-0000-000000000002',
    'category_id','30000000-0000-0000-0000-000000000001'))
$q$, 'contra_shape');

-- voucher collision from another offline device is renumbered, not duplicated
do $$
declare r jsonb;
begin
  r := pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000007','business_id','10000000-0000-0000-0000-000000000001',
    'type','income','voucher_no','CR/26-27/001','txn_date','2026-04-05','amount_paise',250000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000001','party','Walk-in'));
  if r->'row'->>'voucher_no' <> 'CR/26-27/002' then raise exception 'voucher not renumbered: %', r; end if;
end $$;

-- optimistic concurrency
do $$
declare r jsonb; row jsonb;
begin
  select to_jsonb(t) - 'sync_seq' into row from public.transactions t where id = '60000000-0000-0000-0000-000000000002';
  r := pg_temp.push('transactions', row || '{"narration":"Edited on phone"}', 1);
  if r->>'status' <> 'ok' or (r->'row'->>'version')::int <> 2 then raise exception 'update failed: %', r; end if;
  -- a laptop still holding version 1 tries to save a different edit
  r := pg_temp.push('transactions', row || '{"narration":"Edited on laptop"}', 1);
  if r->>'status' <> 'conflict' or r->'row'->>'narration' <> 'Edited on phone' then raise exception 'conflict not detected: %', r; end if;
end $$;

-- cancellation keeps the row and requires a reason
select pg_temp.expect_error($q$ update public.transactions set status = 'cancelled' where id = '60000000-0000-0000-0000-000000000002' $q$, 'cancel_reason_required');
update public.transactions set status = 'cancelled', cancel_reason = 'Duplicate bill' where id = '60000000-0000-0000-0000-000000000002';

-- cancelling a receipt that later payments depend on is refused
do $$
begin
  perform pg_temp.push('transactions', jsonb_build_object('id','60000000-0000-0000-0000-000000000008','business_id','10000000-0000-0000-0000-000000000001',
    'type','expense','voucher_no','CP/26-27/003','txn_date','2026-04-06','amount_paise',1600000,'payment_method','cash',
    'account_id','20000000-0000-0000-0000-000000000001','category_id','30000000-0000-0000-0000-000000000002','party','Rent'));
end $$;
select pg_temp.expect_error($q$ update public.transactions set status = 'cancelled', cancel_reason = 'x' where id = '60000000-0000-0000-0000-000000000001' $q$, 'Insufficient cash');

-- deletes are refused
select pg_temp.expect_error($q$ delete from public.transactions where id = '60000000-0000-0000-0000-000000000001' $q$, 'permission denied');
reset role;
select pg_temp.expect_error($q$ delete from public.transactions where id = '60000000-0000-0000-0000-000000000001' $q$, 'cannot be deleted');
select pg_temp.act_as('00000000-0000-0000-0000-00000000000a');

-- audit trail written by the database and append-only
do $$
declare n int;
begin
  select count(*) into n from public.audit_logs where source = 'db' and entity = 'transactions';
  if n < 5 then raise exception 'expected db audit rows, found %', n; end if;
  if not exists (select 1 from public.audit_logs where action = 'cancel') then raise exception 'cancel not audited'; end if;
end $$;
select pg_temp.expect_error($q$ update public.audit_logs set summary = 'tampered' $q$, 'permission denied');
reset role;
select pg_temp.expect_error($q$ update public.audit_logs set summary = 'tampered' $q$, 'cannot be modified');
select pg_temp.act_as('00000000-0000-0000-0000-00000000000a');
select pg_temp.expect_error($q$ insert into public.audit_logs (business_id, entity, entity_id, action, source)
  values ('10000000-0000-0000-0000-000000000001','transactions','60000000-0000-0000-0000-000000000001','update','db') $q$, 'row-level security');

-- fee bills & allocations
do $$
declare r jsonb;
begin
  r := pg_temp.push('fee_bills', jsonb_build_object('id','70000000-0000-0000-0000-000000000001','business_id','10000000-0000-0000-0000-000000000001',
    'bill_no','FB/26-27/001','bill_date','2026-04-01','client_id','40000000-0000-0000-0000-000000000001','amount_paise',300000,'service','GST'));
  if r->>'status' <> 'ok' then raise exception 'bill failed %', r; end if;
  r := pg_temp.push('fee_allocations', jsonb_build_object('id','80000000-0000-0000-0000-000000000001','business_id','10000000-0000-0000-0000-000000000001',
    'fee_bill_id','70000000-0000-0000-0000-000000000001','transaction_id','60000000-0000-0000-0000-000000000001','amount_paise',300000));
  if r->>'status' <> 'ok' then raise exception 'allocation failed %', r; end if;
end $$;
select pg_temp.expect_error($q$
  select pg_temp.push('fee_allocations', jsonb_build_object('id','80000000-0000-0000-0000-000000000002','business_id','10000000-0000-0000-0000-000000000001',
    'fee_bill_id','70000000-0000-0000-0000-000000000001','transaction_id','60000000-0000-0000-0000-000000000007','amount_paise',100000))
$q$, 'same client');

-- fee bill numbers picked twice offline are renumbered, not rejected
do $$
declare r jsonb;
begin
  r := pg_temp.push('fee_bills', jsonb_build_object('id','70000000-0000-0000-0000-000000000002','business_id','10000000-0000-0000-0000-000000000001',
    'bill_no','FB/26-27/001','bill_date','2026-04-02','client_id','40000000-0000-0000-0000-000000000001','amount_paise',100000,'service','TDS'));
  if r->'row'->>'bill_no' <> 'FB/26-27/002' then raise exception 'bill not renumbered: %', r; end if;
end $$;

-- books lock
update public.business_profiles set settings = '{"books_locked_until":"2026-04-03"}' where id = '10000000-0000-0000-0000-000000000001';
select pg_temp.expect_error($q$ update public.transactions set narration = 'late edit' where id = '60000000-0000-0000-0000-000000000001' $q$, 'locked');
update public.business_profiles set settings = '{}' where id = '10000000-0000-0000-0000-000000000001';

-- ------------------------------------------------------- isolation (user B)
select pg_temp.act_as('00000000-0000-0000-0000-00000000000b');
do $$
declare n int;
begin
  select count(*) into n from public.transactions;
  if n <> 0 then raise exception 'user B can see % transactions of user A', n; end if;
  select count(*) into n from public.business_profiles;
  if n <> 0 then raise exception 'user B can see business of user A'; end if;
  select count(*) into n from public.audit_logs;
  if n <> 0 then raise exception 'user B can see audit logs of user A'; end if;
end $$;
select pg_temp.expect_error($q$
  select pg_temp.push('clients', jsonb_build_object('id','40000000-0000-0000-0000-0000000000ff','business_id','10000000-0000-0000-0000-000000000001','code','C-9','name','Intruder'))
$q$, 'row-level security');
-- user B cannot attach their rows to user A's accounts/clients (composite FKs)
do $$
begin
  perform pg_temp.push('business_profiles', jsonb_build_object('id','10000000-0000-0000-0000-0000000000b0','name','B Practice','settings','{}'::jsonb));
end $$;
select pg_temp.expect_error($q$
  select pg_temp.push('opening_balances', jsonb_build_object('id','50000000-0000-0000-0000-0000000000b1','business_id','10000000-0000-0000-0000-0000000000b0',
    'account_id','20000000-0000-0000-0000-000000000001','as_of_date','2026-04-01','amount_paise',-99999999,'reason','x'))
$q$, 'foreign key');
select pg_temp.expect_error($q$
  select pg_temp.push('fee_bills', jsonb_build_object('id','70000000-0000-0000-0000-0000000000b1','business_id','10000000-0000-0000-0000-0000000000b0',
    'bill_no','FB/26-27/001','bill_date','2026-04-01','client_id','40000000-0000-0000-0000-000000000001','amount_paise',100,'service','x'))
$q$, 'foreign key');

do $$
declare n int;
begin
  update public.transactions set amount_paise = 1 where id = '60000000-0000-0000-0000-000000000001';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'user B updated user A data'; end if;
end $$;

-- anonymous users see nothing
reset role;
set role anon;
select pg_temp.expect_error($q$ select count(*) from public.transactions $q$, 'permission denied');
reset role;

\echo 'db_test.sql: all assertions passed'
