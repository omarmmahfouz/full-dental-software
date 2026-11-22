# The online demo (Koyeb or Cloudflare, with Supabase)

A copy of the system on the internet, **with the sample data only**, for a client to try from anywhere. It is not for
real patients: the clinic keeps its own server (see `docs/deployment.md`).

| Part | Where |
|---|---|
| The system | One container built from `deploy/online/Dockerfile`: **Koyeb** (free) or **Cloudflare** ($5 a month) |
| The data | Supabase project **cia-dental-demo** (Frankfurt), login `dental_demo`, schema `dental` |

| | Koyeb free | Cloudflare |
|---|---|---|
| Cost | Free (Koyeb asks for a bank card) | Workers Paid plan, $5 a month |
| Sleeps after | 1 hour without a page | 2 hours without a page |
| Speed | a tenth of a processor: most pages 1 to 2 seconds, the owner's home page sometimes 8 | a quarter of a processor |
| Address | `https://<service>-<your-name>.koyeb.app` | `https://cia-dental-demo.<your-name>.workers.dev` |

How it behaves, on both:
- When it wakes, a **"The system is starting"** page shows, then the page opens by itself (on Koyeb's free
  server in about a minute; on Cloudflare in seconds).
- The **first start** fills the sample data: every login of the trial (owner, secretary, dentist1...) with the password
  you set as `DEMO_PASSWORD`. On Koyeb's free server this takes 10 to 15 minutes, once; the starting page waits.
- The data (patients, visits, bills...) is in Supabase and is **kept**. Photos and files uploaded during the test are
  on the server's own disk and are **lost when it sleeps**.
- No nightly backup and no 07:00 reminders run here (they are the clinic server's jobs).
- Each login works on one device at a time: give each tester a different login.
- A free Supabase project that is not used for a week is paused: open it again from the Supabase dashboard.

## Step 1 (once): the database password

Supabase dashboard → the project **cia-dental-demo** → **SQL Editor** → write (with your own password) and press
**Run**:

```sql
ALTER ROLE dental_demo WITH PASSWORD 'write-your-password-here';
```

Use letters and digits, 16 or more. You type the same password as `DB_PASSWORD` below.

## Step 2, the free way: Koyeb

1. Sign up at koyeb.com.
2. **Create Web Service** → **GitHub**. In **Public GitHub repository** paste
   `https://github.com/omarmmahfouz/full-dental-software` and choose the branch **claude/great-lovelace-d3pekf**.
3. **Builder**: choose **Dockerfile**. **Dockerfile location**: `deploy/online/Dockerfile`. Leave the work directory
   empty (the whole project is needed).
4. **Instance**: **Free**. **Region**: **Frankfurt** (next to the database: every page asks it many times).
5. **Environment variables**: add two, each as a **Secret**:
   - `DB_PASSWORD` = the password of step 1;
   - `DEMO_PASSWORD` = the password your client will use for every login.
6. **Ports**: `8000`, HTTP, path `/`. Leave the health check as it is (TCP on 8000).
7. Name the service (e.g. `cia-dental-demo`) and press **Deploy**.
8. Wait for the build (a few minutes), then open the address Koyeb shows. The first time the starting page stays 10 to 15
   minutes, then the login page opens: `owner` with your `DEMO_PASSWORD`.

A new version of the system: Koyeb builds again by itself when the branch changes (or press **Redeploy**).

## Step 2, the other way: Cloudflare ($5 a month)

Needs the **Workers Paid** plan, and a PC with Node.js 20+ and Docker Desktop running:

```bash
cd deploy/online/cloudflare
npm install
npx wrangler login
npx wrangler deploy
```

Then the two passwords (each command asks for the value; nothing is shown on the screen):

```bash
npx wrangler secret put DB_PASSWORD
```

```bash
npx wrangler secret put DEMO_PASSWORD
```

Open the address that `wrangler deploy` printed. A new version: `npx wrangler deploy` again.

## Start again or take it off

- **Fresh sample data**: in Supabase's SQL Editor run
  `DROP SCHEMA dental CASCADE; CREATE SCHEMA dental; GRANT USAGE, CREATE ON SCHEMA dental TO dental_demo;`,
  then **Redeploy** (Koyeb) or `npx wrangler deploy` (Cloudflare): the next start fills it again.
- **Take it off the internet**: delete the Koyeb service (or `npx wrangler delete`), and the Supabase project if it is
  no longer needed.

## Notes for whoever changes it

- `start.sh` gives the demo's settings when the host does not: Postgres on the Supabase pooler (`DB_USER`
  `dental_demo.<project>`, `DB_HOSTS` = the two Frankfurt pooler addresses, a project answers on one), HTTPS without
  its redirect (the host is the HTTPS part), `ALLOWED_NETWORKS=*` (the logins still apply), `TRUSTED_PROXIES` for every
  address, `DJANGO_CSRF_TRUSTED_ORIGINS` for `*.koyeb.app`, `*.workers.dev` and `*.onrender.com`, `PORT` 8000. Only
  `DB_PASSWORD` and `DEMO_PASSWORD` must be set; without `DJANGO_SECRET_KEY` the key is made from `DB_PASSWORD`, so it
  is the same at every start and the logins stay open after a sleep.
- Order: `demo_setup.py wait-page` answers 503 "starting" on `$PORT` at once (the host's health check passes during a
  long first start) → `demo_setup.py prepare` (one start of Django: the pooler address, `migrate`, then on an empty
  database `setup_clinic` + `load_demo_data` in one transaction, so a stopped start leaves it empty, not half full;
  after an update with new migrations `setup_clinic`) → the starting page stops and gunicorn takes the port
  (`--preload`, 1 worker × 8 threads by default). Measured with a tenth of a processor and 512 MB: the first start
  11 minutes, a wake-up 51 s, 115 MB of memory.
- `cloudflare/`: `src/index.js` is the Worker. One Durable Object (`DentalApp`, name `main`) starts the container with
  the Worker's vars and secrets, keeps it awake for `IDLE_MS`, forwards each request with the original host,
  `X-Forwarded-Proto: https` and the visitor's address (`X-Real-IP` from `CF-Connecting-IP`), and shows its own
  starting page while the port does not answer. `wrangler.jsonc` keeps the container in Western Europe (`WEUR`).
- `Dockerfile` takes `--build-arg BASE_IMAGE=…` (a mirror when Docker Hub limits downloads).
