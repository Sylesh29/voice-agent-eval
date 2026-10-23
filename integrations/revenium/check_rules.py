"""Print the cost controls the Revenium SDK can see, and each group's balance."""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))

from revenium_middleware._core import enforcement as E

got = E._fetch_rules()
if got is None:
    raise SystemExit("could not fetch rules: check REVENIUM_TEAM_ID, REVENIUM_ENFORCEMENT_BASE_URL and the API key")
rules = got[0] if isinstance(got, tuple) else getattr(got, "rules", got)
print(f"{len(rules)} enforced rule(s)" + ("" if rules else ": none saved with Enforce a hard stop on yet"))
for r in rules:
    print(f"\n{r.get('name')}  breached={r.get('breached')}  current={r.get('currentValue')}  "
          f"threshold={r.get('threshold')}  groupBy={r.get('groupBy')}")
    for g in r.get("groupBreakdown") or []:
        name = g.get("groupValue") or g.get("value") or g.get("key") or g
        print(f"   {str(name)[:40]:<40} {g.get('currentValue')}  breached={g.get('breached')}")
