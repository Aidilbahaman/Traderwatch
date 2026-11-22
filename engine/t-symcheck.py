import json,sys
import MetaTrader5 as mt5
mt5.initialize()
out={}
for pat in ('DXY','USDX','DOLLAR','UST','US10','BOND','YIELD','TNX'):
    s=mt5.symbols_get(pat)
    out[pat]=[x.name for x in s][:8] if s else []
print(json.dumps(out,indent=1))
print('total symbols:',len(mt5.symbols_get() or []))
mt5.shutdown()
