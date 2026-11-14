# Online 24/7 Cloud Hosting Guide (₱0 Forever — Para CP Ra Tanan!)

Human nimo ma-deploy online sa cloud server, **pwede na nimo i-off ang imong laptop**. Ikaw, ang ubang partner rental owners, ug ang customers **CP na lang tanan** ang gamiton 24/7!

---

## Option A (Recommended): GitHub + Neon + Render — **₱0 Forever, WALAY Monthly Extend Click!**

Kani nga setup:
- **Walay credit card** nga pangayoon
- **Walay monthly "Run until..." button** nga i-click
- **Dili mawala** ang bookings, partner shops, ug **uploaded bike photos** bisan mo-restart o mo-sleep ang Render (kay naka-save tanan sulod sa **Neon PostgreSQL**, apil na ang bike photos sa `uploaded_media` table!)

### Step 1: Maghimo og Free Database sa **Neon** (2 minutes)
1. Adto sa **[neon.com](https://neon.com)** ug pag-Sign up (pwede Google/GitHub login, libre, walay card).
2. Paghimo og bag-ong project (e.g. `camiguin-rentals`). Choose nearest region like **AWS Singapore (`ap-southeast-1`)**.
3. Sa Dashboard -> **Connect** -> i-copy ang **`Connection string`** (nagsugod sa `postgresql://...` ug naay `?sslmode=require`). *Tipigi ni kay i-paste nimo sa Render unya.*

### Step 2: I-upload ang Code sa **GitHub** (2 minutes)
1. Pag-Sign in / Sign up sa **[github.com](https://github.com)**.
2. Click **New repository** -> panganli og `motorbike-rentals-camiguin` -> Create repository.
3. I-upload tanan sulod sa folder `C:\Users\acer\.gemini\antigravity\scratch\motorbike-rental-pwa` *(ayaw i-apil ang `motoride.db` ug `__pycache__`)*:
   - **Option 1 (PowerShell `git`):**
     ```powershell
     cd C:\Users\acer\.gemini\antigravity\scratch\motorbike-rental-pwa
     git init
     git add .
     git commit -m "Centralized Motorbike Rentals Camiguin"
     git branch -M main
     git remote add origin https://github.com/<IMONG-GITHUB-USERNAME>/motorbike-rentals-camiguin.git
     git push -u origin main
     ```
   - **Option 2 (GitHub Website Drag-and-Drop):** Sa bag-ong repo page sa browser, click **"uploading an existing file"**, i-drag ang mga files ug folders gikan sa clean unzipped copy sa `motorbike-rental-pwa-cloud.zip` (para walay `motoride.db` o `__pycache__`), unya **Commit changes**.

### Step 3: I-deploy Libre sa **Render** (3 minutes)
1. Adto sa **[render.com](https://render.com)** ug **Sign in with GitHub** (libre, walay card).
2. Click **New +** -> **Web Service** -> pili-a ang imong `motorbike-rentals-camiguin` GitHub repository.
3. I-check / i-set ang settings (automatic ni mabasa kung naay `render.yaml`, or i-type manual):
   - **Plan:** `Free` (`$0/month`)
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 wsgi:app`
4. Ubos sa **Environment Variables**, click **Add Environment Variable**:
   - **`DATABASE_URL`** = *(i-paste diri ang `postgresql://...` string gikan sa Neon!)*
   - **`SECRET_KEY`** = *(pag-type og bisan unsa nga taas nga random letters/numbers, e.g. 40+ characters)*
   - **`ADMIN_PASSWORD`** *(optional)* = password nga gusto nimo para sa Main Admin *(kon wala, default kay `admin1234`)*
5. Click **Create Web Service** ug hulata ~2–3 minutes hangtod mag-**Live**!
6. I-test sa browser:
   - `https://<imong-app>.onrender.com/api/health` *(angay mo-pakita og `"backend": "postgresql"`!)*
   - Storefront: `https://<imong-app>.onrender.com`
   - Partner Portal: `https://<imong-app>.onrender.com/partner`
   - Main Admin: `https://<imong-app>.onrender.com/admin`

*(Reminder sa Render Free Tier: mo-sleep ang app kung walay bisita sulod sa 15 minutes, mao nga ang pinaka-unang mo-open inig mata mahimong maghulat og ~30–50 seconds; pero **100% libre forever, walay bayad, ug walay monthly extend button**, ug safe tanan data sa Neon!)*

---

## Option B: PythonAnywhere (Free Beginner Tier — 1x Monthly Free Extend Click)

Kung **PythonAnywhere** gihapon imong gamiton:
- **₱0 gihapon siya forever** ug **walay bayad after 1 month**. Ang "1 month" kay libre lang nga renewal button (**"Run until..."** sa **Web** tab) nga i-click **1x a month** sa CP browser.
- Setup commands sa Bash console:
  ```bash
  mkdir -p ~/motorbike-rental-pwa
  unzip -o ~/motorbike-rental-pwa-cloud.zip -d ~/motorbike-rental-pwa
  cd ~/motorbike-rental-pwa
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```
- Web tab: **Manual configuration** -> **Python 3.13** -> Source code `/home/<username>/motorbike-rental-pwa` -> Virtualenv `/home/<username>/motorbike-rental-pwa/venv` -> WSGI file (`from wsgi import application`) -> **Reload**.

---

## Pag-convert ngadto sa Android APK (Optional)

Kung naa na kay live **`https://...`** URL (gikan sa Render o PythonAnywhere):
1. Bisitaha ang **pwabuilder.com** ug i-paste ang imong live `https://` URL.
2. I-click ang **Package for Stores -> Android** aron ma-download ang imong signed **`.apk` / `.aab`** file!
