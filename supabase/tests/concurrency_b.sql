-- Device B: ₹700 cash-to-bank contra at the same time. Must be refused.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000c1', false);
set role authenticated;
select public.sync_push('transactions', '{"id":"c4000000-0000-0000-0000-000000000002","business_id":"c0000000-0000-0000-0000-000000000001","type":"contra","voucher_no":"CT/26-27/001","txn_date":"2026-04-02","amount_paise":70000,"payment_method":"other","account_id":"c1000000-0000-0000-0000-000000000001","to_account_id":"c1000000-0000-0000-0000-000000000002"}', 0);
