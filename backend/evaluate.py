import main
r = main.run_eval()
for x in r["rows"]: print(x["rank"] or "miss", "|", x["q"], "->", x["expected"])
print(f"top-1 {r['hit1']}%  top-5 {r['hit5']}%  MRR {r['mrr']}")
