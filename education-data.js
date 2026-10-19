/* TraderWatch Education lesson data.
   Extend by adding entries to window.TW_LESSONS. Fields:
   id (string, used in lesson.html?id=...), title, category, minutes,
   tier ("free" | "pro" | "max"), body: array of blocks.
   Block types: h (heading), p (paragraph), ul (list), callout.
   Content safety: educational concepts only — no financial advice,
   no profit claims, no performance numbers. */
window.TW_LESSONS = [
  {
    id: "what-is-forex",
    title: "What is forex?",
    category: "Basics",
    minutes: 5,
    tier: "free",
    body: [
      { t: "p", text: "TODO: replace with final copy. Forex (foreign exchange) is the global market where currencies are traded against each other. Prices are quoted in pairs, for example EUR/USD." },
      { t: "h", text: "Key ideas" },
      { t: "ul", items: [
        "TODO: replace with final copy. A currency pair has a base and a quote currency.",
        "TODO: replace with final copy. Traders speculate on the direction of exchange-rate movement.",
        "TODO: replace with final copy. The market trades nearly 24/5 across sessions in Sydney, Tokyo, London and New York."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice. Forex trading carries a high level of risk." }
    ]
  },
  {
    id: "pips-lots-leverage",
    title: "Pips, lots and leverage",
    category: "Basics",
    minutes: 6,
    tier: "free",
    body: [
      { t: "p", text: "TODO: replace with final copy. Pips, lots and leverage are the units of measurement and sizing in forex trading. Understanding them is essential before reading any setup." },
      { t: "h", text: "Definitions" },
      { t: "ul", items: [
        "TODO: replace with final copy. A pip is the standard unit of price movement for a pair.",
        "TODO: replace with final copy. A lot is the standard trade size; mini and micro lots allow smaller exposure.",
        "TODO: replace with final copy. Leverage lets a trader control a larger position with less capital — and magnifies both gains and losses."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  },
  {
    id: "risk-management-101",
    title: "Risk management 101",
    category: "Basics",
    minutes: 8,
    tier: "free",
    body: [
      { t: "p", text: "TODO: replace with final copy. Risk management is the practice of limiting how much capital is exposed on any single trade and overall. It is the foundation of long-term participation." },
      { t: "h", text: "Core habits" },
      { t: "ul", items: [
        "TODO: replace with final copy. Decide risk per trade before opening a position.",
        "TODO: replace with final copy. Place a stop-loss level for every position.",
        "TODO: replace with final copy. Keep position size consistent with your account and risk rules."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  },
  {
    id: "reading-candlesticks",
    title: "Reading candlesticks",
    category: "Charts & price action",
    minutes: 7,
    tier: "pro",
    body: [
      { t: "p", text: "TODO: replace with final copy. Each candlestick summarises price action over a period: the open, high, low and close. Patterns of candles are used by many traders to read momentum." },
      { t: "h", text: "What to look at" },
      { t: "ul", items: [
        "TODO: replace with final copy. The body shows the distance between open and close.",
        "TODO: replace with final copy. The wicks show the high and low reached during the period.",
        "TODO: replace with final copy. Body and wick combinations are the building blocks of larger chart patterns."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice. Chart patterns are descriptive, not predictive." }
    ]
  },
  {
    id: "support-and-resistance",
    title: "Support and resistance",
    category: "Charts & price action",
    minutes: 9,
    tier: "pro",
    body: [
      { t: "p", text: "TODO: replace with final copy. Support and resistance are price zones where past buying or selling activity repeatedly appeared. Traders watch them as reference levels." },
      { t: "h", text: "Working with zones" },
      { t: "ul", items: [
        "TODO: replace with final copy. Mark zones rather than exact lines.",
        "TODO: replace with final copy. Levels gain significance when tested multiple times.",
        "TODO: replace with final copy. Levels can change role once price moves decisively through them."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  },
  {
    id: "trading-the-news",
    title: "Trading around news events",
    category: "Fundamentals",
    minutes: 10,
    tier: "pro",
    body: [
      { t: "p", text: "TODO: replace with final copy. Scheduled economic releases — such as central-bank decisions and inflation reports — can move prices quickly. The dashboard's high-impact USD calendar highlights these moments." },
      { t: "h", text: "Key points" },
      { t: "ul", items: [
        "TODO: replace with final copy. Check the economic calendar before planning a session.",
        "TODO: replace with final copy. Spreads can widen and liquidity can thin around releases.",
        "TODO: replace with final copy. Many traders choose to reduce or avoid exposure during major releases."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  },
  {
    id: "intraday-momentum",
    title: "Intraday momentum concepts",
    category: "Strategy lessons",
    minutes: 12,
    tier: "max",
    body: [
      { t: "p", text: "TODO: replace with final copy. Intraday momentum refers to the tendency of price direction to persist for stretches within a trading session. Traders study session ranges and recent movement to understand it." },
      { t: "h", text: "Concepts to explore" },
      { t: "ul", items: [
        "TODO: replace with final copy. Sessions differ in character across London and New York hours.",
        "TODO: replace with final copy. A session's opening range is a common reference.",
        "TODO: replace with final copy. Momentum measures are descriptive tools, not signals on their own."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice. No strategy guarantees outcomes." }
    ]
  },
  {
    id: "backtesting-basics",
    title: "Backtesting basics",
    category: "Strategy lessons",
    minutes: 11,
    tier: "max",
    body: [
      { t: "p", text: "TODO: replace with final copy. Backtesting is reviewing how a defined rule-set would have behaved on past price data. It is a learning exercise to test a process before considering real exposure." },
      { t: "h", text: "Main ideas" },
      { t: "ul", items: [
        "TODO: replace with final copy. Define rules precisely enough to test them the same way twice.",
        "TODO: replace with final copy. Record every simulated trade, including the losing ones.",
        "TODO: replace with final copy. Past behaviour of a rule-set does not guarantee future results."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  },
  {
    id: "trading-journal",
    title: "Keeping a trading journal",
    category: "Strategy lessons",
    minutes: 8,
    tier: "max",
    body: [
      { t: "p", text: "TODO: replace with final copy. A trading journal records what was done and why, so decisions can be reviewed calmly afterwards. Training journals work the same way — review turns experience into feedback." },
      { t: "h", text: "What to record" },
      { t: "ul", items: [
        "TODO: replace with final copy. The reason for entering and the planned exit before the trade.",
        "TODO: replace with final copy. Emotional state and adherence to your own rules.",
        "TODO: replace with final copy. A short post-trade review — what followed the plan, what did not."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice." }
    ]
  }
];
