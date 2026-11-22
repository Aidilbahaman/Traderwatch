//+------------------------------------------------------------------+
//|  StraddleBE.mq5 - trailing BUY STOP / SELL STOP straddle with    |
//|  fixed SL and break-even lock. XAUUSD M1, 0.10 lot.              |
//|  Behaviour inferred from a screen recording (XAUUSD-ECN M1):     |
//|   - BUY STOP + SELL STOP (same lot) sit just either side of price|
//|     and FOLLOW price (buy-stop only moves down, sell-stop only up)|
//|   - each order carries an initial SL (~110 pts)                  |
//|   - once a trade is ~50 pts in profit, SL moves to entry +10 pts |
//|     (break-even lock). No martingale, no lot doubling.           |
//|   - the opposite pending stays alive after a fill (reversal)     |
//|  Inferred numbers are inputs. HEDGING ACCOUNT REQUIRED.          |
//+------------------------------------------------------------------+
#property strict
#property version "1.00"
#include <Trade/Trade.mqh>

CTrade trade;

input group "Straddle"
input double InpLot          = 0.10;
input int    InpDistPts      = 80;     // Pending distance from price (video: BUY STOP ~0.8 USD above price)
input int    InpTrailStepPts = 20;     // Move a pending only when it is this far from its ideal price
input int    InpSLPts        = 110;    // Initial stop loss (video: ~1.10 USD)
input int    InpTPPts        = 0;      // Take profit (0 = none, as in the video)

input group "Break-even / trailing"
input int    InpBEStartPts   = 20;     // Profit (pts) that triggers break-even (video: somewhere 8..61)
input int    InpBELockPts    = 5;     // SL goes to entry +/- this (video: ~0.10 USD)
input int    InpTrailPts     = 30;      // Optional trailing distance after BE (0 = off; video shows none)

input group "Filters / safety"
input int    InpMaxSpread    = 50;     // Do not place/move pendings above this spread (pts)
input int    InpStartHour    = 0;      // Server-time window
input int    InpEndHour      = 24;
input double InpDailyLossPct = 5.0;    // Stop for the day at this % loss of day-start balance (0 = off)

input group "Technical"
input int    InpDeviation    = 30;
input ulong  InpMagic        = 20261112;
input string InpComment      = "STRADDLE_BE";

double g_dayBalance = 0;
int    g_day = -1;
bool   g_dayStopped = false;

//+------------------------------------------------------------------+
int OnInit()
{
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("StraddleBE: needs a HEDGING account (the opposite pending must open a separate position).");
      return INIT_FAILED;
   }
   if(InpDistPts <= 0 || InpSLPts <= 0 || InpLot <= 0) return INIT_PARAMETERS_INCORRECT;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviation);
   trade.SetTypeFillingBySymbol(_Symbol);
   PrintFormat("StraddleBE: OnInit OK magic=%I64u lot=%.2f dist=%d", InpMagic, InpLot, InpDistPts);
   PrintFormat("PERM CHECK: terminal_trade=%d account_trade_expert=%d mql_trade_allowed=%d",
      (int)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED),
      (int)AccountInfoInteger(ACCOUNT_TRADE_EXPERT),
      (int)MQLInfoInteger(MQL_TRADE_ALLOWED));
   SymbolSelect(_Symbol, true);
   EventSetTimer(1);   // fallback: run even when the chart receives no ticks (headless Wine)
   return INIT_SUCCEEDED;
}

double NormLot(double lot)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lot = MathFloor(lot / step + 1e-9) * step;
   return NormalizeDouble(MathMax(mn, MathMin(mx, lot)), 2);
}

bool HasPosition(ENUM_POSITION_TYPE type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == type) return true;
   }
   return false;
}

ulong FindPending(ENUM_ORDER_TYPE type)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if((ulong)OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE) == type) return t;
   }
   return 0;
}

void DeletePending(ENUM_ORDER_TYPE type)
{
   ulong t = FindPending(type);
   if(t != 0 && !trade.OrderDelete(t))
      PrintFormat("StraddleBE: delete %I64u failed %d", t, trade.ResultRetcode());
}

//+------------------------------------------------------------------+
bool TradingAllowed()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != g_day)
   {
      g_day = dt.day_of_year;
      g_dayBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_dayStopped = false;
   }
   if(InpDailyLossPct > 0 && g_dayBalance > 0 &&
      (g_dayBalance - AccountInfoDouble(ACCOUNT_EQUITY)) / g_dayBalance * 100.0 >= InpDailyLossPct)
      g_dayStopped = true;
   if(g_dayStopped) return false;
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpread) return false;
   return true;
}

// Break-even lock (+ optional trailing) on open positions.
void ManagePositions()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      bool   buy  = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double profitPts = buy ? (bid - open) / _Point : (open - ask) / _Point;
      if(InpBEStartPts <= 0 || profitPts < InpBEStartPts) continue;

      double newSL = buy ? open + InpBELockPts * _Point : open - InpBELockPts * _Point;
      if(InpTrailPts > 0)
      {
         double tsl = buy ? bid - InpTrailPts * _Point : ask + InpTrailPts * _Point;
         newSL = buy ? MathMax(newSL, tsl) : MathMin(newSL, tsl);
      }
      newSL = NormalizeDouble(newSL, _Digits);

      bool better = buy ? (sl == 0 || newSL > sl + _Point / 2) : (sl == 0 || newSL < sl - _Point / 2);
      bool valid  = buy ? (bid - newSL >= minDist) : (newSL - ask >= minDist);
      if(better && valid && !trade.PositionModify(t, newSL, tp))
         PrintFormat("StraddleBE: modify SL failed %d", trade.ResultRetcode());
   }
}

// One pending per side while that side has no open position. They follow price.
void ManagePendings(bool allowed)
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double dist = MathMax(InpDistPts * _Point, minDist + SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * _Point);
   double lot  = NormLot(InpLot);
   double step = InpTrailStepPts * _Point;

   for(int s = 0; s < 2; s++)
   {
      bool buy = (s == 0);
      ENUM_ORDER_TYPE type = buy ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
      if(HasPosition(buy ? POSITION_TYPE_BUY : POSITION_TYPE_SELL) || !allowed)
      { DeletePending(type); continue; }

      double ideal = NormalizeDouble(buy ? ask + dist : bid - dist, _Digits);
      double sl = NormalizeDouble(buy ? ideal - InpSLPts * _Point : ideal + InpSLPts * _Point, _Digits);
      double tp = InpTPPts > 0 ? NormalizeDouble(buy ? ideal + InpTPPts * _Point : ideal - InpTPPts * _Point, _Digits) : 0;

      ulong t = FindPending(type);
      if(t == 0)
      {
         PrintFormat("StraddleBE: sending %s lot=%.2f ideal=%.2f sl=%.2f allowed=%d", buy?"BUY_STOP":"SELL_STOP", lot, ideal, sl, (int)allowed);
         bool ok = buy ? trade.BuyStop(lot, ideal, _Symbol, sl, tp, ORDER_TIME_GTC, 0, InpComment)
                       : trade.SellStop(lot, ideal, _Symbol, sl, tp, ORDER_TIME_GTC, 0, InpComment);
         if(ok)
            PrintFormat("StraddleBE: SUCCESS %s ticket=%I64u", buy?"BUY_STOP":"SELL_STOP", trade.ResultOrder());
         else
            PrintFormat("StraddleBE: FAIL %s code=%d desc=%s", buy?"BUY_STOP":"SELL_STOP", trade.ResultRetcode(), trade.ResultComment());
      }
      else
      {
         double cur = OrderGetDouble(ORDER_PRICE_OPEN);   // FindPending left this order selected
         // buy-stop only ratchets DOWN, sell-stop only UP (follows price as it moves away)
         bool move = buy ? (cur - ideal >= step) : (ideal - cur >= step);
         if(move && !trade.OrderModify(t, ideal, sl, tp, ORDER_TIME_GTC, 0))
            PrintFormat("StraddleBE: move %s failed %d", buy ? "BUY STOP" : "SELL STOP", trade.ResultRetcode());
      }
   }
}

void RunCycle()
{
   bool allowed = TradingAllowed();
   ManagePositions();
   ManagePendings(allowed);
}

void OnTick()
{
   RunCycle();
}

void OnTimer()
{
   RunCycle();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}
//+------------------------------------------------------------------+
