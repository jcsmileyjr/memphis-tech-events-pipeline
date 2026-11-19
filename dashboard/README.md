# Memphis Events dashboard

A local Next.js dashboard that reads from the read-only stats API and answers four
questions about Memphis tech event data. Design notes: [`../docs/dashboard-design.md`](../docs/dashboard-design.md).

## Run it

1. **Start the API** (from the project root, the folder that contains `api/`), with the
   `API_DB_*` settings filled in `.env`:

   ```bash
   ./Scripts/python.exe -m uvicorn api.main:app
   ```

   Check `http://localhost:8000/health` returns `{"status":"ok", ...}`.

2. **Configure the dashboard** (first time only):

   ```bash
   cd dashboard
   cp .env.example .env.local
   npm install
   ```

   `API_BASE_URL` defaults to `http://localhost:8000`; change it in `.env.local` if the API
   runs elsewhere.

3. **Start the dashboard:**

   ```bash
   npm run dev
   ```

4. **Open** `http://localhost:3000`.

Production build: `npm run build` then `npm start` (also on port 3000).

## Checks

```bash
npx tsc --noEmit   # type check
npm run lint
npm run build
```
