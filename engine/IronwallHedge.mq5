//+------------------------------------------------------------------+
//|  IronwallHedge.mq5  - hedge + doubling-lot "zone recovery" EA    |
//|  Replica of the behaviour seen in the "Ironwall Hedge V7" video  |
//|  (XAUUSD M5). Logic is inferred from the video, not the original |
//|  source. HEDGING ACCOUNT REQUIRED.                               |
//|                                                                  |
//|  Cycle:                                                          |
//|   1. Open first position (EMA signal or fixed direction).        |
//|   2. Keep ONE pending STOP at the opposite edge of a zone        |
//|      (InpStepPoints away) with lot = base * mult^n.              |
//|   3. Every fill flips the direction and places the next STOP.    |
//|   4. Close the whole basket when floating P/L >= target.         |
//|   5. Hard caps: max level, max lot, margin, equity DD, spread.   |
//+------------------------------------------------------------------+
#property strict
#property version "1.00"
#include <Trade/Trade.mqh>

CTrade trade;

input group "Entry"
input bool   InpStraddle       = true;      // Start like the video: BUY STOP + SELL STOP (base lot) around price
input bool   InpUseSignal      = true;      // (Straddle OFF only) use EMA signal for first position
input int    InpFastEMA        = 8;
input int    InpSlowEMA        = 21;
input bool   InpInitialBuy     = true;      // First direction if signal is off
input int    InpStartHour      = 0;         // Server-time window start
input int    InpEndHour        = 24;        // Server-time window end (24 = all day)
input int    InpMaxSpread      = 40;        // Skip new cycle if spread (points) above
input int    InpCooldownSec    = 5;         // Wait after a basket closes

input group "Ladder"
input double InpBaseLot        = 0.01;
input double InpLotMult        = 2.0;       // 0.01 > 0.02 > 0.04 ...
input int    InpStepPoints     = 200;       // Zone height (points). Video: 1.56-2.19 USD wide (~156-219 pts), XAUUSD 100 pts = 1.00
input int    InpMaxLevel       = 6;         // Max extra rungs after the first (6 => up to 7 positions, 0.01..0.64)
input double InpMaxLot         = 0.64;      // Never send a lot above this

input group "Exit / protection"
input double InpBasketTP       = 2.0;       // Basket target (money) per 0.01 base lot. Trail ON: trailing starts here
input bool   InpUseTrail       = true;      // Basket break-even/trailing: lock profit and follow price
input double InpLockProfit     = 0.5;       // Break-even lock (money, per 0.01 base lot): never close below this once trailing
input int    InpTrailGapPoints = 130;       // Trail distance behind price (points). Video: SL ~1.2-1.4 USD behind price at small lots
input int    InpTrailGapDeep   = 50;        // Tighter trail distance (points) at deep levels. Video: ~0.4-0.5 USD at 0.64 lot (one sample)
input int    InpDeepFromPos    = 6;         // "Deep" = this many open positions or more
input double InpMaxLevelExit   = 0.0;       // At max level close when profit >= this (money, can be negative)
input double InpHardStopMoney  = 0.0;       // Close all if floating <= -this (0 = off)
input double InpMaxDDPct       = 20.0;      // Close all + pause for the day at this equity DD % (0 = off)
input double InpMinMarginLevel = 150.0;     // Do not add rungs below this margin level % (0 = off)

input group "Technical"
input int    InpDeviation      = 30;
input ulong  InpMagic          = 20261111;
input string InpComment        = "IRONWALL";

int      hFast = INVALID_HANDLE, hSlow = INVALID_HANDLE;
datetime g_lastClose = 0;
double   g_cycleEquity = 0;
int      g_pauseDay = -1;
bool     g_trailOn = false;     // basket trailing active
double   g_peak = 0;            // best basket profit since trailing started
int      g_lastN = 0;           // position count when trail state was last valid

struct Basket
{
   int       n;
   double    profit;
   double    lots, buyLots, sellLots;
   long      firstMsc, lastMsc;
   ENUM_POSITION_TYPE firstType, lastType;
   double    firstPrice;
};

//+------------------------------------------------------------------+
int OnInit()
{
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("Ironwall: this EA needs a HEDGING account. Netting would merge the hedge legs.");
      return INIT_FAILED;
   }
   if(InpLotMult < 1.0 || InpMaxLevel < 1 || InpStepPoints <= 0)
   {
      Print("Ironwall: invalid ladder inputs");
      return INIT_PARAMETERS_INCORRECT;
   }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviation);
   trade.SetTypeFillingBySymbol(_Symbol);
   if(InpUseSignal)
   {
      hFast = iMA(_Symbol, _Period, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
      hSlow = iMA(_Symbol, _Period, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
      if(hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE) return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hFast != INVALID_HANDLE) IndicatorRelease(hFast);
   if(hSlow != INVALID_HANDLE) IndicatorRelease(hSlow);
}

//+------------------------------------------------------------------+
double NormLot(double lot)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lot = MathFloor(lot / step + 1e-9) * step;
   lot = MathMax(mn, MathMin(mx, lot));
   return NormalizeDouble(lot, 2);
}

void ReadBasket(Basket &b)
{
   b.n = 0; b.profit = 0; b.lots = 0; b.buyLots = 0; b.sellLots = 0;
   b.firstMsc = LONG_MAX; b.lastMsc = 0;
   b.firstType = POSITION_TYPE_BUY; b.lastType = POSITION_TYPE_BUY; b.firstPrice = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      b.n++;
      b.profit += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      b.lots   += PositionGetDouble(POSITION_VOLUME);
      long msc = PositionGetInteger(POSITION_TIME_MSC);
      ENUM_POSITION_TYPE ty = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(ty == POSITION_TYPE_BUY) b.buyLots += PositionGetDouble(POSITION_VOLUME);
      else                        b.sellLots += PositionGetDouble(POSITION_VOLUME);
      if(msc < b.firstMsc) { b.firstMsc = msc; b.firstType = ty; b.firstPrice = PositionGetDouble(POSITION_PRICE_OPEN); }
      if(msc >= b.lastMsc) { b.lastMsc = msc; b.lastType = ty; }
   }
}

int CountPendings()
{
   int c = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == InpMagic) c++;
   }
   return c;
}

void DeletePendings()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == InpMagic)
         if(!trade.OrderDelete(t)) PrintFormat("Ironwall: delete order %I64u failed %d", t, trade.ResultRetcode());
   }
}

void CloseAll(string why)
{
   PrintFormat("Ironwall: closing basket (%s)", why);
   DeletePendings();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(!trade.PositionClose(t))
         PrintFormat("Ironwall: close %I64u failed %d", t, trade.ResultRetcode());
   }
   g_lastClose = TimeCurrent();
}

int GetSignal()
{
   if(!InpUseSignal) return InpInitialBuy ? 1 : -1;
   double f[2], s[2];
   if(CopyBuffer(hFast, 0, 1, 2, f) < 2 || CopyBuffer(hSlow, 0, 1, 2, s) < 2) return 0;
   if(f[1] > s[1]) return 1;
   if(f[1] < s[1]) return -1;
   return 0;
}

bool MarginOK(ENUM_ORDER_TYPE type, double lot, double price)
{
   double need;
   if(!OrderCalcMargin(type, _Symbol, lot, price, need)) return false;
   if(need > AccountInfoDouble(ACCOUNT_MARGIN_FREE)) return false;
   if(InpMinMarginLevel > 0)
   {
      double used = AccountInfoDouble(ACCOUNT_MARGIN);
      if(used > 0)
      {
         double ml = AccountInfoDouble(ACCOUNT_EQUITY) / (used + need) * 100.0;
         if(ml < InpMinMarginLevel) return false;
      }
   }
   return true;
}

bool OpenMarket(bool buy, double lot, string tag)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(!MarginOK(buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lot, buy ? ask : bid))
   { Print("Ironwall: margin check failed for ", tag); return false; }
   bool ok = buy ? trade.Buy(lot, _Symbol, 0, 0, 0, tag) : trade.Sell(lot, _Symbol, 0, 0, 0, tag);
   if(!ok) PrintFormat("Ironwall: market %s failed %d", tag, trade.ResultRetcode());
   return ok;
}

// Keep exactly one pending STOP at the opposite edge of the zone.
void EnsurePending(const Basket &b)
{
   double lot = NormLot(InpBaseLot * MathPow(InpLotMult, b.n));
   if(b.n > InpMaxLevel || lot > InpMaxLot + 1e-9) { DeletePendings(); return; }

   double step    = InpStepPoints * _Point;
   double zoneHi  = (b.firstType == POSITION_TYPE_BUY) ? b.firstPrice : b.firstPrice + step;
   double zoneLo  = zoneHi - step;
   bool   wantBuy = (b.lastType == POSITION_TYPE_SELL);        // flip direction
   double price   = NormalizeDouble(wantBuy ? zoneHi : zoneLo, _Digits);
   ENUM_ORDER_TYPE wantType = wantBuy ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;

   // existing pending already correct?
   int cnt = 0; bool good = false;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || (ulong)OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      cnt++;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE) == wantType &&
         MathAbs(OrderGetDouble(ORDER_VOLUME_CURRENT) - lot) < 1e-9 &&
         MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - price) < _Point / 2) good = true;
   }
   if(good && cnt == 1) return;
   if(cnt > 0) DeletePendings();

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   string tag = StringFormat("%s L%d", InpComment, b.n + 1);

   // price already through the trigger (or too close for a pending): go to market instead
   if(wantBuy && ask >= price - minDist) { OpenMarket(true, lot, tag); return; }
   if(!wantBuy && bid <= price + minDist) { OpenMarket(false, lot, tag); return; }

   if(!MarginOK(wantType, lot, price)) { Print("Ironwall: margin check failed for pending ", tag); return; }
   bool ok = wantBuy ? trade.BuyStop(lot, price, _Symbol, 0, 0, ORDER_TIME_GTC, 0, tag)
                     : trade.SellStop(lot, price, _Symbol, 0, 0, ORDER_TIME_GTC, 0, tag);
   if(!ok) PrintFormat("Ironwall: pending %s failed %d", tag, trade.ResultRetcode());
}

// Video start: BUY STOP + SELL STOP at base lot, zone InpStepPoints wide, centred on price.
void PlaceStraddle()
{
   int c = CountPendings();
   if(c == 2) return;
   if(c > 0) DeletePendings();
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double mid = (ask + bid) / 2.0, half = InpStepPoints * _Point / 2.0;
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double bp = NormalizeDouble(mid + half, _Digits), sp = NormalizeDouble(mid - half, _Digits);
   if(bp - ask < minDist || bid - sp < minDist) { Print("Ironwall: zone too tight for broker stop level"); return; }
   double lot = NormLot(InpBaseLot);
   if(!MarginOK(ORDER_TYPE_BUY_STOP, lot, bp)) return;
   g_cycleEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   string tag = InpComment + " L1";
   if(!trade.BuyStop(lot, bp, _Symbol, 0, 0, ORDER_TIME_GTC, 0, tag))
      PrintFormat("Ironwall: straddle buy-stop failed %d", trade.ResultRetcode());
   if(!trade.SellStop(lot, sp, _Symbol, 0, 0, ORDER_TIME_GTC, 0, tag))
      PrintFormat("Ironwall: straddle sell-stop failed %d", trade.ResultRetcode());
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   Basket b; ReadBasket(b);

   // a new rung filling (or a new basket) invalidates the old trail
   if(b.n != g_lastN) { g_trailOn = false; g_peak = 0; g_lastN = b.n; }

   if(b.n == 0)
   {
      bool canStart = (g_pauseDay != dt.day_of_year)
                   && (TimeCurrent() - g_lastClose >= InpCooldownSec)
                   && (dt.hour >= InpStartHour && dt.hour < InpEndHour)
                   && (SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) <= InpMaxSpread)
                   && (InpStepPoints > SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * 2);
      if(!canStart) { if(CountPendings() > 0) DeletePendings(); return; }
      if(InpStraddle) { PlaceStraddle(); return; }
      if(CountPendings() > 0) DeletePendings();
      int sig = GetSignal();
      if(sig == 0) return;
      g_cycleEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      OpenMarket(sig > 0, NormLot(InpBaseLot), InpComment + " L1");
      return;
   }

   // ---- exits
   double k      = InpBaseLot / 0.01;
   double target = InpBasketTP * k;
   if(b.n > InpMaxLevel)
   {
      // deepest rung: get out at the exit level, no waiting
      if(b.profit >= InpMaxLevelExit) { CloseAll("max-level exit " + DoubleToString(b.profit, 2)); return; }
   }
   else if(!InpUseTrail)
   {
      if(b.profit >= target) { CloseAll("target " + DoubleToString(b.profit, 2)); return; }
   }
   else
   {
      // basket break-even / trailing: once in profit, the floor follows the peak upward
      if(!g_trailOn && b.profit >= target) { g_trailOn = true; g_peak = b.profit; }
      if(g_trailOn)
      {
         g_peak = MathMax(g_peak, b.profit);
         // trail distance is in PRICE (points) like the video's SL; convert to money via net lots
         double netLots  = MathAbs(b.buyLots - b.sellLots);
         double perPrice = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
         int    gapPts   = (b.n >= InpDeepFromPos) ? InpTrailGapDeep : InpTrailGapPoints;
         double gapMoney = gapPts * _Point * perPrice * netLots;
         if(gapMoney <= 0) gapMoney = 1.0 * k;        // fully balanced basket: fallback
         double floorP = MathMax(InpLockProfit * k, g_peak - gapMoney);
         if(b.profit <= floorP)
         { CloseAll("trail peak " + DoubleToString(g_peak, 2) + " exit " + DoubleToString(b.profit, 2)); return; }
      }
   }

   if(InpHardStopMoney > 0 && b.profit <= -InpHardStopMoney)
   { CloseAll("hard stop"); return; }

   if(InpMaxDDPct > 0 && g_cycleEquity > 0)
   {
      double dd = (g_cycleEquity - AccountInfoDouble(ACCOUNT_EQUITY)) / g_cycleEquity * 100.0;
      if(dd >= InpMaxDDPct)
      {
         CloseAll("equity DD " + DoubleToString(dd, 1) + "%");
         // Owner request: do NOT pause after a DD cut. The EA keeps trading.
         g_cycleEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         return;
      }
   }

   // ---- keep the next rung in place
   EnsurePending(b);
}
//+------------------------------------------------------------------+
