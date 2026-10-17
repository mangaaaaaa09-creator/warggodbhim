FF GLORY HELLO BOT — setup

1) Install Python 3.10+.
2) In this folder run: pip install -r requirements.txt
3) Set a stable secret before starting the server:
   Linux/macOS: export SECRET_KEY='use-a-long-random-secret-here'
   Windows PowerShell: $env:SECRET_KEY='use-a-long-random-secret-here'
4) Start: python app.py
5) Open http://127.0.0.1:5000/login

The site includes account registration/login, account-scoped projects, a Clan ID confirmation dialog, and a change-password form. Project data is stored under data/ and users in data/users.json. Keep the server and these files on the same host to access the same projects from another phone.

Note: XP/level/games display only when the underlying bot/account source provides those values. 24/7 uptime is not guaranteed.

UI refresh (October 2026)
- Dashboard template: templates/dashboard.html
- Sign-in/register template: templates/login.html
- Responsive theme and mobile bottom navigation: static/css/style.css
- Dashboard interactions, job status refresh, and error modals: static/js/dashboard.js
- Redeem codes and payment methods are intentionally marked as coming soon; current access is free.
- The dashboard uses the existing Flask API routes; no new backend endpoints are required.

Privacy note: account credentials and runtime user/job/device records from the supplied archive were not included in this distributable. Start with fresh local data files.

UI refresh (reference-matched)
- Mobile-first Teams dashboard inspired by the supplied FFGloryBot screenshot: templates/dashboard.html
- Sign-in page with Wargood Top 1 Telegram promo/link: https://t.me/wargood_officiel
- Responsive styles: static/css/style.css
- Teams/activity/payment interactions and existing Flask API wiring: static/js/dashboard.js
- Payment methods and coupon redemption are marked coming soon; standard service access is free for now.
- Premium selection is displayed as coming soon and does not trigger a payment.
- The distributable has empty account/runtime JSON files; create a fresh account after starting the app.
