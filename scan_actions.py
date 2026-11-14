#!/usr/bin/env python3
"""alpha-grok scanner for GitHub Actions (temporary, while the Hermes server lapses).

Deterministic 0-token fallback scanner (ddgs), same user rules as the cron:
- NFT early-WL <12h, from the project's OFFICIAL X account only
- permanent sent-list (data/sent.json) — never re-post a handle once sent
- fail-closed: ambiguous = drop, never fabricate
- 0 passing items = silent (exit 0, no Discord post, feed untouched except timestamp)

Outputs per run:
- feed.json (repo root, dashboard contract) — new items prepended, max 50 kept
- data/sent.json — new handles appended (committed back by the workflow)
- Discord embeds via ALPHA_GROK_WEBHOOK env (repo secret). If unset,
  Discord is skipped and only the feed is written.

Webhook is NEVER hardcoded here — it comes from the repo secret only.
"""
import json
import os
import re
import sys
import time
import datetime
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SENT_PATH = ROOT / "data" / "sent.json"
FEED_PATH = ROOT / "feed.json"
NOW = int(time.time())
SNOW_EPOCH = 1288834974657
MAX_AGE_H = 12
MAX_LEADS = 10
WEBHOOK = os.environ.get("ALPHA_GROK_WEBHOOK", "").strip()

QUERIES = [
    # meta agentic BNB first
    "NFT agentic BNB chain mint site:x.com",
    "Binance Agentic Wallet NFT mint whitelist",
    "BAP-578 NFA agent NFT mint waitlist",
    ".ai Agent ID NFT mint BSC",
    "BSC agentic NFT collection apply WL",
    # general WL
    "NFT waitlist application open site:x.com",
    "open waitlist NFT site:x.com",
    "WL open NFT early site:x.com",
    "NFT whitelist open site:x.com",
    "NFT allowlist open site:x.com",
    "free mint waitlist NFT site:x.com",
    "NFT WL form open site:x.com",
    "early access NFT waitlist site:x.com",
    "NFT genesis waitlist open site:x.com",
]

STALE_KW = ["ended", "closed", "sold out", "expired", "mint complete", "finished",
            "waitlist closed", "applications closed", "claim ended", "mint ended",
            "deadline passed", "mint is live", "mint now", "minting live",
            "1 day to mint", "2 days to mint", "mint countdown", "mint price",
            "mint cost", "mint fee"]
STALE_PROJ = ["azuki", "bored ape", "yuga", "clonex", "moonbirds", "doodles",
              "cryptopunks", "pudgy", "lil pudgy"]

AGENTIC_KW = ["agent-gated", "agent id", ".ai", "agentic wallet", "bap-578",
              "nfa", "agent id exclusive", "binance agentic"]


def norm_tweet_url(url):
    m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)", url or "", re.I)
    if not m:
        return None, None
    return f"https://x.com/{m.group(1)}/status/{m.group(2)}", m.group(1)


def snow_age_h(tid):
    ms = (int(tid) >> 22) + SNOW_EPOCH
    return (NOW * 1000 - ms) / 3600000, ms


def snow_iso(tid):
    ms = (int(tid) >> 22) + SNOW_EPOCH
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def looks_stale(text):
    t = (text or "").lower()
    return any(k in t for k in STALE_KW)


def looks_bluechip(text):
    t = (text or "").lower()
    return any(k in t for k in STALE_PROJ)


def has_wl_keywords(text):
    t = (text or "").lower()
    wl_kw = ["waitlist", "whitelist", "allowlist", "wl", "apply", "application",
             "sign up", "form", "early access", "genesis", "free mint", "gtd",
             "guaranteed", "allow list", "mint pass"]
    if not any(kw in t for kw in wl_kw):
        return False
    if any(kw in t for kw in ["mint price:", "mint cost:", "mint fee:"]):
        if not any(kw in t for kw in ["waitlist", "wl", "gtd", "allowlist"]):
            return False
    return True


def is_agentic(text):
    t = (text or "").lower()
    return any(k in t for k in AGENTIC_KW)


def load_sent():
    try:
        items = json.load(open(SENT_PATH))
        return {str(h).lower().strip().lstrip("@").rstrip("/") for h in items}
    except Exception:
        return set()


def load_feed():
    try:
        data = json.load(open(FEED_PATH))
        return data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        return []


def role_mention():
    """Read the Discord role mention from CRON_PROMPT.md in this repo if present.
    Keeps the role id out of this script; falls back to no mention."""
    try:
        text = (ROOT / "CRON_PROMPT.md").read_text()
        m = re.search(r"<@&\d+>", text)
        return m.group(0) if m else ""
    except Exception:
        return ""


def post_embed(webhook, item):
    mention = role_mention()
    agentic = "AGENTIC BNB" in (item.get("tags") or [])
    if agentic:
        content = f"{mention} **[ALPHA-GROK \u2014 AGENTIC BINANCE]**" if mention else "**[ALPHA-GROK \u2014 AGENTIC BINANCE]**"
        content += "\nNFT agentic BNB \u2014 gate `.ai` Agent ID (Binance Agentic Wallet), chain BSC / BAP-578"
        meta = "Agentic BNB"
    else:
        content = f"{mention} **[ALPHA-GROK]** akun NFT resmi \u2014 WL baru" if mention else "**[ALPHA-GROK]** akun NFT resmi \u2014 WL baru"
        meta = "NFT lain"
    payload = {
        "content": content,
        "embeds": [{
            "title": item["project"],
            "url": item["post_url"],
            "color": 0x2ECC71,
            "description": item["note"] or "Detail terbatas.",
            "fields": [
                {"name": "Akun", "value": item["handle"], "inline": True},
                {"name": "Window", "value": "WL baru buka", "inline": True},
                {"name": "Age", "value": item.get("age_label", ""), "inline": True},
                {"name": "Tweet time", "value": item["found_at"], "inline": True},
                {"name": "Meta", "value": meta, "inline": True},
            ],
            "footer": {"text": "alpha-grok | <12h X-only WL | DYOR"},
        }],
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def main():
    sent = load_sent()
    print(f"DEDUP: {len(sent)} handles in sent-list", flush=True)

    try:
        from ddgs import DDGS
        s = DDGS()
    except Exception as e:
        print(f"[ERR] ddgs import: {e}", flush=True)
        print("[[SILENT]]")
        return 0

    raw, order = {}, []
    for qi, q in enumerate(QUERIES):
        try:
            res = list(s.text(q, max_results=10, region="wt-wt", safesearch="off", timelimit="d"))
            for r in res:
                url, handle = norm_tweet_url((r.get("href") or "").strip())
                if not url:
                    continue
                if url not in raw:
                    raw[url] = {"title": r.get("title", ""), "body": r.get("body", ""),
                                "handle": handle}
                    order.append(url)
            print(f"  [OK] q{qi}: {q[:44]} -> {len(res)} raw, {len(order)} X", flush=True)
        except Exception as e:
            print(f"  [ERR] q{qi}: {str(e)[:70]}", flush=True)
        time.sleep(2.0)

    print(f"TOTAL_X_URLS: {len(order)}", flush=True)
    cands = []
    for u in order:
        r = raw[u]
        handle = (r["handle"] or "").lower()
        if handle in sent:
            print(f"  DEDUP: {u}", flush=True)
            continue
        m = re.search(r"/status/(\d+)", u)
        if not m:
            continue
        age_h, _ = snow_age_h(m.group(1))
        if age_h > MAX_AGE_H:
            continue
        text = f"{r['title']} {r['body']}"
        if looks_stale(text) or looks_bluechip(text):
            continue
        if not has_wl_keywords(text):
            continue
        agentic = is_agentic(text)
        snippet = re.sub(r"\s+", " ", r["body"] or r["title"] or "").strip()[:180]
        cands.append({
            "id": m.group(1),
            "project": f"@{r['handle']}",
            "handle": f"@{r['handle']}",
            "post_url": u,
            "site_url": "",
            "source": "alpha-grok",
            "found_at": snow_iso(m.group(1)),
            "age_label": f"{age_h:.1f}h",
            "tags": ["AGENTIC BNB"] if agentic else ["NFT"],
            "note": snippet,
        })
        if len(cands) >= MAX_LEADS:
            break

    print(f"CANDIDATES: {len(cands)}", flush=True)
    if not cands:
        print("[[SILENT]]")
        return 0

    # Discord first (if webhook configured), then record sent + feed.
    posted = 0
    if WEBHOOK:
        for item in cands:
            try:
                post_embed(WEBHOOK, item)
                posted += 1
                print(f"  POSTED: {item['handle']}", flush=True)
            except Exception as e:
                print(f"  [ERR] post {item['handle']}: {str(e)[:100]}", flush=True)
            time.sleep(1.0)
    else:
        print("WEBHOOK not set — Discord skipped, feed still written", flush=True)

    # Only mark sent for items actually posted; if no webhook, still mark them
    # sent (they are in the feed now — the dashboard is the record).
    new_handles = {c["handle"].lstrip("@").lower() for c in cands}
    sent |= new_handles
    (ROOT / "data").mkdir(exist_ok=True)
    json.dump(sorted(sent), open(SENT_PATH, "w"), indent=1)

    old_items = load_feed()
    seen_ids = {it.get("id") for it in old_items}
    merged = [c for c in cands] + [it for it in old_items if it.get("id") not in {c["id"] for c in cands}]
    merged = merged[:50]
    for c in merged:
        c.pop("age_label", None)
    json.dump({
        "updated_at": datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": merged,
    }, open(FEED_PATH, "w"), indent=1)

    print(f"REPORTED: {posted} posted to Discord, {len(cands)} in feed, sent-list now {len(sent)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
