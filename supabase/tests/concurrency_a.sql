-- Device A: ₹700 cash payment, held open for 2 seconds before commit.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000c1', false);
set role authenticated;
begin;
select public.sync_push('transactions', '{"id":"c4000000-0000-0000-0000-000000000001","business_id":"c0000000-0000-0000-0000-000000000001","type":"expense","voucher_no":"CP/26-27/001","txn_date":"2026-04-02","amount_paise":70000,"payment_method":"cash","account_id":"c1000000-0000-0000-0000-000000000001","category_id":"c2000000-0000-0000-0000-000000000001","party":"A"}', 0);
select pg_sleep(2);
commit;
