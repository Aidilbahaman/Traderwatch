/* ===== Settings: edit these ===== */
const CONFIG = {
  // Form service that receives sign-ups, e.g. "https://formspree.io/f/xxxxxxx". Leave empty until you have one.
  signupEndpoint: "https://formspree.io/f/xqpewvzl",
  // Payment link for Pro (Stripe Payment Link, Lemon Squeezy, Paddle, etc.)
  proCheckoutUrl: "",
  // Touch 'n Go eWallet QR. Used when proCheckoutUrl is empty.
  // 1) Your QR image is saved in this folder as tng-qr.jpg
  // 2) Set the amount you charge per month in MYR
  tngQrImage: "tng-qr.jpg",
  proPriceMYR: "79.00",
  // Supabase (real logins, next step). The publishable key is safe in public code. Never put a secret or service_role key here.
  supabaseUrl: "https://vicfiftvhxemuhxxmkxk.supabase.co",
  supabaseKey: "sb_publishable_4LzgHiCMUXmXUOkPtvIHVw_F7ks9otV",
  pairs: [
    {label:"EUR/USD", symbol:"FX:EURUSD"},
    {label:"GBP/USD", symbol:"FX:GBPUSD"},
    {label:"USD/JPY", symbol:"FX:USDJPY"},
    {label:"XAU/USD", symbol:"OANDA:XAUUSD"},
    {label:"AUD/USD", symbol:"FX:AUDUSD"}
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
