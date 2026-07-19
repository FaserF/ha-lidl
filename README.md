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

It groups all sensors under a single market device and implements advanced lock-serialization, random jitter delays, storage caching, and exponential backoffs to keep your setup secure and prevent rate-limiting bans.

---

## ✨ Features

- **🛒 Detailed Offers Sensors**:
  - **Offers**: Current week's discounted items count, with attributes detailing titles, brands, categories, prices (original & discount), packaging units, unit prices, and direct links to product images.
  - **Offers Preview**: Next week's upcoming deals.
- **🔐 Lidl Plus Features** *(requires login)*:
  - **Coupons**: Number of available and activated coupons on your account.
  - **Activate All Coupons**: A button entity that activates every available coupon on your Lidl Plus account with a single tap.
  - **Last Receipt**: Shows your most recent Lidl purchase total and date.
  - **Loyalty ID**: Your Lidl Plus loyalty card number (barcode ID).
- **🛡️ Rate-Limiting & Anti-Ban Protections**:
  - **First-Fetch Optimisation**: Skips jitter sleep on initial setup so the first refresh completes instantly.
  - **Lock Queueing**: A domain-wide lock ensures concurrent updates run sequentially.
  - **Random Jitter**: Introduces a 5–15 second delay between requests.
  - **Restart-Resistance**: Saves parsed data to Home Assistant's JSON storage cache to survive restarts without hitting the API.
  - **Exponential Backoff**: Backs off for up to 24 hours on 403/429 blocks, and minutes on network failures.
- **⚙️ Device-Based Grouping**:
  - All sensors and buttons are automatically grouped under a main Lidl Store device.
  - **Visit Lidl Store Button**: The device registry provides a dynamic configuration URL that takes you straight to your specific country's Lidl website.
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

### Why is login complicated?

Lidl's authentication system uses a **proprietary OAuth 2.0 + PKCE flow** that is designed exclusively for their mobile app. The auth server (`accounts.lidl.com`) uses:
- A **custom URI scheme** (`com.lidlplus.app://callback`) as the OAuth redirect target — a scheme that only the real Lidl app can handle on a mobile device.
- **Angular SPA** (Single Page Application) for the login UI, which relies heavily on JavaScript for form submission and navigation.
- **Anti-automation measures** that detect and reject browser-based flows that don't match the fingerprint of the real Lidl app.

---

### Option 1: Automatic login in Home Assistant *(try this first)*

The integration attempts a **headless login** directly from Home Assistant using your email/password:
1. During setup (or in Options Flow → **Log in to Lidl Plus**), enter your **Lidl Plus email/phone** and **password**.
2. If your account uses **two-factor authentication (MFA/2FA)**, a second step will appear asking for your verification code.
3. If login succeeds, the integration will store a **refresh token** — you will not need to log in again.

---

### Option 2: Manual Refresh Token via Browser & Terminal *(fallback)*

If Option 1 fails or gets stuck on MFA, you can capture the code and exchange it for a token manually using any standard Web Browser and Terminal (PowerShell / Terminal).

#### Step 1: Open the Lidl OAuth Authorization Page

Copy the URL below, replace `COUNTRY` with your country code in uppercase (e.g. `DE`) and `LANG` with your lowercase language code (e.g. `de`), and open it in your desktop web browser:

```
https://accounts.lidl.com/connect/authorize?client_id=LidlPlusNativeClient&redirect_uri=com.lidlplus.app%3A%2F%2Fcallback&response_type=code&scope=openid%20profile%20offline_access%20lpprofile%20lpapis&code_challenge=FqIYVVYB0E6McLBFgG679hzdviy-I6EOUTRnA4COpss&code_challenge_method=S256&Country=COUNTRY&language=LANG-COUNTRY
```

#### Step 2: Authenticate and Capture the Redirect

1. Complete the login process and enter your MFA verification code if prompted.
2. The browser will eventually show a connection error or blank page because it tries to load `com.lidlplus.app://callback?code=...`.
3. **Copy the full URL** from the browser's address bar. It will contain `code=YOUR_AUTHORIZATION_CODE`.

#### Step 3: Exchange the Code for a Refresh Token

Open your terminal and execute the request to exchange the code. 

**For Windows (PowerShell):**
```powershell
$body = @{
    grant_type = "authorization_code"
    code = "PASTE_YOUR_CODE_HERE"
    redirect_uri = "com.lidlplus.app://callback"
    code_verifier = "LidlPlusNativeClientVerifierLidlPlusNativeClientVerifier"
}
Invoke-RestMethod -Uri "https://accounts.lidl.com/connect/token" -Method Post -Body $body -Headers @{ Authorization = "Basic TGlkbFBsdXNOYXRpdmVDbGllbnQ6c2VjcmV0" }
```

**For macOS / Linux (cURL):**
```bash
curl -X POST https://accounts.lidl.com/connect/token \
  -H "Authorization: Basic TGlkbFBsdXNOYXRpdmVDbGllbnQ6c2VjcmV0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=PASTE_YOUR_CODE_HERE" \
  -d "redirect_uri=com.lidlplus.app://callback" \
  -d "code_verifier=LidlPlusNativeClientVerifierLidlPlusNativeClientVerifier"
```

The response will contain the `refresh_token`. Copy it and paste it in Home Assistant under **Enter refresh token manually**.

---

## 🛠️ Options Flow

You can adjust settings at any time:

1. Go to **Settings > Devices & Services**.
2. Find **Lidl Weekly Offers** and click **Configure**.
3. Options available:
   - **Update Interval**: How often to poll the Lidl API (1–168 hours, default: 24 h).
   - **Log in to Lidl Plus** / **Log out of Lidl Plus**: Manage your Lidl Plus authentication.

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

This project is licensed under the Apache 2.0 License. See the [LICENSE](LICENSE) file for details.
