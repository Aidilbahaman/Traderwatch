/* ===== Settings: edit these ===== */
const CONFIG = {
  // Form service that receives sign-ups, e.g. "https://formspree.io/f/xxxxxxx". Leave empty until you have one.
  signupEndpoint: "https://formspree.io/f/xqpewvzl",
  // Payment link per plan (Stripe Payment Link, Lemon Squeezy, Paddle, etc).
  // Leave a plan empty to fall back to the Touch 'n Go QR flow below.
  checkoutUrls: { pro: "", max: "" },
  // Touch 'n Go eWallet QR. Used when the plan has no checkout URL.
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
    {label:"USD/CAD", symbol:"FX:USDCAD"}
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
