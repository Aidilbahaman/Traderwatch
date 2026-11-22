#include <Trade/Trade.mqh>
CTrade trade;

input int    InpPositions   = 4;
input bool   InpAutoLot     = true;
input double InpLotPer1000  = 0.01;  // Lot bertambah mengikut setiap $1000 balance
input double InpLot         = 0.01;  // Lot tetap jika AutoLot = false
input int    InpTPPoints    = 40;
input int    InpSLPoints    = 150;
input double InpBasketProfit= 0;
input int    InpMaxSpread   = 25;
input int    InpCooldownSec = 3;
input double InpDailyLossPct= 5.0;
input int    InpMaxSlippage = 10;
input int    InpStartHour   = 8;
input int    InpEndHour     = 20;
input ulong  InpMagic       = 20261109;

int hFast, hSlow;
datetime lastCloseTime = 0;
double dayStartBalance = 0;
int dayOfYear = -1;

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippage);
   hFast = iMA(_Symbol, _Period, 8,  0, MODE_EMA, PRICE_CLOSE);
   hSlow = iMA(_Symbol, _Period, 21, 0, MODE_EMA, PRICE_CLOSE);
   return INIT_SUCCEEDED;
}

double GetDynamicLot()
{
   if(!InpAutoLot) return InpLot;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double lot = (balance / 1000.0) * InpLotPer1000;
   
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   
   if(lot < minLot) lot = minLot;
   if(lot > maxLot) lot = maxLot;
   
   if(step > 0)
      lot = NormalizeDouble(MathRound(lot / step) * step, 2);
   return lot;
}

int CountPositions()
{
   int n = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) &&
         PositionGetInteger(POSITION_MAGIC) == (long)InpMagic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol) n++;
   }
   return n;
}

double BasketProfit()
{
   double p = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) &&
         PositionGetInteger(POSITION_MAGIC) == (long)InpMagic)
         p += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return p;
}

void CloseAll()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) &&
         PositionGetInteger(POSITION_MAGIC) == (long)InpMagic)
         trade.PositionClose(t);
   }
}

int GetSignal()
{
   double f[2], s[2];
   if(CopyBuffer(hFast,0,0,2,f)<2 || CopyBuffer(hSlow,0,0,2,s)<2) return 0;
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(f[1] > s[1] && price > f[1]) return +1;
   if(f[1] < s[1] && price < f[1]) return -1;
   return 0;
}

bool DailyLossHit()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != dayOfYear)
   { dayOfYear = dt.day_of_year; dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE); }
   if(InpDailyLossPct <= 0) return false;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   return (dayStartBalance - eq) / dayStartBalance * 100.0 >= InpDailyLossPct;
}

void OnTick()
{
   if(DailyLossHit()) { CloseAll(); return; }

   int open = CountPositions();

   if(open > 0)
   {
      if(InpBasketProfit > 0 && BasketProfit() >= InpBasketProfit) CloseAll();
      lastCloseTime = TimeCurrent();
      return;
   }

   if(TimeCurrent() - lastCloseTime < InpCooldownSec) return;

   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpread) return;

   int sig = GetSignal();
   if(sig == 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = _Point;
   double lotToUse = GetDynamicLot();

   for(int i = 0; i < InpPositions; i++)
   {
      if(sig > 0)
      {
         double sl = InpSLPoints > 0 ? ask - InpSLPoints*pt : 0;
         trade.Buy(lotToUse, _Symbol, ask, sl, ask + InpTPPoints*pt);
      }
      else
      {
         double sl = InpSLPoints > 0 ? bid + InpSLPoints*pt : 0;
         trade.Sell(lotToUse, _Symbol, bid, sl, bid - InpTPPoints*pt);
      }
   }
}
