/* TraderWatch Education lesson data.
   Extend by adding entries to window.TW_LESSONS. Fields:
   id (string, used in lesson.html?id=...), title, category, minutes,
   tier ("free" | "pro" | "max"), body: array of blocks.
   Block types: h (heading), p (paragraph), ul (list), callout.
   Content safety: educational concepts only — no financial advice,
   no profit claims, no performance numbers. Changing an existing id
   resets that lesson's saved progress. */
window.TW_LESSONS = [
  {
    id: "what-is-forex",
    title: "What is forex?",
    category: "Basics",
    minutes: 5,
    tier: "free",
    body: [
      { t: "p", text: "Forex is the market where one currency is exchanged for another. It is the largest market in the world by turnover, and it never really closes during the working week." },
      { t: "h", text: "Currencies trade in pairs" },
      { t: "p", text: "Every forex price is a ratio between two currencies. In EUR/USD, the euro is the base currency and the US dollar is the quote currency. A price of 1.0850 means one euro is worth 1.0850 dollars." },
      { t: "ul", items: [
        "Buying the pair means you expect the base currency to strengthen against the quote currency.",
        "Selling the pair means the opposite.",
        "The price on screen is the market's current agreement, not a forecast."
      ] },
      { t: "h", text: "Who is on the other side" },
      { t: "p", text: "Banks, importers and exporters, investment funds, central banks and retail traders all take part. Most volume comes from institutions settling real business, which is why the market is so liquid during overlapping sessions." },
      { t: "h", text: "The four sessions" },
      { t: "p", text: "Activity moves around the globe: Sydney opens, then Tokyo, then London, then New York. The London–New York overlap is historically the busiest window, which is why spreads are usually tightest and price moves fastest then." },
      { t: "callout", text: "Educational content only. Not financial advice. Forex trading carries a high level of risk and leveraged positions can lose more than the amount committed." }
    ]
  },
  {
    id: "pips-lots-leverage",
    title: "Pips, lots and leverage",
    category: "Basics",
    minutes: 6,
    tier: "free",
    body: [
      { t: "p", text: "Three units decide what a trade actually costs you: the pip measures movement, the lot measures size, and leverage measures how much of the position your broker funds." },
      { t: "h", text: "The pip" },
      { t: "p", text: "A pip is the standard increment of price movement. For most pairs it is the fourth decimal place (0.0001). For pairs quoted in Japanese yen it is the second decimal place (0.01). Many platforms also show a fifth digit — a pipette — which is one tenth of a pip." },
      { t: "h", text: "The lot" },
      { t: "p", text: "A lot is a fixed quantity of currency. A standard lot is 100,000 units of the base currency, a mini lot is 10,000, and a micro lot is 1,000. Position size is simply how many lots you are trading." },
      { t: "p", text: "Pip value follows from size. On a standard lot of a pair where the quote currency is the US dollar, one pip is worth roughly ten dollars; on a mini lot roughly one dollar; on a micro lot roughly ten cents. Exact values shift with the exchange rate, which is why platforms display them live." },
      { t: "h", text: "Leverage and margin" },
      { t: "p", text: "Leverage lets a broker hold a position larger than your deposit. At 1:100, a position of 100,000 units requires about 1,000 units of margin — one percent. Leverage does not change the size of a price move; it changes how large that move is relative to your account." },
      { t: "ul", items: [
        "A move against a leveraged position loses money faster than the same move unleveraged.",
        "If equity falls below the required margin, the broker may close positions automatically — a margin call or stop out.",
        "Margin is not a cost. It is capital set aside while the position is open."
      ] },
      { t: "callout", text: "Educational content only. Not financial advice. Leverage magnifies losses as well as gains." }
    ]
  },
  {
    id: "risk-management-101",
    title: "Risk management 101",
    category: "Basics",
    minutes: 8,
    tier: "free",
    body: [
      { t: "p", text: "Risk management is the practice of deciding in advance how much of an account can be lost on a single trade, and on a run of trades. It is the part of trading that is fully under your control." },
      { t: "h", text: "Risk per trade" },
      { t: "p", text: "The common approach is fixed fractional risk: risk a fixed percentage of the account on each trade, so size shrinks after losses and grows after gains. Educational material often discusses figures in the low single digits, but the right number depends on the account, the approach and the person — it is a decision, not a rule of nature." },
      { t: "p", text: "Risk per trade is set by two things together: where the stop loss sits, and how large the position is. Moving a stop closer without shrinking size increases risk, not reduces it." },
      { t: "h", text: "Why the maths matters more than the win rate" },
      { t: "p", text: "Losses and gains are not symmetrical. A 50% drawdown needs a 100% gain to return to the starting point, because recovery is measured from a smaller base. That asymmetry is why protecting capital matters more than chasing a high percentage of winning trades." },
      { t: "ul", items: [
        "A run of losses is normal for any approach — sizing has to survive the bad run, not just the good one.",
        "Risk-to-reward describes the relationship between the stop distance and the target distance.",
        "Correlated positions stack risk: three long trades in similar currencies is closer to one large trade than three small ones."
      ] },
      { t: "h", text: "Decide before, not during" },
      { t: "p", text: "Risk rules only work if they are set before a position is open. Once money is at stake the temptation is to widen a stop or add size to recover a loss — the two behaviours that turn a manageable drawdown into an account-ending one." },
      { t: "callout", text: "Educational content only. Not financial advice. No risk process removes the possibility of loss." }
    ]
  },
  {
    id: "reading-candlesticks",
    title: "Reading candlesticks",
    category: "Charts & price action",
    minutes: 7,
    tier: "pro",
    body: [
      { t: "p", text: "A candlestick compresses one period of price action into four numbers: open, high, low and close. Reading them is the basic literacy of chart work." },
      { t: "h", text: "The four prices" },
      { t: "ul", items: [
        "The body spans the open and the close. A filled body usually means the close was below the open; a hollow body means the close was above it.",
        "The upper wick reaches the highest price of the period.",
        "The lower wick reaches the lowest price.",
        "A long body says the period ended far from where it started. A short body says it did not."
      ] },
      { t: "h", text: "What the shapes describe" },
      { t: "p", text: "A candle with a tiny body and long wicks on both sides is called a doji — it describes a period where price moved but ended near where it began. A candle with a long lower wick and a small body near the top is called a hammer shape. These names describe what happened. They do not say what happens next." },
      { t: "h", text: "Timeframes change the meaning" },
      { t: "p", text: "The same shape means different things on a one-minute chart and a daily chart. A daily candle contains everything that happened during the day, including moves that looked dramatic on a five-minute chart. Most traders pick one timeframe for context and a smaller one for timing, and read them together rather than in isolation." },
      { t: "h", text: "The honest limit" },
      { t: "p", text: "Candle patterns describe past behaviour. Tests of pattern performance produce mixed results, and any pattern can fail in conditions that differ from the sample it was observed in. Treat them as context, not as instructions." },
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
      { t: "p", text: "Support and resistance are price areas where the market has repeatedly turned. They are drawn as zones rather than lines, because price rarely respects a single number to the pip." },
      { t: "h", text: "Why price reacts there" },
      { t: "p", text: "Areas where price reversed before tend to hold resting orders: stop losses from traders positioned the other way, and limit orders from traders waiting for a better price. That concentration of orders can produce a visible reaction, which is why the same area often matters more than once." },
      { t: "h", text: "How to mark a zone" },
      { t: "ul", items: [
        "Start from swing highs and swing lows on the timeframe you are reading.",
        "Draw a band around the wicks rather than a single line at the close.",
        "Prefer zones that have produced several clear reactions over ones touched once.",
        "Fewer, wider zones are easier to act on than a chart covered in lines."
      ] },
      { t: "h", text: "Role reversal" },
      { t: "p", text: "When price moves decisively through a support zone, that zone often becomes resistance on a retest, and the reverse. The idea is that traders who defended the level may now exit on the return, adding pressure in the new direction." },
      { t: "h", text: "What breaks a zone" },
      { t: "p", text: "A close beyond the zone on the timeframe that defined it carries more weight than a wick through it. Time matters too: a level tested many times in a short window tends to weaken, because the orders that created the reaction have already been filled." },
      { t: "callout", text: "Educational content only. Not financial advice. Levels describe where price reacted before, not where it must react again." }
    ]
  },
  {
    id: "trading-the-news",
    title: "Trading around news events",
    category: "Fundamentals",
    minutes: 10,
    tier: "pro",
    body: [
      { t: "p", text: "Scheduled economic releases move currency prices because they change expectations about interest rates and growth. Knowing when they land is part of reading the chart, not a separate discipline." },
      { t: "h", text: "The events that matter most" },
      { t: "ul", items: [
        "Central bank rate decisions and the statement that follows.",
        "Inflation data such as CPI, which markets watch for rate expectations.",
        "Employment reports, read as a gauge of economic strength.",
        "Growth figures such as GDP, and minutes from past central bank meetings."
      ] },
      { t: "p", text: "The dashboard's fundamental panel lists high-impact USD events from the TradingView calendar. An impact label is a guide to how much attention an event usually receives, not a guarantee of a large move." },
      { t: "h", text: "What changes around a release" },
      { t: "p", text: "In the seconds around a scheduled release, liquidity thins as market makers widen quotes or step away. Spreads can multiply, and orders can fill far from the price on screen — that is slippage. A stop placed close to price is more likely to be hit by the widened spread than by a real change in direction." },
      { t: "h", text: "Working with the calendar" },
      { t: "p", text: "The practical use of a calendar is planning, not predicting. Many traders reduce size or stand aside before a major release and wait for conditions to normalise; others treat the release itself as the event they want to trade. Both are choices with different risk profiles, and both are legitimate — what matters is that the choice is made before the release, not during the spike." },
      { t: "callout", text: "Educational content only. Not financial advice. News trading involves fast moves, wide spreads and the risk of losses beyond the planned amount." }
    ]
  },
  {
    id: "intraday-momentum",
    title: "Intraday momentum concepts",
    category: "Strategy lessons",
    minutes: 12,
    tier: "max",
    body: [
      { t: "p", text: "Intraday momentum is the tendency of price to keep moving in the same direction for stretches within a session. It describes behaviour rather than acting as a signal, and it is strongest when a session brings new information and volume." },
      { t: "h", text: "Sessions have different characters" },
      { t: "p", text: "The Asian session is often quieter and range-bound, London brings a burst of activity at its open, the London–New York overlap carries the most volume, and New York alone often fades after its morning. These are tendencies, and they break down on days with major news." },
      { t: "h", text: "The opening range" },
      { t: "p", text: "A common reference is the first thirty to sixty minutes of a session — the opening range. Its high and low are watched because early volume shows where participants are willing to transact. Price leaving that range is often described as a breakout; returning into it is described as a failed break." },
      { t: "h", text: "Measuring momentum" },
      { t: "ul", items: [
        "Rate of change compares the current price with the price a number of periods ago.",
        "Average true range (ATR) describes how far price typically travels in a period, which is useful for sizing stops to an instrument's normal movement.",
        "Trend measures such as moving averages describe direction over a window and lag by design."
      ] },
      { t: "h", text: "Trend versus range" },
      { t: "p", text: "Momentum ideas behave differently in a trending market and a ranging one. In a range, price returning to the middle is normal; in a trend, the same pullback may be a continuation point. Deciding which regime you are in — using higher-timeframe structure rather than hope — is the step most descriptions of momentum skip." },
      { t: "h", text: "Where it goes wrong" },
      { t: "p", text: "Momentum readings are computed from past prices, so they turn after the move they describe. Late entries into exhausted moves, and stops sized for quiet conditions, are two common ways momentum approaches produce losses. Position sizing and a pre-defined exit do more work than the entry signal." },
      { t: "callout", text: "Educational content only. Not financial advice. No approach or indicator guarantees an outcome." }
    ]
  },
  {
    id: "backtesting-basics",
    title: "Backtesting basics",
    category: "Strategy lessons",
    minutes: 11,
    tier: "max",
    body: [
      { t: "p", text: "Backtesting means applying a fixed set of rules to historical price data to see how those rules would have behaved. Its value is finding out whether a process is testable at all, not predicting what happens next." },
      { t: "h", text: "Rules must be exact" },
      { t: "p", text: "If a rule cannot be applied the same way twice, it cannot be tested. \"Buy when momentum is strong\" is not a rule. \"Enter at the close of the first candle that closes above the previous session high, stop at the session low\" is. The test is only as meaningful as the precision of the definition." },
      { t: "h", text: "The biases that flatter results" },
      { t: "ul", items: [
        "Look-ahead bias: using information that was not available when the decision would have been made.",
        "Overfitting: adding rules until the sample looks good, which usually means the rules describe that sample and nothing else.",
        "Ignoring costs: spread, commission and slippage turn many marginal results negative.",
        "Small samples: thirty trades is an anecdote, not evidence."
      ] },
      { t: "h", text: "In-sample and out-of-sample" },
      { t: "p", text: "A standard guard is to develop rules on one slice of history and check them on a later slice the rules have never seen. If behaviour collapses out of sample, the rules were fitted to noise. Walk-forward testing repeats this in rolling windows and is more realistic than a single split." },
      { t: "h", text: "What to record" },
      { t: "p", text: "Record every simulated trade, including the losers, with entry, exit, size and the reason for each decision. A backtest that only lists winning examples is a story, not a test. Note the market conditions in each period, because rules built in a trending year often behave differently in a range." },
      { t: "callout", text: "Educational content only. Not financial advice. Historical behaviour does not guarantee future results." }
    ]
  },
  {
    id: "trading-journal",
    title: "Keeping a trading journal",
    category: "Strategy lessons",
    minutes: 8,
    tier: "max",
    body: [
      { t: "p", text: "A trading journal records what was done and why, so decisions can be reviewed later with a clear head. Without one, every review is a memory exercise, and memory is generous to itself." },
      { t: "h", text: "What to write down" },
      { t: "ul", items: [
        "The reason for the trade, written before entry.",
        "Entry, stop and target, with position size and the risk it represents.",
        "The plan for managing the trade: where it gets cut, where it gets reduced.",
        "What actually happened, and whether the plan was followed.",
        "How you felt — rushed, bored, hesitant, over-confident. Emotions are data about process."
      ] },
      { t: "h", text: "Review on a schedule" },
      { t: "p", text: "A journal read once a quarter is a diary. A journal reviewed weekly, in a fixed format, becomes a feedback loop. The useful question is not \"did this trade win\" but \"was this decision consistent with the process I said I would follow\"." },
      { t: "h", text: "Process versus outcome" },
      { t: "p", text: "A good decision can lose and a bad decision can win. Judging process by outcome teaches the wrong lesson, because a single trade's result contains a large amount of randomness. Journals help separate the two by recording the reasoning at the time, before the result was known." },
      { t: "h", text: "Keep it small enough to keep" },
      { t: "p", text: "A journal with twenty fields per trade gets abandoned within a month. Five fields filled in consistently beat twenty filled in occasionally. A screenshot of the chart at entry and exit is worth more than paragraphs of description." },
      { t: "callout", text: "Educational content only. Not financial advice. Journaling improves self-knowledge, not outcomes." }
    ]
  }
];
