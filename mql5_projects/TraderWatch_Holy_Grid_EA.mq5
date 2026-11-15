//+------------------------------------------------------------------+
//| TraderWatch Holy Grid EA                                         |
//| Educational example. Test on DEMO before any live deployment.   |
//| Designed for MT5 hedging accounts.                               |
//+------------------------------------------------------------------+
#property copyright "TraderWatch"
#property version   "1.09"
#property strict
#property description "EMA-seeded, two-sided adverse grid with basket exits and equity guards."

#include <Trade/Trade.mqh>
CTrade trade;

//--------------------------- INPUTS ---------------------------------
input group "01. General"
input ulong  InpMagic                 = 26111001;
input string InpTradeComment          = "TraderWatch Holy Grid";
input bool   InpAllowBuy              = true;
input bool   InpAllowSell             = true;
input bool   InpOneEntryPerBar        = true;
input ENUM_TIMEFRAMES InpSignalTF     = PERIOD_M1;
input int    InpMaxSpreadPoints       = 80;      // points, broker-specific
input int    InpDeviationPoints       = 30;

input group "02. Initial direction (EMA)"
input int    InpFastEMA               = 9;
input int    InpSlowEMA               = 21;

input group "03. Grid / aggressive profile"
input double InpStartLot              = 0.05;
input double InpLotMultiplier         = 1.00;    // fixed lot: no compounding
input double InpMaxLotPerOrder        = 0.05;
input int    InpGridStepPoints        = 300;     // 30 pips between grid layers
input int    InpMaxPositionsPerSide   = 10;      // includes first position
input double InpMaxTotalLots          = 0.10;    // 10 positions x fixed 0.01 lot
input double InpProfitLayerStepPrice  = 0.10;    // add next same-lot layer after favourable $0.10 move
input int    InpMaxTotalPositions     = 10;      // combined BUY+SELL layer cap
input bool   InpUseATRGridStep        = false;
input int    InpATRPeriod             = 14;
input double InpATRStepMultiplier     = 1.20;

input group "04. Basket exits (account currency)"
input double InpBasketTakeProfitMoney = 0.0;     // 0 = open (no money TP)
input double InpBasketStopLossMoney   = 0.0;     // 0 = disabled; set a positive loss amount
input double InpBasketTakeProfitPercent = 0.0;   // if >0, TP = this % of equity (override money)
input double InpBasketStopLossPercent  = 0.0;   // if >0, SL = this % of equity (override money)
input bool   InpCloseOppositeOnSignal = false;

input group "05. Account protection"
input double InpMaxEquityDrawdownPct  = 0.0;     // from EA start equity; closes EA positions and locks (set 0 to disable)
input double InpDrawdownMoneyDollar   = 50.00;   // dollar amount; if >0, trigger when drawdown >= this (override percent)
input double InpDailyLossLimitMoney   = 0.0;      // 0 = disabled; based on balance at day start (use dollar if needed)
input bool   InpCloseOnProtection     = true;

input group "06. Tiering (TraderWatch risk tiers)"
input bool   InpUseTiering            = true;    // auto lot / grid / basket / max positions from balance
input double InpTierRiskPct           = 0.0;     // 0 = use the tier's own risk %, >0 = override all tiers
input double InpLotMultTier           = 1.50;    // per-layer lot multiplier when tiering is on

input group "07. Trading schedule"
input bool   InpUseTradingHours       = false;
//+-----------------------------------------------------------+
//| Profit trailing guard (basket-level)                      |
//+-----------------------------------------------------------+
input group "09. Quant Runner & Breakeven"
input bool   InpUsePartialClose     = true;   // close half position at partial TP, let runner run
input double InpPartialProfitPct    = 1.50;   // equity % to trigger partial close (50%)
input bool   InpUseBreakevenShift   = true;   // move SL to breakeven when basket profit > BE threshold
input double InpBEProfitPct         = 1.00;   // equity % to trigger breakeven shift

input group "08. Profit guard / trailing"
input double InpProfitGuardPct        = 0.0;    // deprecated when point trailing is enabled
input double InpProfitGuardRetracePct = 0.0;    // 0 = use points instead of %
input int    InpProfitGuardStartPoints   = 100;   // arm after basket gains 100 points
input int    InpProfitGuardRetracePoints = 100;   // close after 100-point retrace from peak
input int    InpStopLossPoints            = 1000;  // broker SL: 100 pips ($10 price distance)
// v1.06 staged profit management. Distances are measured from the first entry.
input int    InpTrailBETriggerPts        = 150;   // move shared SL to BE + lock at +150 pts
input int    InpTrailBELockPts           = 30;    // lock this many points above/below anchor
input int    InpTrailMidTriggerPts       = 300;   // begin wider trailing at +300 pts
input int    InpTrailMidDistPts          = 180;   // mid-stage trailing distance
input int    InpTrailRunnerTriggerPts    = 600;   // runner stage at +600 pts
input int    InpTrailRunnerDistPts       = 250;   // runner trailing distance
input int    InpTrailModifyStepPts       = 50;    // only tighten after at least 50 pts improvement
input bool   InpUsePartialAt2R           = true;  // one-shot pro-rata partial close
input double InpPartialAt2RFrac          = 0.40;  // close 40% of every position at +2R
input int    InpStartHour             = 0;       // broker server time
input int    InpEndHour               = 24;      // exclusive; 24 means end of day

//--------------------------- STATE ----------------------------------
int fastHandle = INVALID_HANDLE, slowHandle = INVALID_HANDLE, atrHandle = INVALID_HANDLE;
datetime lastBarTime = 0;
double startEquity = 0.0, dayStartBalance = 0.0;
int dayOfYear = -1;
bool protectionLock = false;
// Total lots for one side (BUY or SELL)
double SideLots(ENUM_POSITION_TYPE side)
{
   double lots=0;
   for(int i=PositionsTotal()-1;i>=0;i--) {
      ulong t=PositionGetTicket(i); if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol || (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE)==side) lots+=PositionGetDouble(POSITION_VOLUME);
   }
   return lots;
}
int guardPeakIdx(ENUM_POSITION_TYPE side) { return (side == POSITION_TYPE_BUY ? 0 : 1); }
double guardPeak[2] = {0.0, 0.0};
bool   guardArmed[2] = {false, false};
// Track the initial entry of each independent basket for R-based partials.
static ulong trailAnchorTicket[2] = {0,0};
static double trailAnchorOpen[2] = {0,0};
static double trailAnchorSideSL[2] = {0,0};
static bool   trailPartialDone[2] = {false,false};

//--------------------------- TIERING --------------------------------
// Ported from engine/holy-grid-bridge.py TIERS table. Balance decides the row.
struct TierCfg
{
   string name;
   double risk;      // % of equity risked per grid step
   double gridPts;   // adverse distance between layers
   double maxLot;    // per-order ceiling
   double maxTotal;  // combined lots ceiling
   double basketTp;  // close a side at this net P/L (account currency)
   int    maxPos;    // max layers per side
};

TierCfg GetTier(double bal)
{
   TierCfg t;
   if(bal >= 1000.0)      { t.name="T5 Full";        t.risk=4.0; t.gridPts=300; t.maxLot=2.00; t.maxTotal=2.00; t.basketTp=10.00; t.maxPos=10; }
   else if(bal >= 600.0)  { t.name="T4 Established"; t.risk=4.0; t.gridPts=250; t.maxLot=0.50; t.maxTotal=1.00; t.basketTp=5.00;  t.maxPos=10; }
   else if(bal >= 300.0)  { t.name="T3 Scaling";     t.risk=3.0; t.gridPts=200; t.maxLot=0.25; t.maxTotal=0.40; t.basketTp=3.50;  t.maxPos=10; }
   else if(bal >= 100.0)  { t.name="T2 Growing";     t.risk=2.0; t.gridPts=150; t.maxLot=0.10; t.maxTotal=0.40; t.basketTp=2.00;  t.maxPos=10; }
   else                   { t.name="T1 Saver";       t.risk=1.0; t.gridPts=100; t.maxLot=0.01; t.maxTotal=0.03; t.basketTp=1.00;  t.maxPos=3;  }
   return t;
}

TierCfg EffCfg()
{
   TierCfg t = GetTier(AccountInfoDouble(ACCOUNT_BALANCE));
   if(InpTierRiskPct > 0) t.risk = InpTierRiskPct;
   if(!InpUseTiering)
   {
      t.name      = "Manual";
      t.gridPts   = InpGridStepPoints;
      t.maxLot    = InpMaxLotPerOrder;
      t.maxTotal  = InpMaxTotalLots;
      t.basketTp  = InpBasketTakeProfitMoney;
      t.maxPos    = InpMaxPositionsPerSide;
      if(InpTierRiskPct <= 0) t.risk = 7.0;
   }
   return t;
}

// money lost per 1.00 lot for one full grid step
double LossPerGridStep(const TierCfg &t)
{
   double tv  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts > 0) tv = tv * _Point / ts;      // normalise to "per point per lot"
   return t.gridPts * tv;
}

// Risk-based lot for layer n (0 = first entry), mirroring dynamic_lot() in the bridge.
double TierLot(const TierCfg &t, int layer)
{
   if(!InpUseTiering) return NormalizeVolumeRaw(InpStartLot, InpMaxLotPerOrder);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double lpg = LossPerGridStep(t);
   double mult = InpUseTiering ? InpLotMultTier : InpLotMultiplier;
   if(lpg <= 0 || eq <= 0) return NormalizeVolumeRaw(InpStartLot, t.maxLot);
   double riskMoney = eq * t.risk / 100.0;
   double lot = (riskMoney / lpg) * MathPow(mult, layer);
   double dynMax = MathMax(0.10, MathMin(20.0, bal / 500.0));   // smart dynamic cap (bridge parity)
   lot = MathMin(lot, MathMin(dynMax, t.maxLot));
   return NormalizeVolumeRaw(lot, t.maxLot);
}

//--------------------------- HELPERS --------------------------------
bool IsHedgingAccount()
{
   return (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
}

bool IsNewBar()
{
   datetime t = iTime(_Symbol, InpSignalTF, 0);
   if(t == 0) return false;
   if(t != lastBarTime) { lastBarTime = t; return true; }
   return false;
}

bool TradingTimeOK()
{
   if(!InpUseTradingHours) return true;
   MqlDateTime tm; TimeToStruct(TimeCurrent(), tm);
   if(InpStartHour == InpEndHour) return true;
   if(InpStartHour < InpEndHour)
      return (tm.hour >= InpStartHour && tm.hour < InpEndHour);
   return (tm.hour >= InpStartHour || tm.hour < InpEndHour);
}

bool SpreadOK()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return false;
   double spread = (tick.ask - tick.bid) / _Point;
   return (spread <= InpMaxSpreadPoints);
}

double NormalizeVolumeRaw(double lots, double cap)
{
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathMin(lots, MathMin(vmax, cap));
   lots = MathMax(lots, vmin);
   lots = MathFloor(lots / step + 1e-8) * step;
   int digits = 2;
   if(step >= 1.0) digits = 0;
   else if(step >= 0.1) digits = 1;
   else if(step >= 0.01) digits = 2;
   else digits = 3;
   return NormalizeDouble(lots, digits);
}

double NormalizeVolume(double lots)
{
   return NormalizeVolumeRaw(lots, EffCfg().maxLot);
}

int CountEAPositions()
{
   int n=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i); if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol && (ulong)PositionGetInteger(POSITION_MAGIC)==InpMagic) n++;
   }
   return n;
}

datetime lastProfitLayerTime=0;

int CountSide(ENUM_POSITION_TYPE side, double &lots, double &profit, double &lastPrice, datetime &lastTime)
{
   int count = 0; lots = 0; profit = 0; lastPrice = 0; lastTime = 0;
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != side) continue;

      count++;
      lots += PositionGetDouble(POSITION_VOLUME);
      profit += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      datetime pt = (datetime)PositionGetInteger(POSITION_TIME);
      if(pt >= lastTime) { lastTime = pt; lastPrice = PositionGetDouble(POSITION_PRICE_OPEN); }
   }
   return count;
}

double TotalEALots()
{
   double total = 0;
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         total += PositionGetDouble(POSITION_VOLUME);
   }
   return total;
}

void CloseSide(ENUM_POSITION_TYPE side)
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol ||
         (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == side)
         trade.PositionClose(ticket);
   }
}

void CloseAllEA()
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         trade.PositionClose(ticket);
   }
}

double CurrentGridStep()
{
   double step = EffCfg().gridPts * _Point;
   if(InpUseATRGridStep && atrHandle != INVALID_HANDLE)
   {
      double a[1];
      if(CopyBuffer(atrHandle, 0, 1, 1, a) == 1 && a[0] > 0)
         step = MathMax(step, a[0] * InpATRStepMultiplier);
   }
   return step;
}

int GetSignal()
{
   double f[1], s[1];
   if(CopyBuffer(fastHandle, 0, 1, 1, f) != 1) return 0;
   if(CopyBuffer(slowHandle, 0, 1, 1, s) != 1) return 0;
   if(f[0] > s[0]) return 1;
   if(f[0] < s[0]) return -1;
   return 0;
}

double MoneyForPoints(ENUM_POSITION_TYPE side,double lots,int points)
{
   if(lots<=0 || points<=0) return 0;
   MqlTick q; if(!SymbolInfoTick(_Symbol,q)) return 0;
   ENUM_ORDER_TYPE type=(side==POSITION_TYPE_BUY?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
   double from=(side==POSITION_TYPE_BUY?q.ask:q.bid);
   double to=(side==POSITION_TYPE_BUY?from+points*_Point:from-points*_Point);
   double profit=0;
   if(!OrderCalcProfit(type,_Symbol,lots,from,to,profit)) return 0;
   return MathAbs(profit);
}

// The oldest position is the anchor. All grid layers share its SL and its trailing distance.
// The SL only ratchets towards profit and is never widened when new layers enter.
// Return the oldest side's anchor, including when a new layer is older than the stored ticket.
bool FindAnchor(ENUM_POSITION_TYPE side,ulong &ticket,double &open,double &sl)
{
   datetime oldest=LONG_MAX; ticket=0; open=0; sl=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i); if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol || (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=side) continue;
      datetime pt=(datetime)PositionGetInteger(POSITION_TIME);
      if(pt<oldest)
      {
         oldest=pt; ticket=t;
         open=PositionGetDouble(POSITION_PRICE_OPEN);
         sl=PositionGetDouble(POSITION_SL);
      }
   }
   return ticket>0;
}

double BetterSL(ENUM_POSITION_TYPE side,double oldSL,double candidate)
{
   if(candidate<=0) return oldSL;
   if(oldSL<=0) return candidate;
   if(side==POSITION_TYPE_BUY) return MathMax(oldSL,candidate);
   return MathMin(oldSL,candidate);
}

void ManageStagedPartial(ENUM_POSITION_TYPE side,double anchorOpen,double initialSL)
{
   int gi=guardPeakIdx(side);
   if(!InpUsePartialAt2R || trailPartialDone[gi] || initialSL<=0 || InpPartialAt2RFrac<=0 || InpPartialAt2RFrac>=1) return;
   MqlTick q; if(!SymbolInfoTick(_Symbol,q)) return;
   double risk=MathAbs(anchorOpen-initialSL);
   if(risk<=0) return;
   double move=side==POSITION_TYPE_BUY?q.bid-anchorOpen:anchorOpen-q.ask;
   if(move < 2.0*risk) return;
   trailPartialDone[gi]=true; // prevent duplicate sends while partial deals are still being reported
   int closed=0,failed=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i); if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol || (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=side) continue;
      double vol=PositionGetDouble(POSITION_VOLUME);
      double closeVol=NormalizeVolumeRaw(vol*InpPartialAt2RFrac,vol);
      if(closeVol<=0 || closeVol>=vol) continue;
      if(!trade.PositionClosePartial(ticket,closeVol)) { failed++; trailPartialDone[gi]=false; }
      else closed++;
   }
   Print("PARTIAL 2R side=",side==POSITION_TYPE_BUY?"BUY":"SELL"," fraction=",InpPartialAt2RFrac," closed=",closed," failed=",failed," anchorOpen=",anchorOpen);
}

// Every layer follows the first entry's staged SL; trailing only tightens, never widens.
void ManageBrokerSL()
{
   // No initial SL in no-SL mode; staged profit trail can still arm after trigger.
   MqlTick q; if(!SymbolInfoTick(_Symbol,q)) return;
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double minGap=MathMax((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),
                        (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL))*_Point+_Point;
   for(int pass=0;pass<2;pass++)
   {
      ENUM_POSITION_TYPE side=pass==0?POSITION_TYPE_BUY:POSITION_TYPE_SELL;
      int gi=guardPeakIdx(side);
      ulong anchor=0; double anchorOpen=0,anchorSL=0;
      if(!FindAnchor(side,anchor,anchorOpen,anchorSL)) { trailAnchorTicket[gi]=0; trailAnchorOpen[gi]=0; trailAnchorSideSL[gi]=0; trailPartialDone[gi]=false; continue; }
      if(trailAnchorTicket[gi]!=anchor)
      {
         trailAnchorTicket[gi]=anchor; trailAnchorOpen[gi]=anchorOpen; trailAnchorSideSL[gi]=anchorSL; trailPartialDone[gi]=false;
         Print("TRAIL ANCHOR side=",side==POSITION_TYPE_BUY?"BUY":"SELL"," ticket=",anchor," open=",anchorOpen," initialSL=",anchorSL);
      }
      double sl=anchorSL;
      if(sl<=0 && InpStopLossPoints>0)
         sl=NormalizeDouble(side==POSITION_TYPE_BUY?anchorOpen-InpStopLossPoints*_Point:anchorOpen+InpStopLossPoints*_Point,digits);
      // Never replace an already-improved SL with a staged candidate that is worse.
      double initial=trailAnchorSideSL[gi]>0?trailAnchorSideSL[gi]:sl;
      ManageStagedPartial(side,trailAnchorOpen[gi],initial);
      double favourable=side==POSITION_TYPE_BUY?q.bid-trailAnchorOpen[gi]:trailAnchorOpen[gi]-q.ask;
      double candidate=0;
      if(favourable>=InpTrailRunnerTriggerPts*_Point)
         candidate=side==POSITION_TYPE_BUY?q.bid-InpTrailRunnerDistPts*_Point:q.ask+InpTrailRunnerDistPts*_Point;
      else if(favourable>=InpTrailMidTriggerPts*_Point)
         candidate=side==POSITION_TYPE_BUY?q.bid-InpTrailMidDistPts*_Point:q.ask+InpTrailMidDistPts*_Point;
      else if(favourable>=InpTrailBETriggerPts*_Point)
         candidate=side==POSITION_TYPE_BUY?trailAnchorOpen[gi]+InpTrailBELockPts*_Point:trailAnchorOpen[gi]-InpTrailBELockPts*_Point;
      if(candidate>0)
      {
         candidate=NormalizeDouble(candidate,digits);
         // 50-point modification step avoids repeated micro-adjustments. Initial SL is always allowed.
         bool enough=(sl<=0 || MathAbs(candidate-sl)>=InpTrailModifyStepPts*_Point);
         if(enough) sl=BetterSL(side,sl,candidate);
      }
      if(sl<=0) continue;
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong ticket=PositionGetTicket(i); if(ticket==0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol || (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
         if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=side) continue;
         double old=PositionGetDouble(POSITION_SL);
         if(old>0 && ((side==POSITION_TYPE_BUY && old>=sl-_Point*0.5) || (side==POSITION_TYPE_SELL && old<=sl+_Point*0.5))) continue;
         if(side==POSITION_TYPE_BUY && q.bid-sl<minGap) continue;
         if(side==POSITION_TYPE_SELL && sl-q.ask<minGap) continue;
         if(!trade.PositionModify(ticket,sl,0)) Print("STAGED SHARED SL FAILED ticket=",ticket," retcode=",trade.ResultRetcode());
         else Print("STAGED SHARED SL ticket=",ticket," anchor=",anchor," sl=",DoubleToString(sl,digits));
      }
   }
}

bool OpenMarket(ENUM_ORDER_TYPE type, double lots)
{
   TierCfg cfg = EffCfg();
   lots = NormalizeVolumeRaw(lots, cfg.maxLot);
   if(lots <= 0 || TotalEALots() + lots > cfg.maxTotal + 1e-8) return false;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   MqlTick q; if(!SymbolInfoTick(_Symbol,q)) return false;
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double sl=0; // Grid layers inherit the first entry SL in ManageBrokerSL.
   bool ok = false;
   if(type == ORDER_TYPE_BUY)
      ok = trade.Buy(lots, _Symbol, 0, sl, 0, InpTradeComment);
   else if(type == ORDER_TYPE_SELL)
      ok = trade.Sell(lots, _Symbol, 0, sl, 0, InpTradeComment);
   if(!ok)
      Print("Order failed. retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   return ok;
}

void UpdateDailyBaseline()
{
   MqlDateTime tm; TimeToStruct(TimeCurrent(), tm);
   if(dayOfYear != tm.day_of_year)
   {
      dayOfYear = tm.day_of_year;
      dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   }
}

bool CheckProtection()
{
   UpdateDailyBaseline();
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double ddPct = (startEquity > 0) ? (startEquity - equity) / startEquity * 100.0 : 0;
   double dailyLoss = dayStartBalance - AccountInfoDouble(ACCOUNT_EQUITY);

   bool hitDD = false;
   if(InpDrawdownMoneyDollar > 0.0 && (startEquity - equity) >= InpDrawdownMoneyDollar) hitDD = true;
   else if(InpMaxEquityDrawdownPct > 0.0 && ddPct >= InpMaxEquityDrawdownPct) hitDD = true;
   bool hitDaily = (InpDailyLossLimitMoney > 0 && dailyLoss >= InpDailyLossLimitMoney);

if(hitDD || hitDaily)
   {
      if(!protectionLock)
      {
         if(InpDrawdownMoneyDollar > 0.0)
         {
            Print("PROTECTION TRIGGERED. DD $=", DoubleToString(startEquity - equity,2));
            Print(" (", DoubleToString(ddPct,2), "%)");
         }
         else
         {
            Print("PROTECTION TRIGGERED. Equity DD=", DoubleToString(ddPct,2));
            Print(" % daily loss=", DoubleToString(dailyLoss,2));
         }
      }
      protectionLock = true;
      if(InpCloseOnProtection)
         CloseAllEA();
      return true;
   }
   return protectionLock;
}

//--- Quant Quant Helpers ---
void ApplyQuantManagement(ENUM_POSITION_TYPE side, double profit)
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq <= 0) return;

   // 1. Breakeven Shift
   if(false && InpUseBreakevenShift && profit >= eq * InpBEProfitPct / 100.0)
   {
      for(int i=PositionsTotal()-1; i>=0; --i)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != side) continue;
         
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl = PositionGetDouble(POSITION_SL);
         // If SL not yet at open price, move it
         if(side == POSITION_TYPE_BUY && (sl < openPrice))
            trade.PositionModify(ticket, openPrice, PositionGetDouble(POSITION_TP));
         else if(side == POSITION_TYPE_SELL && (sl > openPrice || sl == 0))
            trade.PositionModify(ticket, openPrice, PositionGetDouble(POSITION_TP));
      }
   }
}

void ManageBasket(ENUM_POSITION_TYPE side)
{
   double lots, profit, lastPrice; datetime lastTime;
   int count = CountSide(side, lots, profit, lastPrice, lastTime);
   if(count == 0)
   {
      int gi = guardPeakIdx(side);
      guardPeak[gi] = 0.0;
      guardArmed[gi] = false;
      return;
   }

   // v1.04: no basket money-close. All layers follow only the first entry's shared trailing SL.
   TierCfg cfg = EffCfg();
   double targetTP = cfg.basketTp;
   if(InpBasketTakeProfitPercent > 0.0) targetTP = AccountInfoDouble(ACCOUNT_EQUITY) * InpBasketTakeProfitPercent / 100.0;
   if(InpProfitGuardPct <= 0.0 && targetTP > 0 && profit >= targetTP) // hard TP disabled while profit guard is on
   {
      PrintFormat("BASKET-TP %s profit=%.2f target=%.2f tier=%s", side==POSITION_TYPE_BUY?"BUY":"SELL", profit, targetTP, cfg.name);
      CloseSide(side);
      return;
   }
   double targetSL = InpBasketStopLossMoney;
   if(InpBasketStopLossPercent > 0.0) targetSL = AccountInfoDouble(ACCOUNT_EQUITY) * InpBasketStopLossPercent / 100.0;
   if(targetSL > 0 && profit <= -targetSL)
   {
      PrintFormat("BASKET-SL %s loss=%.2f target=%.2f tier=%s", side==POSITION_TYPE_BUY?"BUY":"SELL", -profit, targetSL, cfg.name);
      CloseSide(side);
      return;
   }
   if(InpBasketStopLossMoney > 0 && profit <= -InpBasketStopLossMoney)
   {
      CloseSide(side);
      return;
   }
}

void ManageGridSide(ENUM_POSITION_TYPE side, bool enabled)
{
   if(!enabled) return;
   TierCfg cfg = EffCfg();
   double lots, profit, lastPrice; datetime lastTime;
   int count = CountSide(side, lots, profit, lastPrice, lastTime);
   if(count <= 0 || count >= cfg.maxPos) return;
   if(CountEAPositions() >= InpMaxTotalPositions) return;
   if(TotalEALots() >= cfg.maxTotal - 1e-8) return;
   if(lastProfitLayerTime != 0 && (TimeCurrent()-lastProfitLayerTime) < 2) return;

   MqlTick tick; if(!SymbolInfoTick(_Symbol, tick)) return;
   double step = InpProfitLayerStepPrice;
   if(step <= 0) return;
   // Pyramiding only: add in the direction of profit, never against the position.
   bool favourable = false;
   if(side == POSITION_TYPE_BUY) favourable = (tick.bid >= lastPrice + step);
   if(side == POSITION_TYPE_SELL) favourable = (tick.ask <= lastPrice - step);
   if(!favourable) return;

   double nextLot = NormalizeVolumeRaw(InpStartLot, InpMaxLotPerOrder);
   if(nextLot <= 0 || TotalEALots() + nextLot > cfg.maxTotal + 1e-8) return;
   PrintFormat("PROFIT-LAYER %s layer=%d lot=%.2f step=$%.2f totalPos=%d/%d",
      side==POSITION_TYPE_BUY?"BUY":"SELL", CountEAPositions()+1, nextLot, step, CountEAPositions(), InpMaxTotalPositions);
   if(OpenMarket(side == POSITION_TYPE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, nextLot))
      lastProfitLayerTime=TimeCurrent();
}
void DrawStatus()
{
   double bl, bp, lp; datetime lt;
   int buys = CountSide(POSITION_TYPE_BUY, bl, bp, lp, lt);
   double sl, sp; int sells = CountSide(POSITION_TYPE_SELL, sl, sp, lp, lt);
   Comment("TraderWatch Holy Grid EA\n",
           "Symbol: ", _Symbol, " | TF: ", EnumToString(InpSignalTF), "\n",
           "BUY: ", buys, " positions | P/L: ", DoubleToString(bp,2), "\n",
           "SELL: ", sells, " positions | P/L: ", DoubleToString(sp,2), "\n",
           "EA lots: ", DoubleToString(TotalEALots(),2), "\n",
           "Equity: ", DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2),
           " | Status: ", protectionLock ? "LOCKED - PROTECTION" : "ACTIVE");
}

//--------------------------- EVENTS ---------------------------------
int OnInit()
{
   if(!IsHedgingAccount())
   {
      Print("This EA requires an MT5 HEDGING account. Netting accounts are not supported.");
      return INIT_FAILED;
   }
   if(InpFastEMA < 1 || InpSlowEMA <= InpFastEMA || InpGridStepPoints < 1 ||
      InpMaxPositionsPerSide < 1 || InpLotMultiplier < 1.0 || InpStopLossPoints < 0 || InpProfitGuardStartPoints < 1 || InpProfitGuardRetracePoints < 1)
   {
      Print("Invalid inputs. Check EMA, grid step, position count and multiplier.");
      return INIT_PARAMETERS_INCORRECT;
   }

   fastHandle = iMA(_Symbol, InpSignalTF, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   slowHandle = iMA(_Symbol, InpSignalTF, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(InpUseATRGridStep) atrHandle = iATR(_Symbol, InpSignalTF, InpATRPeriod);
   if(fastHandle == INVALID_HANDLE || slowHandle == INVALID_HANDLE ||
      (InpUseATRGridStep && atrHandle == INVALID_HANDLE))
      return INIT_FAILED;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   startEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   MqlDateTime tm; TimeToStruct(TimeCurrent(), tm); dayOfYear = tm.day_of_year;
   protectionLock = false;
   lastBarTime = iTime(_Symbol, InpSignalTF, 0);

   SymbolSelect(_Symbol, true);
   EventSetTimer(1);   // headless Wine: chart may never tick, drive the cycle from a timer
   Print("Holy Grid v1.09 initialized STAGED_TRAIL BE=",InpTrailBETriggerPts,"/",InpTrailBELockPts," mid=",InpTrailMidTriggerPts,"/",InpTrailMidDistPts," runner=",InpTrailRunnerTriggerPts,"/",InpTrailRunnerDistPts," step=",InpTrailModifyStepPts," partial2R=",InpUsePartialAt2R," fraction=",InpPartialAt2RFrac," FIXED lot=",InpStartLot," multiplier=",InpLotMultiplier," gridPts=",InpGridStepPoints," maxPos=",InpMaxPositionsPerSide," maxTotal=",InpMaxTotalLots," profitLayer=$",InpProfitLayerStepPrice," maxTotalPos=",InpMaxTotalPositions," SLpts=",InpStopLossPoints," basketTPmoney=",InpBasketTakeProfitMoney," basketTPpct=",InpBasketTakeProfitPercent," basketSLpct=",InpBasketStopLossPercent," trailStartPts=",InpProfitGuardStartPoints," trailRetracePts=",InpProfitGuardRetracePoints," tiering=",InpUseTiering);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(fastHandle != INVALID_HANDLE) IndicatorRelease(fastHandle);
   if(slowHandle != INVALID_HANDLE) IndicatorRelease(slowHandle);
   if(atrHandle != INVALID_HANDLE) IndicatorRelease(atrHandle);
   Comment("");
}

void RunCycle()
{
   DrawStatus();
   ManageBrokerSL();

   ApplyQuantManagement(POSITION_TYPE_BUY, 0.0);
   ApplyQuantManagement(POSITION_TYPE_SELL, 0.0);
   ManageBasket(POSITION_TYPE_BUY);
   ManageBasket(POSITION_TYPE_SELL);

   if(CheckProtection()) return;
   if(!TradingTimeOK() || !SpreadOK()) return;

   // Add grid orders on every qualifying tick; initial entries are evaluated once per bar.
   ManageGridSide(POSITION_TYPE_BUY, InpAllowBuy);
   ManageGridSide(POSITION_TYPE_SELL, InpAllowSell);

   if(InpOneEntryPerBar && !IsNewBar()) return;
   if(!InpOneEntryPerBar) { /* signal still uses closed candle */ }

   int signal = GetSignal();
   double bl, bp, lp; datetime lt;
   int buyCount = CountSide(POSITION_TYPE_BUY, bl, bp, lp, lt);
   double sl, sp; int sellCount = CountSide(POSITION_TYPE_SELL, sl, sp, lp, lt);

   if(signal > 0 && InpAllowBuy && buyCount == 0)
   {
      if(InpCloseOppositeOnSignal && sellCount > 0) CloseSide(POSITION_TYPE_SELL);
      { TierCfg c0 = EffCfg(); double lot0 = TierLot(c0, 0);
        PrintFormat("INITIAL-BUY lot=%.2f tier=%s risk=%.1f%% grid=%.0fpts tp=%.2f maxPos=%d",
           lot0, c0.name, c0.risk, c0.gridPts, c0.basketTp, c0.maxPos);
        OpenMarket(ORDER_TYPE_BUY, lot0); }
   }
   else if(signal < 0 && InpAllowSell && sellCount == 0)
   {
      if(InpCloseOppositeOnSignal && buyCount > 0) CloseSide(POSITION_TYPE_BUY);
      { TierCfg c1 = EffCfg(); double lot1 = TierLot(c1, 0);
        PrintFormat("INITIAL-SELL lot=%.2f tier=%s risk=%.1f%% grid=%.0fpts tp=%.2f maxPos=%d",
           lot1, c1.name, c1.risk, c1.gridPts, c1.basketTp, c1.maxPos);
        OpenMarket(ORDER_TYPE_SELL, lot1); }
   }
}

void OnTick()
{
   EMATrendGuard();
   RunCycle();
}

void OnTimer()
{
   RunCycle();
}

//+------------------------------------------------------------------+


//+------------------------------------------------------------------+
//| EMA Trend Guard: close all EA positions when trend flips           |
//+------------------------------------------------------------------+
static int hEMAFast_ = INVALID_HANDLE;
static int hEMASlow_ = INVALID_HANDLE;
static int lastTrend_ = 0;

void EMATrendGuard()
{
   if(hEMAFast_ == INVALID_HANDLE) hEMAFast_ = iMA(_Symbol, PERIOD_M1, 9, 0, MODE_EMA, PRICE_CLOSE);
   if(hEMASlow_ == INVALID_HANDLE) hEMASlow_ = iMA(_Symbol, PERIOD_M1, 21, 0, MODE_EMA, PRICE_CLOSE);
   if(hEMAFast_ == INVALID_HANDLE || hEMASlow_ == INVALID_HANDLE) return;

   double fa[], sa[];
   if(CopyBuffer(hEMAFast_, 0, 1, 1, fa) <= 0) return;
   if(CopyBuffer(hEMASlow_, 0, 1, 1, sa) <= 0) return;

   int cur = (fa[0] > sa[0]) ? 1 : -1;
   if(lastTrend_ != 0 && cur != lastTrend_)
   {
      Print("EMA Trend Guard: trend flipped - closing all Holy Grid positions.");
      CloseAllEAPositions();
   }
   lastTrend_ = cur;
}

void CloseAllEAPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      // close all EA positions on this symbol (exclude manager safety is handled by magic below)
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      trade.PositionClose(ticket);
   }
}

