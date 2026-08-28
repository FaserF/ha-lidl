<div align="center">
  <h1>Lidl Weekly Offers (for Home Assistant) 🛒</h1>
  <p><strong>A secure, robust Home Assistant integration that fetches weekly offers, discounts, upcoming deal previews, coupons, and digital receipts for your local Lidl store directly from the official Lidl Plus API.</strong></p>

  [![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)
  [![Downloads (Current release)](https://img.shields.io/github/downloads/FaserF/ha-lidl/latest/lidl.zip?label=Downloads%20(Current%20release)&style=for-the-badge)](https://github.com/FaserF/ha-lidl/releases)
  [![GitHub Release](https://img.shields.io/github/v/release/FaserF/ha-lidl?style=for-the-badge)](https://github.com/FaserF/ha-lidl/releases)
  [![License](https://img.shields.io/github/license/FaserF/ha-lidl?style=for-the-badge)](LICENSE)
</div>

---

## 🧭 Quick Links

| | | | |
| :--- | :--- | :--- | :--- |
| [✨ Features](#-features) | [📦 Installation](#-installation) | [⚙️ Configuration](#-configuration) | [🔐 Lidl Plus Login](#-lidl-plus-login-optional) |
| [🛠️ Options](#-options-flow) | [🧑‍💻 Development](#-development) | [📄 License](#-license) | |

### Why use this integration?
Instead of scraping brittle public HTML pages (which constantly break) or using heavy headless browser setups, this integration connects directly to Lidl's official mobile app backend endpoints. By utilizing `curl_cffi` for advanced TLS fingerprinted client impersonation, it retrieves structured weekly store brochures and discount offers in real-time.

---

### 🛒 Supermarket Family & Deals Hub

Check out our full collection of Home Assistant supermarket integrations and the multi-store aggregator:

| Repository | Description |
| :--- | :--- |
| 🏷️ [**Grocery Deals (ha-grocery-deals)**](https://github.com/FaserF/ha-grocery-deals) | **Smart multi-store price comparison hub (aggregates all 5 integrations)** |
| 🔴 [**ha-rewe**](https://github.com/FaserF/ha-rewe) | REWE weekly offers, bonus points, coupons & product filters |
| 🟡 [**ha-edeka**](https://github.com/FaserF/ha-edeka) | EDEKA weekly offers, discounts & PAYBACK card |
| ⚪ [**ha-aldi**](https://github.com/FaserF/ha-aldi) | ALDI Süd & ALDI Nord weekly flyers & brochures |
| 🔴 [**ha-norma**](https://github.com/FaserF/ha-norma) | Norma weekly store discounts & flyer offers |

---

It groups all sensors under a single market device and implements advanced lock-serialization, random jitter delays, storage caching, and exponential backoffs to keep your setup secure and prevent rate-limiting bans.

---

## ✨ Features

- **🛒 Detailed Offers Sensors**:
  - **Offers**: Current week's discounted items count, with attributes detailing titles, brands, categories, prices (original & discount), packaging units, unit prices, and direct links to product images.
  - **Offers Preview**: Next week's upcoming deals.
- **🔐 Lidl Plus Features** *(requires login)*:
  - **Loyalty Card QR Code Image (`image`)**: A dynamic 300x300 PNG QR Code entity rendering your 17-digit barcode for scanning directly at the checkout. Includes state attributes for your full profile (`user_name`, `email`, `country`, `registration_date`).
  - **Activated & Available Coupons**: Sensors for currently active and available coupons, broken down by store vs. online shop coupons.
  - **Activate All Coupons**: A button entity to activate every available coupon with a single tap.
  - **Last Receipt**: Shows total amount, date, store code, article count, and redeemed coupon counts.
- **📱 Single Lidl Plus Account Device per Country**:
  - All account-level entities (`Loyalty Card QR Code`, `Activated Coupons`, `Available Coupons`, `Last Receipt`, `Activate All Coupons`) are grouped under a dedicated **Lidl Plus Account (DE)** device.
  - Features a direct **Visit Lidl Plus Account** button taking you directly to your web account management portal.
- **🛡️ Rate-Limiting & Anti-Ban Protections**:
  - **First-Fetch Optimisation**: Skips jitter sleep on initial setup so the first refresh completes instantly.
  - **Lock Queueing**: A domain-wide lock ensures concurrent updates run sequentially.
  - **Random Jitter**: Introduces a 5–15 second delay between requests.
  - **Restart-Resistance**: Saves parsed data to Home Assistant's JSON storage cache to survive restarts without hitting the API.
  - **Exponential Backoff**: Backs off for up to 24 hours on 403/429 blocks, and minutes on network failures.
- **⚙️ Store-Based Device Grouping**:
  - Store-specific offer sensors (`Offers`, `Offers Preview`, `Force Update`) are grouped under their respective Lidl Store device.
  - **Visit Lidl Store Button**: The store device registry provides a dynamic configuration URL pointing directly to your local store page.
- **🎛️ Manual Force Update**:
  - A **Force Update** button entity allows manually triggering an API update on demand (disabled by default to avoid accidental triggers).
- **🔍 Diagnostic Downloads**:
  - Full support for Home Assistant UI Diagnostics. Download complete configurations with identifiers and session details automatically redacted.

---

## ❤️ Support This Project

> I maintain this integration in my **free time alongside my regular job**.
>
> **This project is and will always remain 100% free.**
>
> Donations are completely voluntary — but they help me stay motivated and dedicate more time to maintaining open-source tools!

<div align="center">

[![PayPal](https://img.shields.io/badge/Donate%20via-PayPal-%2300457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/FaserF)

</div>

---

## 📦 Installation

### HACS (Recommended)

This integration is fully compatible with [HACS](https://hacs.xyz/).

1. Open HACS in Home Assistant.
2. Click on the three dots in the top right corner and select **Custom repositories**.
3. Add `FaserF/ha-lidl` with category **Integration**.
4. Search for "Lidl Weekly Offers".
5. Install and restart Home Assistant.

[![Open HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FaserF&repository=ha-lidl&category=integration)

### Manual Installation

1. Download the latest release zip file.
2. Extract the `custom_components/lidl` folder into your Home Assistant's `custom_components` directory.
3. Restart Home Assistant.

---

### 🌍 Supported Countries

This integration supports **27 European countries** operating on the Lidl Plus API infrastructure:

| Country | Code | Country | Code | Country | Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 🇦🇹 Austria | `AT` | 🇧🇪 Belgium | `BE` | 🇧🇬 Bulgaria | `BG` |
| 🇨🇭 Switzerland | `CH` | 🇨🇿 Czech Republic | `CZ` | 🇩🇪 Germany | `DE` |
| 🇩🇰 Denmark | `DK` | 🇪🇪 Estonia | `EE` | 🇪🇸 Spain | `ES` |
| 🇫🇮 Finland | `FI` | 🇫🇷 France | `FR` | 🇬🇧 United Kingdom | `GB` |
| 🇬🇷 Greece | `GR` | 🇭🇷 Croatia | `HR` | 🇭🇺 Hungary | `HU` |
| 🇮🇪 Ireland | `IE` | 🇮🇹 Italy | `IT` | 🇱🇹 Lithuania | `LT` |
| 🇱🇺 Luxembourg | `LU` | 🇱🇻 Latvia | `LV` | 🇳🇱 Netherlands | `NL` |
| 🇵🇱 Poland | `PL` | 🇵🇹 Portugal | `PT` | 🇷🇴 Romania | `RO` |
| 🇸🇪 Sweden | `SE` | 🇸🇮 Slovenia | `SI` | 🇸🇰 Slovakia | `SK` |

#### ❌ Unsupported Countries & Technical Reasons

- **🇺🇸 United States (`US`)**: Lidl US operates an entirely independent infrastructure/app system ("myLidl") separate from the European Lidl Plus mobile backend (`tickets.lidlplus.com`). The European API endpoints return HTTP 404 for US requests.
- **🇨🇦 / 🇦🇺 / 🇳🇿 / 🇯🇵 / 🇨🇳 / Non-European countries**: Lidl does not operate stores or Lidl Plus mobile services in these regions.

---

## ⚙️ Configuration

1. Navigate to **Settings > Devices & Services** in Home Assistant.
2. Click **Add Integration** and search for **Lidl Weekly Offers**.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=lidl)

3. Select your country.
4. Enter your ZIP code or city name to search for nearby Lidl stores.
5. *(Optional)* Check **Log in to Lidl Plus** to enable personal features — see below.
6. Select your specific store from the dropdown list.
7. Submit to create the device and entities.

---

## 🔐 Lidl Plus Login *(optional)*

Logging in to your Lidl Plus account enables additional sensors and the coupon activation button. Without a login, only the public weekly offers are available.

---

### 🏗️ How Lidl's Authentication Works

Lidl uses **OAuth 2.0 with PKCE** (Proof Key for Code Exchange), designed exclusively for their mobile app. Key constraints that affect this integration:

| Constraint | Effect |
| :--- | :--- |
| `redirect_uri` is **only** `com.lidlplus.app://callback` | No other redirect URI (including `http://localhost`) is accepted — the auth server returns *"There's been an error, Sorry, something went wrong"* for any other value |
| Login page uses **Cloudflare Turnstile** (anti-bot CAPTCHA) | Headless/automated login is frequently blocked on new accounts or after repeated attempts |
| MFA (2FA) is enforced on many accounts | A verification code sent via SMS/email is required even in headless mode |
| The app deeplink `com.lidlplus.app://` cannot be opened in a desktop browser | After successful login, the browser shows a connection error — the authorization code is embedded in the failed redirect URL |

---

### Option 1: Automatic login *(try this first)*

The integration attempts a **headless login** directly from Home Assistant using your credentials:

1. During setup (or via **Options → Log in to Lidl Plus**), enter your **Lidl Plus email/phone** and **password**.
2. If your account uses **MFA/2FA**, a second step appears asking for the SMS/email verification code.
3. On success, the integration stores a **refresh token** — you will not need to log in again.

**If this fails** with one of the errors below, proceed to Option 2.

---

### Option 2: Browser-based login *(fallback when headless login is blocked)*

When the automatic login is blocked (Captcha, new session detection, or persistent MFA issues), Home Assistant automatically shows you a **login link** and a text field.

#### ⚠️ What happens after MFA — and why "Hoppla!" is expected

After you submit the MFA code, Lidl's server redirects to `com.lidlplus.app://callback?code=XXXX`. A desktop browser cannot open this mobile app deeplink, so the Lidl SPA shows:

> *"Hoppla! Es ist ein Fehler aufgetreten"* / *"This site can't be reached"*

**This is completely expected and correct.** The authorization code is embedded in that failed redirect URL. You capture it via the **DevTools Network tab** — Chrome and Firefox do NOT show `com.lidlplus.app://` URLs in the address bar.

#### Step-by-step instructions

1. **Open DevTools first**: Press **F12** in your browser → go to the **Network** tab → enable **"Preserve log"** (checkbox at the top of the Network tab).
2. **Click the login link** shown in Home Assistant — Lidl’s login page opens.
3. **Log in** with your Lidl Plus email and password.
4. **Enter the MFA code** when prompted and submit it.
5. The browser shows **"Hoppla!"** or a blank page — **this is normal and expected**.
6. **In the Network tab**, search for `com.lidlplus.app` — you will see a failed request with a URL like:
   ```
   com.lidlplus.app://callback?code=XXXXXXXXXXXXXXXXXX&state=...
   ```
7. **Right-click that request → Copy → Copy link address** (or click it and copy "Request URL" from the Headers panel).
8. **Paste the full URL** into the text field in Home Assistant and submit.
9. Home Assistant extracts the code, exchanges it for a token — done.

> 💡 **Alternative: paste just the refresh token**
> If you already have a refresh token (e.g. from the CLI method below), you can paste it directly (minimum 20 characters).

---

### Option 3: Manual token via Terminal *(advanced)*

You can generate and exchange the code yourself without relying on the HA UI. Useful if you run HA on a server without a browser accessible from the same machine.

#### Step 1: Generate PKCE values

In Python (any machine):
```python
import base64, hashlib, secrets

verifier = secrets.token_urlsafe(64)
challenge = (
    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    .decode()
    .rstrip("=")
)
nonce = secrets.token_urlsafe(32)
state = secrets.token_urlsafe(32)
print(f"verifier={verifier}\nchallenge={challenge}\nnonce={nonce}\nstate={state}")
```

#### Step 2: Open the OAuth authorization URL in a browser

Replace `COUNTRY` (e.g. `DE`) and use the generated values:
```
https://accounts.lidl.com/connect/authorize?client_id=LidlPlusNativeClient&redirect_uri=com.lidlplus.app%3A%2F%2Fcallback&response_type=code&scope=openid%20profile%20offline_access%20lpprofile%20lpapis&code_challenge=CHALLENGE&code_challenge_method=S256&Country=COUNTRY&language=LANG-COUNTRY&nonce=NONCE&state=STATE
```

Log in → complete MFA → copy the `com.lidlplus.app://callback?code=XXX` URL from the address bar (see Option 2 Step 4–6).

#### Step 3: Exchange the code for a refresh token

**Windows (PowerShell):**
```powershell
$body = @{
    grant_type    = "authorization_code"
    code          = "PASTE_CODE_HERE"
    redirect_uri  = "com.lidlplus.app://callback"
    code_verifier = "PASTE_VERIFIER_HERE"
}
$headers = @{ Authorization = "Basic TGlkbFBsdXNOYXRpdmVDbGllbnQ6c2VjcmV0" }
(Invoke-RestMethod -Uri "https://accounts.lidl.com/connect/token" -Method Post -Body $body -Headers $headers).refresh_token
```

**macOS / Linux (cURL):**
```bash
curl -s -X POST https://accounts.lidl.com/connect/token \
  -H "Authorization: Basic TGlkbFBsdXNOYXRpdmVDbGllbnQ6c2VjcmV0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=PASTE_CODE_HERE" \
  -d "redirect_uri=com.lidlplus.app://callback" \
  -d "code_verifier=PASTE_VERIFIER_HERE" | python3 -m json.tool
```

Copy the `refresh_token` value and paste it in Home Assistant.

---

### 🔴 Common Errors & Solutions

| Error | Cause | Solution |
| :--- | :--- | :--- |
| *"There's been an error, Sorry, something went wrong"* shown **before login** | The OAuth authorization URL uses a `redirect_uri` that is not `com.lidlplus.app://callback` — Lidl only accepts this exact URI | Make sure you use the link provided by Home Assistant (not a manually constructed URL with a localhost redirect) |
| *"Login flow did not reach callback. Last status: 200"* | Cloudflare/Turnstile CAPTCHA blocked the headless login | Use Option 2 (browser-based login) — HA will show you the link automatically |
| *"invalid_auth"* in HA | Wrong email/password | Double-check credentials on the [Lidl Plus app](https://www.lidl.de/lidl-plus) |
| *"mfa_failed"* | Wrong or expired MFA code | Request a new code and enter it immediately |
| Browser shows error after login but address bar is empty / URL not visible | Browser navigated away from the deeplink URL | Use F12 → Network tab to find the `com.lidlplus.app://` request (see Option 2 tip) |
| *"invalid_token"* when pasting callback URL | Code already used or expired (codes are single-use and expire within ~60 seconds) | Start the login flow again to generate a fresh code |
| Integration loses authentication after some time | Lidl refresh tokens expire after ~30 days of inactivity | Re-login via **Options → Log in to Lidl Plus** |

---


## 🛠️ Options Flow

You can adjust settings at any time:

1. Go to **Settings > Devices & Services**.
2. Find **Lidl Weekly Offers** and click **Configure**.
3. Options available:
   - **Update Interval**: How often to poll the Lidl API (1–168 hours, default: 24 h).
   - **Automatically activate coupons in background**: Toggle automatic background activation of store coupons upon refresh.
   - **Skip special product selection coupons**: Choose whether to skip coupons requiring product choices or automatically select default products.
   - **Log in to Lidl Plus** / **Log out of Lidl Plus**: Manage your Lidl Plus authentication.

## 🃏 Lovelace Cards

The community has built dedicated cards to display Lidl discounts beautifully in your dashboard.

### Custom Discounts Card
A dedicated Lovelace card maintained by the community:

[![Discounts Card](https://img.shields.io/badge/Lovelace-%20Discounts%20Card-brightgreen?style=for-the-badge&logo=home-assistant)](https://github.com/schblondie/discounts-card)

---

## 🧑‍💻 Development

### Ruff Linter
Ensure formatting and import order matches:
```bash
ruff check . --fix
ruff format .
```

### Type Checking
Ensure all files pass strict type checking:
```bash
mypy .
```

### Running Tests
Verify your changes against the test suite:
```bash
pytest
```

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
