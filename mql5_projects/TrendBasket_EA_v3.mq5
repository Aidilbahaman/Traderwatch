//+------------------------------------------------------------------+
//|  TrendBasket_EA_v3.mq5                                           |
//|  Dipertingkat: 5% Risk-based Lot Sizing + TP/SL Seimbang (150pts) |
//|  + BreakEven + Trailing + Basket Lock + ATR / Spread Guard       |
//+------------------------------------------------------------------+
#property version "3.00"
#property strict
#include <Trade/Trade.mqh>
CTrade trade;

//--- Saiz & Risiko (5% Risk Model)
input int    InpPositions        = 4;       // Bilangan posisi setiap signal
input bool   InpAutoLot          = true;    // Guna Risk-based Lot Sizing
input double InpRiskPct          = 5.0;     // Risiko jumlah equity per kitaran (%)
input double InpFixedLot         = 0.01;    // Lot tetap jika AutoLot = false

//--- TP / SL (points; XAUUSD: 150 points = 15 pips)
input int    InpTPPoints         = 150;     // TP posisi pertama
input double InpTPStepMult       = 0.5;     // TP posisi seterusnya = TP x (1 + i x nilai ni)
input int    InpSLPoints         = 150;     // SL (sama jarak dengan TP)

//--- Kunci profit
input int    InpBETrigger        = 80;      // Pindah SL ke break-even bila profit >= points
input int    InpBEBuffer         = 10;      // Lebihan di atas spread bila BE (points)
input int    InpTrailStart       = 100;     // Mula trailing bila profit >= points
input int    InpTrailDist        = 50;      // Jarak trailing dari harga (points)
input int    InpTrailStep        = 5;       // Langkah minimum ubah SL (points)
input double InpBasketStartUSD   = 1.0;     // Basket lock: aktif bila peak profit >= USD ni
input int    InpBasketGivebackPct= 40;      // Tutup semua bila profit jatuh sekian % dari peak
input double InpBasketProfit     = 0;       // Tutup semua bila profit >= USD (0 = off)

//--- Penapis kemasukan
input int    InpMaxSpread        = 25;      // Spread maksimum (points)
input double InpMinTPSpreadRatio = 3.0;     // TP mesti >= spread x nilai ni
input int    InpADXMin           = 20;      // ADX minimum (elak pasaran sideways)
input int    InpCooldownSec      = 60;      // Rehat selepas semua posisi tutup
input int    InpStartHour        = 8;
input int    InpEndHour          = 20;

//--- Lain
input double InpDailyLossPct     = 5.0;     // Berhenti hari ini bila rugi % ni (0 = off)
input int    InpMaxSlippage      = 10;
input ulong  InpMagic            = 20261110;

int      hFast, hSlow, hADX;
datetime lastCloseTime = 0, lastEntryBar = 0;
double   dayStartBalance = 0, basketPeak = 0;
int      dayOfYear = -1;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   hFast = iMA(_Symbol, _Period, 8,  0, MODE_EMA, PRICE_CLOSE);
   hSlow = iMA(_Symbol, _Period, 21, 0, MODE_EMA, PRICE_CLOSE);
   hADX  = iADX(_Symbol, _Period, 14);
   if(hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE || hADX == INVALID_HANDLE)
      return INIT_FAILED;
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(hFast); IndicatorRelease(hSlow); IndicatorRelease(hADX);
   Comment("");
}

//+------------------------------------------------------------------+
//  Pengiraan Lot Dinamik berdasarkan 5% Risiko Equity
//+------------------------------------------------------------------+
double GetRiskBasedLot(double slDistancePoints)
{
   if(!InpAutoLot) return InpFixedLot;
   
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double totalRiskMoney = equity * (InpRiskPct / 100.0);
   double riskPerPosition = totalRiskMoney / MathMax(1, InpPositions);
   
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0) tickSize = _Point;
   if(tickValue <= 0) tickValue = 1.0; // Anggaran default jika kosong
   
   double lossPerLot = (slDistancePoints * _Point / tickSize) * tickValue;
   if(lossPerLot <= 0) return 0.01;
   
   double lot = riskPerPosition / lossPerLot;
   
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st > 0) lot = MathFloor(lot / st + 1e-9) * st;
   lot = MathMax(mn, MathMin(mx, lot));
   return NormalizeDouble(lot, 2);
}

double MinDist()
{
   long lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long frz = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   return (MathMax(lvl, frz) + 2) * _Point;
}

bool IsMine(ulong t)
{
   if(t == 0 || !PositionSelectByTicket(t)) return false;
   return PositionGetInteger(POSITION_MAGIC) == (long)InpMagic &&
          PositionGetString(POSITION_SYMBOL) == _Symbol;
}

int CountPositions()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(IsMine(PositionGetTicket(i))) n++;
   return n;
}

double BasketProfit()
{
   double p = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(IsMine(PositionGetTicket(i)))
         p += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   return p;
}

void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(IsMine(t)) trade.PositionClose(t);
   }
}

//+------------------------------------------------------------------+
void ManagePositions()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double pt  = _Point, minD = MinDist();
   double spr = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(!IsMine(t)) continue;

      long   type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double prof = (bid - open) / pt;
         if(InpBETrigger > 0 && prof >= InpBETrigger)
         {
            double be = open + (spr + InpBEBuffer) * pt;
            if(newSL == 0 || be > newSL) newSL = be;
         }
         if(InpTrailStart > 0 && InpTrailDist > 0 && prof >= InpTrailStart)
         {
            double tr = bid - InpTrailDist * pt;
            if(newSL == 0 || tr > newSL) newSL = tr;
         }
         newSL = NormalizeDouble(newSL, _Digits);
         if(newSL > 0 && newSL != sl && (sl == 0 || newSL - sl >= InpTrailStep * pt) && bid - newSL >= minD)
            trade.PositionModify(t, newSL, tp);
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double prof = (open - ask) / pt;
         if(InpBETrigger > 0 && prof >= InpBETrigger)
         {
            double be = open - (spr + InpBEBuffer) * pt;
            if(newSL == 0 || be < newSL) newSL = be;
         }
         if(InpTrailStart > 0 && InpTrailDist > 0 && prof >= InpTrailStart)
         {
            double tr = ask + InpTrailDist * pt;
            if(newSL == 0 || tr < newSL) newSL = tr;
         }
         newSL = NormalizeDouble(newSL, _Digits);
         if(newSL > 0 && newSL != sl && (sl == 0 || sl - newSL >= InpTrailStep * pt) && newSL - ask >= minD)
            trade.PositionModify(t, newSL, tp);
      }
   }
}

//+------------------------------------------------------------------+
int GetSignal()
{
   double f[3], s[3], adx[2], pdi[2], mdi[2];
   ArraySetAsSeries(f, true); ArraySetAsSeries(s, true);
   ArraySetAsSeries(adx, true); ArraySetAsSeries(pdi, true); ArraySetAsSeries(mdi, true);
   if(CopyBuffer(hFast, 0, 0, 3, f) < 3 || CopyBuffer(hSlow, 0, 0, 3, s) < 3) return 0;
   if(CopyBuffer(hADX, 0, 0, 2, adx) < 2 || CopyBuffer(hADX, 1, 0, 2, pdi) < 2 ||
      CopyBuffer(hADX, 2, 0, 2, mdi) < 2) return 0;

   double c1 = iClose(_Symbol, _Period, 1);
   if(adx[1] < InpADXMin) return 0;

   if(f[1] > s[1] && f[1] > f[2] && c1 > f[1] && pdi[1] > mdi[1]) return +1;
   if(f[1] < s[1] && f[1] < f[2] && c1 < f[1] && mdi[1] > pdi[1]) return -1;
   return 0;
}

bool DailyLossHit()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != dayOfYear)
   { dayOfYear = dt.day_of_year; dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE); }
   if(InpDailyLossPct <= 0 || dayStartBalance <= 0) return false;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   return (dayStartBalance - eq) / dayStartBalance * 100.0 >= InpDailyLossPct;
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(DailyLossHit()) { CloseAll(); Comment("Had rugi harian tercapai - berhenti"); return; }

   int open = CountPositions();

   if(open > 0)
   {
      ManagePositions();

      double bp = BasketProfit();
      if(bp > basketPeak) basketPeak = bp;

      bool closeNow = false;
      if(InpBasketProfit > 0 && bp >= InpBasketProfit) closeNow = true;
      if(InpBasketStartUSD > 0 && basketPeak >= InpBasketStartUSD &&
         bp <= basketPeak * (1.0 - InpBasketGivebackPct / 100.0)) closeNow = true;

      Comment("Posisi: ", open, "  Basket: ", DoubleToString(bp, 2),
              "  Peak: ", DoubleToString(basketPeak, 2));
      if(closeNow) CloseAll();
      lastCloseTime = TimeCurrent();
      return;
   }

   basketPeak = 0;
   Comment("Menunggu signal...");

   if(TimeCurrent() - lastCloseTime < InpCooldownSec) return;

   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return;

   double spreadPts = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spreadPts > InpMaxSpread) return;
   if(InpTPPoints < spreadPts * InpMinTPSpreadRatio) return;

   datetime barTime = iTime(_Symbol, _Period, 0);
   if(barTime == lastEntryBar) return;

   int sig = GetSignal();
   if(sig == 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = _Point, minD = MinDist() / pt;
   
   // Kira lot dinamik mengikut risiko 5% dan jarak SL (150 points)
   double slP = InpSLPoints > 0 ? MathMax((double)InpSLPoints, minD) : 0;
   double lot = GetRiskBasedLot(slP);

   for(int i = 0; i < InpPositions; i++)
   {
      double tpP = MathMax(InpTPPoints * (1.0 + i * InpTPStepMult), minD);
      bool ok;
      if(sig > 0)
      {
         double sl = slP > 0 ? NormalizeDouble(ask - slP * pt, _Digits) : 0;
         ok = trade.Buy(lot, _Symbol, ask, sl, NormalizeDouble(ask + tpP * pt, _Digits));
      }
      else
      {
         double sl = slP > 0 ? NormalizeDouble(bid + slP * pt, _Digits) : 0;
         ok = trade.Sell(lot, _Symbol, bid, sl, NormalizeDouble(bid - tpP * pt, _Digits));
      }
      if(!ok) break;
      if(i == 0) lastEntryBar = barTime;
   }
}
//+------------------------------------------------------------------+