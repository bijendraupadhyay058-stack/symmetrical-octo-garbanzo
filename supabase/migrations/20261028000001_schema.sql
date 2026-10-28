-- FIN TAX PRO – CashBook: core schema
-- Money is stored as BIGINT paise (1 rupee = 100 paise). Dates are calendar
-- dates in Asia/Kolkata. Rows are never hard-deleted: financial records are
-- cancelled, masters are deactivated.

create extension if not exists pgcrypto;

-- Every write gets a monotonically increasing sequence number used by
-- device synchronisation ("give me everything after N").
create sequence if not exists public.sync_seq;

-- --------------------------------------------------------------- businesses
create table public.business_profiles (
  id uuid primary key,
  business_id uuid generated always as (id) stored,
  owner_id uuid not null references auth.users (id),
  name text not null check (length(trim(name)) > 0),
  tagline text not null default '',
  address text not null default '',
  phone text not null default '',
  email text not null default '',
  gstin text not null default '',
  pan text not null default '',
  logo_data_url text check (logo_data_url is null or length(logo_data_url) < 400000),
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);

-- Membership table keeps the design ready for staff users later.
create table public.business_members (
  business_id uuid not null references public.business_profiles (id),
  user_id uuid not null references auth.users (id),
  role text not null check (role in ('owner', 'accountant', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (business_id, user_id)
);

-- ----------------------------------------------------------------- masters
create table public.accounts (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  name text not null check (length(trim(name)) > 0),
  kind text not null check (kind in ('cash', 'bank', 'upi')),
  details text not null default '',
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);

create table public.opening_balances (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  account_id uuid not null,
  as_of_date date not null,
  amount_paise bigint not null,
  reason text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);

-- Income and expense categories share one table, distinguished by kind.
create table public.categories (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  kind text not null check (kind in ('income', 'expense')),
  name text not null check (length(trim(name)) > 0),
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);
create unique index categories_unique_name on public.categories (business_id, kind, lower(name));

create table public.clients (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  code text not null,
  name text not null check (length(trim(name)) > 0),
  firm_name text not null default '',
  mobile text not null default '',
  email text not null default '',
  gstin text not null default '',
  pan text not null default '',
  service_type text not null default '',
  notes text not null default '',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);
create index clients_business on public.clients (business_id);

-- ------------------------------------------------------------ transactions
create table public.transactions (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  type text not null check (type in ('income', 'expense', 'contra')),
  voucher_no text not null,
  txn_date date not null,
  amount_paise bigint not null check (amount_paise > 0),
  payment_method text not null check (payment_method in ('cash', 'upi', 'bank_transfer', 'neft_rtgs', 'cheque', 'other')),
  account_id uuid not null,
  to_account_id uuid,
  category_id uuid,
  client_id uuid,
  party text not null default '',
  service text not null default '',
  narration text not null default '',
  reference_no text not null default '',
  status text not null default 'active' check (status in ('active', 'cancelled')),
  cancel_reason text not null default '',
  cancelled_at timestamptz,
  recurring_template_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq'),
  constraint contra_shape check (
    (type = 'contra' and to_account_id is not null and to_account_id <> account_id and category_id is null and client_id is null)
    or (type <> 'contra' and to_account_id is null and category_id is not null)
  ),
  constraint cancel_reason_required check (status = 'active' or length(trim(cancel_reason)) > 0)
);
create unique index transactions_voucher_unique on public.transactions (business_id, voucher_no);
create index transactions_business_date on public.transactions (business_id, txn_date);
create index transactions_client on public.transactions (client_id);

create table public.fee_bills (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  bill_no text not null,
  bill_date date not null,
  due_date date,
  client_id uuid not null,
  category_id uuid,
  service text not null default '',
  amount_paise bigint not null check (amount_paise > 0),
  narration text not null default '',
  status text not null default 'active' check (status in ('active', 'cancelled')),
  cancel_reason text not null default '',
  last_reminded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);
create unique index fee_bills_no_unique on public.fee_bills (business_id, bill_no);

-- Links a receipt (income transaction) to the bill(s) it settles.
-- amount 0 means the link was removed (rows are never deleted).
create table public.fee_allocations (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  fee_bill_id uuid not null,
  transaction_id uuid not null,
  amount_paise bigint not null check (amount_paise >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);
create unique index fee_allocations_unique on public.fee_allocations (transaction_id, fee_bill_id);

create table public.recurring_templates (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  name text not null,
  party text not null default '',
  category_id uuid,
  amount_paise bigint not null check (amount_paise > 0),
  payment_method text not null,
  account_id uuid not null,
  narration text not null default '',
  day_of_month integer not null check (day_of_month between 1 and 31),
  next_due_date date not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);


create table public.attachments (
  id uuid primary key,
  business_id uuid not null references public.business_profiles (id),
  transaction_id uuid not null,
  file_name text not null,
  mime_type text not null check (mime_type in ('image/jpeg', 'image/png', 'image/webp', 'application/pdf')),
  size_bytes integer not null check (size_bytes between 1 and 5242880),
  storage_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);

-- Audit trail. source = 'app' rows are written by the app (including edits
-- made offline); source = 'db' rows are written by database triggers and
-- cannot be forged by clients.
create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.business_profiles (id),
  entity text not null,
  entity_id uuid not null,
  action text not null,
  summary text not null default '',
  before_data jsonb,
  after_data jsonb,
  source text not null default 'app' check (source in ('app', 'db')),
  actor_id uuid default auth.uid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1,
  sync_seq bigint not null default nextval('public.sync_seq')
);
create index audit_logs_entity on public.audit_logs (business_id, entity_id);

-- -------------------------------------------------- same-business references
-- Composite foreign keys guarantee that a row can only reference accounts,
-- categories, clients, bills and entries of its OWN business (a plain
-- foreign key would accept another business's id).
alter table public.accounts add constraint accounts_id_business unique (id, business_id);
alter table public.categories add constraint categories_id_business unique (id, business_id);
alter table public.clients add constraint clients_id_business unique (id, business_id);
alter table public.transactions add constraint transactions_id_business unique (id, business_id);
alter table public.fee_bills add constraint fee_bills_id_business unique (id, business_id);
alter table public.recurring_templates add constraint recurring_templates_id_business unique (id, business_id);

alter table public.opening_balances
  add constraint opening_balances_account_fk foreign key (account_id, business_id) references public.accounts (id, business_id);
alter table public.transactions
  add constraint transactions_account_fk foreign key (account_id, business_id) references public.accounts (id, business_id),
  add constraint transactions_to_account_fk foreign key (to_account_id, business_id) references public.accounts (id, business_id),
  add constraint transactions_category_fk foreign key (category_id, business_id) references public.categories (id, business_id),
  add constraint transactions_client_fk foreign key (client_id, business_id) references public.clients (id, business_id),
  add constraint transactions_template_fk foreign key (recurring_template_id, business_id) references public.recurring_templates (id, business_id);
alter table public.fee_bills
  add constraint fee_bills_client_fk foreign key (client_id, business_id) references public.clients (id, business_id),
  add constraint fee_bills_category_fk foreign key (category_id, business_id) references public.categories (id, business_id);
alter table public.fee_allocations
  add constraint fee_allocations_bill_fk foreign key (fee_bill_id, business_id) references public.fee_bills (id, business_id),
  add constraint fee_allocations_txn_fk foreign key (transaction_id, business_id) references public.transactions (id, business_id);
alter table public.recurring_templates
  add constraint recurring_templates_account_fk foreign key (account_id, business_id) references public.accounts (id, business_id),
  add constraint recurring_templates_category_fk foreign key (category_id, business_id) references public.categories (id, business_id);
alter table public.attachments
  add constraint attachments_txn_fk foreign key (transaction_id, business_id) references public.transactions (id, business_id);
