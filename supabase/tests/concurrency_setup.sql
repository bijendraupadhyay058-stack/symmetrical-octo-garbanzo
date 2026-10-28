-- Fresh business with ₹1,000 cash for the concurrent-withdrawal test.
insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000000c1', 'c@example.com') on conflict do nothing;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000c1', false);
set role authenticated;
select public.sync_push('business_profiles', '{"id":"c0000000-0000-0000-0000-000000000001","name":"C","settings":{}}', 0);
select public.sync_push('accounts', '{"id":"c1000000-0000-0000-0000-000000000001","business_id":"c0000000-0000-0000-0000-000000000001","name":"Cash","kind":"cash"}', 0);
select public.sync_push('accounts', '{"id":"c1000000-0000-0000-0000-000000000002","business_id":"c0000000-0000-0000-0000-000000000001","name":"Bank","kind":"bank"}', 0);
select public.sync_push('categories', '{"id":"c2000000-0000-0000-0000-000000000001","business_id":"c0000000-0000-0000-0000-000000000001","kind":"expense","name":"Rent"}', 0);
select public.sync_push('opening_balances', '{"id":"c3000000-0000-0000-0000-000000000001","business_id":"c0000000-0000-0000-0000-000000000001","account_id":"c1000000-0000-0000-0000-000000000001","as_of_date":"2026-04-01","amount_paise":100000,"reason":""}', 0);
