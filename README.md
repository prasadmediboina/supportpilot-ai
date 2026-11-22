# SupportPilot AI backend (FastAPI)

## Run locally
    python -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env     # then edit it; load it with: export $(grep -v '^#' .env | xargs)
    uvicorn main:app --reload
Open http://localhost:8000/docs to try every endpoint.

## Deploy on Render
New Web Service -> build `pip install -r requirements.txt` -> start `uvicorn main:app --host 0.0.0.0 --port $PORT`.
Add a Render PostgreSQL database and set DATABASE_URL, JWT_SECRET, FRONTEND_ORIGIN, ADMIN_EMAILS, UPI_ID.

## Payments
Customers scan a UPI QR that pays your UPI_ID, then submit the 12-digit UTR. You approve it at
POST /admin/payments/{id}/approve after checking your bank app. Plans last 30 days, then fall back to free.
For automatic confirmation, switch to Razorpay or Cashfree.

## Before real customers
Add rate limiting on /public/chat and /auth/*, send reset links by email (see /auth/forgot), use HTTPS only,
and keep JWT_SECRET private.

## Website
The backend also serves the website (static/index.html) and the chat widget (static/widget.js),
so one Render service is the whole product. Open http://localhost:8000 after starting it.
If you host the site elsewhere (e.g. Vercel), set window.API_URL near the top of index.html to your API address
and set FRONTEND_ORIGIN to your site address.

## First-time setup checklist
1. Set ADMIN_EMAILS to your email, then register with that email. An Admin tab appears for confirming payments.
2. Set UPI_ID to your real UPI ID so the QR code works.
3. Set SITE_URL to your live address. Password reset links are printed in the server logs until you add email sending.
