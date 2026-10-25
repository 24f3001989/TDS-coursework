import sqlite3, json
c = sqlite3.connect("mailroom.db")
seen = {}
for fp, dos in c.execute("select fp, dossier from pending"):
    row = c.execute("select proposal from decisions where fp=?", (fp,)).fetchone()
    if not row:
        continue
    p = json.loads(row[0]); d = json.loads(dos)
    if seen.get(p["action"], 0) >= 2:
        continue
    seen[p["action"]] = seen.get(p["action"], 0) + 1
    print("=====", p["action"], "mailbox:", d["mailbox"])
    for s in d["sources"]:
        if s["kind"] in ("history", "bulletin"):
            continue
        print("--", s["sourceId"], s["kind"], s["provenance"])
        for l in s["lines"]:
            if "Archival annotation" in l["text"]:
                continue
            print(l["lineId"], l["text"])
    print("PROPOSAL", json.dumps({k: p[k] for k in ("target", "payload", "evidence")}))
print(seen)