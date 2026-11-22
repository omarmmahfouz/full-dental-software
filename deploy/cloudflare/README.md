# The online demo (Cloudflare + Supabase)

A copy of the system on the internet, **with the sample data only**, for a client to try. It is not for real
patients: the clinic itself keeps its own server (see `docs/deployment.md`).

| Part | Where |
|---|---|
| The system (one container) | Cloudflare Workers + Containers, Western Europe (`wrangler.jsonc`) |
| The data | Supabase project **cia-dental-demo** (Frankfurt), login `dental_demo`, schema `dental` |
| The address | `https://cia-dental-demo.<your-workers-subdomain>.workers.dev` (HTTPS) |

How it behaves:
- The container **sleeps after 2 hours** without a page and wakes at the next one: a "The system is starting" page
  shows for a few seconds, then the page opens by itself.
- The **first start** fills the sample data (all the logins of the trial, with the password you set as
  `DEMO_PASSWORD`). It takes a few minutes; the starting page waits.
- The data (patients, visits, bills...) is in Supabase and is **kept**. Photos and files uploaded during the test are
  on the container's own disk and are **lost when it sleeps**.
- No nightly backup and no 07:00 reminders run here (they are the clinic server's jobs).
- Each login works on one device at a time: give each tester a different login.

Cost: Cloudflare's **Workers Paid** plan ($5 a month) is needed for Containers; a few hours of testing a day stay
within, or a little over, what it includes. Supabase's free plan is enough; a free project that is not used for a
week is paused (open it again from the Supabase dashboard).

## Put it online (from a PC with Node.js 20+ and Docker Desktop running)

```bash
cd deploy/cloudflare
npm install
npx wrangler login
npx wrangler deploy
```

Then the three secrets (each command asks for the value; nothing is shown on the screen):

```bash
npx wrangler secret put DJANGO_SECRET_KEY
```
Any long random text (50 letters and digits or more).

```bash
npx wrangler secret put DB_PASSWORD
```
The password of the Supabase login `dental_demo`. To choose one: Supabase dashboard → the project
**cia-dental-demo** → *SQL Editor* → `ALTER ROLE dental_demo WITH PASSWORD 'the-new-password';` → *Run*.

```bash
npx wrangler secret put DEMO_PASSWORD
```
The password of every sample login (owner, secretary, dentist1...) on the first start.

Open the address that `wrangler deploy` printed. The first time, wait on the starting page for a few minutes.

## Change or remove it

- **A new version of the system**: `npx wrangler deploy` again. The running container is replaced; the data is kept and
  the database changes run by themselves.
- **Start again with fresh sample data**: in Supabase's *SQL Editor* run
  `DROP SCHEMA dental CASCADE; CREATE SCHEMA dental; GRANT USAGE, CREATE ON SCHEMA dental TO dental_demo;`,
  then `npx wrangler deploy` (the next start fills it again).
- **Take it off the internet**: `npx wrangler delete`, and delete the Supabase project if it is no longer needed.

## Notes for whoever changes it

- `src/index.js` is the Worker: one Durable Object (`DentalApp`, name `main`) starts the container with the Worker's
  vars and secrets as its environment, keeps it awake for `IDLE_MS`, forwards each request with the original host,
  `X-Forwarded-Proto: https` and the visitor's address (`X-Real-IP` from `CF-Connecting-IP`), and answers with the
  starting page while the port does not answer yet.
- `start.sh` → `demo_setup.py host` picks the Supabase pooler address of `DB_HOSTS` that accepts the login (a
  project is on one of the two), `migrate`, then `demo_setup.py fill` on an empty database (`setup_clinic` and
  `load_demo_data` in one transaction, so a stopped start leaves it empty, not half full), else `setup_clinic` in the
  background, then gunicorn on port 8000.
- `Dockerfile` takes `--build-arg BASE_IMAGE=…` (a mirror when Docker Hub limits downloads) and an optional build
  secret `ca` (a network that inspects HTTPS); neither is kept in the image.
- The settings that differ from the clinic server are the `vars` of `wrangler.jsonc`: `ALLOWED_NETWORKS=*` (the
  logins and passwords still apply), `DJANGO_HTTPS=1` without its redirect (Cloudflare is the HTTPS part), and
  `TRUSTED_PROXIES` for every address (only the Worker reaches the container).
