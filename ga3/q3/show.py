import sqlite3, json
# ids = ["d_qanuimSQFQTnQ3ZcDV", "d_hvSU5u6LjMspAoHYRM", "d_XSXJyWHjU8GjytnTJ5", "d_cwPN2RfHPoE8tyV4mH"]
ids = ["d_uo3CFC6sbG839ATzAh", "d_AY8jDWDnHCLC6LzkVJ"]
c = sqlite3.connect("mailroom.db")
rows = [json.loads(r[0]) for r in c.execute("select dossier from pending")]
print("pending rows:", len(rows))
for d in rows:
    if d["dossierId"] in ids:
        print("=====", d["dossierId"], d["mailbox"], d.get("objective"))
        for s in d["sources"]:
            print("--", s["sourceId"], s.get("kind"), s.get("provenance"), s.get("title"))
            for l in s["lines"]:
                print(l["lineId"], l["text"])