/* ===== Settings: edit these ===== */
const CONFIG = {
  // Form service that receives sign-ups, e.g. "https://formspree.io/f/xxxxxxx". Leave empty until you have one.
  signupEndpoint: "https://formspree.io/f/xqpewvzl",
  // Stripe Payment Link per plan (dibuat via Stripe Dashboard).
  // Leave a plan empty to fall back to the Touch 'n Go QR flow below.
  // Payment Link already carries the price + currency configured in Stripe;
  // this site only sends the member's email for auto-fill.
  checkoutUrls: {
    free: "https://buy.stripe.com/aFa9AS8bP8972s9g3tdby04",
    pro:  "https://buy.stripe.com/aFaaEWgIl4WVgiZ18zdby05",
    max:  "https://buy.stripe.com/dRmbJ04ZDblj0k1bNddby06"
  },
  // Touch 'n Go eWallet QR. Fallback bila plan tiada checkout URL (Stripe).
  // 1) Your QR image is saved in this folder as tng-qr.jpg
  // 2) Amounts below are MYR estimates of the USD plan price; edit to match
  //    what you actually charge before accepting any payment.
  tngQrImage: "tng-qr.jpg",
  planPrices: {
    pro: { usd: "20", myr: "82.00" },
    max: { usd: "50", myr: "204.00" }
  },
  // Supabase (real logins, next step). The publishable key is safe in public code. Never put a secret or service_role key here.
  supabaseUrl: "https://vicfiftvhxemuhxxmkxk.supabase.co",
  supabaseKey: "sb_publishable_4LzgHiCMUXmXUOkPtvIHVw_F7ks9otV",
  pairs: [
    {label:"EUR/USD", symbol:"FX:EURUSD"},
    {label:"GBP/USD", symbol:"FX:GBPUSD"},
    {label:"USD/JPY", symbol:"FX:USDJPY"},
    {label:"XAU/USD", symbol:"OANDA:XAUUSD"},
    {label:"AUD/USD", symbol:"FX:AUDUSD"},
    {label:"USD/CAD", symbol:"FX:USDCAD"},
    {label:"NZD/USD", symbol:"FX:NZDUSD"}
  ],
  signals: [
    {pair:"EUR/USD", side:"BUY",  entry:"1.0850", sl:"1.0815", tp:"1.0920", time:"Posted today, 08:15", locked:false},
    {pair:"XAU/USD", side:"SELL", entry:"2,415.0", sl:"2,428.0", tp:"2,385.0", time:"Posted today, 11:40", locked:true},
    {pair:"USD/JPY", side:"BUY",  entry:"149.20", sl:"148.60", tp:"150.50", time:"Posted yesterday, 14:05", locked:true}
  ],
  // Live signals are loaded from this URL. If it is unreachable, the
  // sample signals above are shown instead.
  signalsEndpoint: ""
};
