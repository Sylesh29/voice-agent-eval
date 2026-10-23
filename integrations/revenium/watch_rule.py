"""Poll the cost control until any customer is marked breached (or give up)."""
import datetime
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))
from revenium_middleware._core import enforcement as E

tries = int(sys.argv[1]) if len(sys.argv) > 1 else 30
for _ in range(tries):
    g = E._fetch_rules()
    rules = g[0] if isinstance(g, tuple) else g.rules
    for r in rules:
        bd = r.get("groupBreakdown") or []
        groups = [(x.get("groupValue") or x.get("groupKey") or x.get("value"), x.get("currentValue"), x.get("breached")) for x in bd]
        print(datetime.datetime.now().strftime("%H:%M:%S"), r["name"], "compiled", str(r.get("compiledAt"))[11:19],
              "current", r.get("currentValue"), "breached", r.get("breached"), groups, flush=True)
        if r.get("breached") or any(x.get("breached") for x in bd):
            print("BREACHED", flush=True)
            print(bd or r, flush=True)
            sys.exit(0)
    time.sleep(60)
sys.exit("not breached yet")
