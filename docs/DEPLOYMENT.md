# Installation & Deployment Guide

This guide takes you from source code to the app installed on your Android phone at `https://fintaxprojsr.in`.

## 1. Create the project

Requirements: **Node.js 20.9+** (22 LTS recommended), npm, Git, a free [Supabase](https://supabase.com) account and a free [Vercel](https://vercel.com) account.

```bash
git clone <this repository>
cd symmetrical-octo-garbanzo
npm install
```

## 2. Set up the database and authentication (Supabase)

1. In Supabase, **New project** → choose the **Mumbai (ap-south-1)** region → set a strong database password (store it in a password manager).
2. Open **SQL Editor** and run the three files in `supabase/migrations/` **in order**:
   1. `20261028000001_schema.sql` – tables
   2. `20261028000002_rules_and_security.sql` – accounting rules, audit triggers, Row Level Security
   3. `20261028000003_sync_and_storage.sql` – sync function and the private `attachments` storage bucket

   *Alternative with the Supabase CLI:* `npx supabase link --project-ref <ref>` then `npx supabase db push`.
3. **Authentication → Providers → Email**: keep Email enabled. Recommended: *Confirm email* ON, minimum password length 8.
4. **Authentication → URL Configuration**:
   - Site URL: `https://fintaxprojsr.in`
   - Redirect URLs: `https://fintaxprojsr.in/**`, `http://localhost:3000/**` (and your `*.vercel.app` preview URL if you use it)
5. **Authentication → Sessions** (optional): set an inactivity timeout (e.g. 7 days). The app additionally locks itself after the minutes you choose in *Settings → Security*.
6. **Storage**: confirm a bucket named `attachments` exists and is **not public** (the migration creates it).
7. Single-owner setup: after you create your own account (step 4 below), you may turn **off** “Allow new users to sign up” under *Authentication → Providers → Email* so nobody else can register.

## 3. Configure environment variables

Copy `.env.example` to `.env.local` and fill in values from **Supabase → Project Settings → API**:

```
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key>
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_ALLOW_LOCAL_MODE=false
```

> **Never** put the `service_role` key in this project, in any `NEXT_PUBLIC_` variable or in Vercel. The app does not need it – all access goes through Row Level Security with the public anon key.

## 4. Run locally

```bash
npm run dev        # http://localhost:3000
```

Open the app, choose **Create account**, enter your business name, email and password. The first sign-in creates your business, default Cash / Bank / UPI accounts and the standard income and expense categories. Then go to **Settings → Accounts & Opening Balances** and enter the opening cash and bank balances.

## 5. Test the application

```bash
npm run typecheck
npm test                 # accounting, sync, reports, exports, backup
npm run test:db          # migrations + RLS/rules on a temporary PostgreSQL (needs PostgreSQL 15+ server binaries)
npm run build && npm run test:e2e   # Playwright: Pixel 7 + desktop
```

Then follow the manual checklist in [TESTING.md](TESTING.md) on your phone.

## 6. Deploy to Vercel

1. Push the repository to GitHub.
2. Vercel → **Add New → Project** → import the repository. Framework preset: **Next.js** (auto-detected). Build command `npm run build`, output default.
3. **Environment Variables** (Production and Preview):
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `NEXT_PUBLIC_SITE_URL` = `https://fintaxprojsr.in`
   - `NEXT_PUBLIC_ALLOW_LOCAL_MODE` = `false`
4. **Deploy**. Every push to the main branch deploys automatically.

## 7. Connect the custom domain `fintaxprojsr.in`

1. Vercel project → **Settings → Domains** → add `fintaxprojsr.in` and `www.fintaxprojsr.in` (set `www` to redirect to the apex).
2. At your domain registrar's DNS panel add the records Vercel shows, typically:
   - `A` record, host `@` → `76.76.21.21`
   - `CNAME` record, host `www` → `cname.vercel-dns.com`
3. Wait for Vercel to show **Valid Configuration** (minutes to a few hours).
4. Update Supabase **Site URL / Redirect URLs** (step 2.4) to the final domain.

## 8. HTTPS

Vercel issues and renews a free TLS certificate automatically once DNS is valid; HTTP requests are redirected to HTTPS. The app also sends `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and a strict referrer policy (see `next.config.ts`). Service workers, the install prompt, biometric unlock and the share sheet all require HTTPS – they work on `localhost` for development only.

## 9. Install the PWA on Android (Chrome)

1. Open `https://fintaxprojsr.in` in **Google Chrome** and sign in.
2. Chrome shows **“Install app”** (or ⋮ menu → **Add to Home screen / Install app**). You can also use *Settings → Install app on this device* inside CashBook.
3. The **CashBook** icon appears on the home screen and opens full-screen with the navy splash screen. Long-press the icon for shortcuts (Add Income, Add Expense, Cash Book).
4. Open each main screen once while online; after that the app opens and records entries offline. The header badge shows **Offline · n pending** until the phone reconnects and uploads.
5. Optional: *Settings → Security → Enable fingerprint unlock*.

## 10. Updating the app without losing data

- All business data lives in the **Supabase database** and, on each device, in **IndexedDB**. Deploying a new version never touches either.
- Each build generates a new versioned service worker (`scripts/build-sw.mjs`). Installed apps detect it and show **“A new version is ready – Update”**; the page reloads only when you tap it, so a half-filled form is never lost.
- Entries not yet uploaded remain on the device across updates, restarts and sign-outs, and upload on the next sync.
- **Database changes**: add a *new* numbered file in `supabase/migrations/` (never edit an applied one) and run it in the SQL editor / `supabase db push` *before* deploying code that depends on it. Use additive changes (new nullable columns, new tables).
- **Backups**: Supabase keeps daily backups (Pro plan adds point-in-time recovery). In addition, download a manual backup from *Settings → Backup & Restore* monthly and store it in Google Drive. The app also keeps 4 weekly snapshots on the device.

## Device-only mode (optional)

If `NEXT_PUBLIC_SUPABASE_URL` is not set (or `NEXT_PUBLIC_ALLOW_LOCAL_MODE=true`), the sign-in screen offers **This device** mode: data stays only in that browser with an app password, no cloud sync. Use regular backups in this mode.

## Adding staff users later

The schema already supports it: add a row to `business_members` with role `accountant` (can add/edit) or `viewer` (read-only) for the staff member's `auth.users` id, e.g. from the SQL editor:

```sql
insert into public.business_members (business_id, user_id, role)
values ('<your business id>', '<staff user id>', 'accountant');
```

(The business id is shown in `public.business_profiles`.) The staff member signs in with their own account and sees the shared books; all changes are audited with their user id.
