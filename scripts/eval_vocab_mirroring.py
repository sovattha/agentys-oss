"""
Vocabulary mirroring redundancy test.

Hypothesis: a "user global vocab" injection (top-N unigrams + bigrams) is only
useful if the LLM doesn't already see these terms in the context it receives.

Method (purely statistical, no LLM calls):
  1. For each persona, identify "draft cases": received emails that have a
     human-written sent reply in the same thread.
  2. Compute top-10 unigrams + top-10 bigrams from ALL sent emails (= user
     global vocab, what the user habitually writes).
  3. For each draft case, measure:
     a. REDUNDANCY: % of top-10 terms already present in the context the
        drafter would receive (input email + thread history).
     b. NET LIFT: terms in vocab AND in human reply BUT NOT in context
        (= pure value the injection would add, since the LLM can't see them).
     c. NOISE RISK: terms in vocab BUT NOT in human reply
        (= terms the injection would push but human didn't use → forced).

If REDUNDANCY > 75% on average, injection is mostly noise.
If NET LIFT < 5% of vocab on average, injection adds little real value.
If NOISE RISK > 50%, injection biases the draft toward terms human wouldn't use.
"""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

# French + English stopwords (compact, ~250 most common)
STOPWORDS = set("""
le la les un une des de du au aux à et ou mais donc car ni or que qui quoi dont où
ce cet cette ces mon ma mes ton ta tes son sa ses notre votre nos vos leur leurs
je tu il elle nous vous ils elles me te se moi toi lui eux soi
être avoir faire dire aller voir savoir pouvoir vouloir devoir falloir venir
suis es est sommes êtes sont étais était étions étaient été
ai as a avons avez ont avais avait avions avaient eu
fais fait faisons faites font faisais faisait faisaient
dans sur sous avec sans pour par vers chez entre depuis pendant avant après
aussi alors ainsi très plus moins bien mal trop peu tout tous toute toutes
si comme quand parce car puisque tandis lorsque
oui non pas ne ni
the a an of for to in on at by with from as is are was were be been being have has had do does did
this that these those it its they them their there here where when what why how
some any all each every few more most other such no nor not only own same so than too very
can will just don should now then up out so up down through about into above below
i me my we us our you your he him his she her hers
de du sur le dans pour avec une vous merci je tu et le la les
bonjour bonsoir cordialement bien salutations
hello hi thanks thank regards best
""".split())

# URLs, emails, numbers
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]+")
URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMAIL_RE = re.compile(r"\S+@\S+")


def clean(text: str) -> str:
    text = URL_RE.sub(" ", text)
    text = EMAIL_RE.sub(" ", text)
    return text


def tokenize(text: str) -> list[str]:
    text = clean(text).lower()
    tokens = TOKEN_RE.findall(text)
    return [t for t in tokens
            if len(t) >= 4
            and t not in STOPWORDS
            and not t.isnumeric()]


def bigrams(tokens: list[str]) -> list[tuple[str, str]]:
    return list(zip(tokens, tokens[1:]))


def top_n_unigrams(corpus_texts: list[str], n: int = 10) -> list[str]:
    """TF-IDF-ish: rank by frequency × distinctiveness vs general corpus."""
    all_tokens = []
    for text in corpus_texts:
        all_tokens.extend(tokenize(text))
    counts = Counter(all_tokens)
    counts = {t: c for t, c in counts.items() if c >= 2}
    return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def top_n_bigrams(corpus_texts: list[str], n: int = 10) -> list[tuple[str, str]]:
    all_bg = []
    for text in corpus_texts:
        all_bg.extend(bigrams(tokenize(text)))
    counts = Counter(all_bg)
    counts = {bg: c for bg, c in counts.items() if c >= 2}
    return [bg for bg, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def contains_bg(text: str, bg: tuple[str, str]) -> bool:
    return f"{bg[0]} {bg[1]}".lower() in text.lower()


def analyze_persona(fixture_path: Path) -> dict:
    data = json.load(open(fixture_path, encoding="utf-8"))
    emails = data["emails"]

    # Sent = user-authored, Received = inbound
    sent = [e for e in emails if e.get("direction") == "sent"]
    received = [e for e in emails if e.get("direction") == "received"]

    if len(sent) < 5:
        return {"persona": fixture_path.stem, "skipped": True, "reason": "too few sent"}

    # Build thread index
    thread_idx = {}
    for e in emails:
        thread_idx.setdefault(e.get("thread_id"), []).append(e)

    # Compute user global vocab from ALL sent emails
    sent_bodies = [e["body"] for e in sent]
    top_uni = top_n_unigrams(sent_bodies, n=10)
    top_bi = top_n_bigrams(sent_bodies, n=10)

    # Build draft cases: each received email that has a sent reply in thread
    cases = []
    for r in received:
        tid = r.get("thread_id")
        thread = thread_idx.get(tid, [])
        # Find sent reply in same thread, dated after received
        replies = [t for t in thread if t.get("direction") == "sent"]
        if not replies:
            continue
        # Context the drafter would see: received email body + earlier thread
        ctx = r["body"]
        # Add prior emails in thread
        for prior in thread:
            if prior.get("date", "") < r.get("date", "") and prior["id"] != r["id"]:
                ctx += "\n" + prior["body"]
        # Take the chronologically first reply after received
        reply_body = replies[0]["body"]
        cases.append({"context": ctx, "reply": reply_body})

    if len(cases) < 5:
        return {"persona": fixture_path.stem, "skipped": True, "reason": "too few cases"}

    # Per-case analysis
    redundancy_uni = []
    net_lift_uni = []
    noise_risk_uni = []
    redundancy_bi = []
    net_lift_bi = []
    noise_risk_bi = []

    for c in cases:
        ctx = c["context"]
        reply = c["reply"]

        # Unigrams
        in_ctx = sum(1 for t in top_uni if contains(ctx, t))
        in_reply_only = sum(1 for t in top_uni if contains(reply, t) and not contains(ctx, t))
        not_in_reply = sum(1 for t in top_uni if not contains(reply, t))
        redundancy_uni.append(in_ctx / len(top_uni))
        net_lift_uni.append(in_reply_only / len(top_uni))
        noise_risk_uni.append(not_in_reply / len(top_uni))

        # Bigrams
        in_ctx_b = sum(1 for bg in top_bi if contains_bg(ctx, bg))
        in_reply_only_b = sum(1 for bg in top_bi if contains_bg(reply, bg) and not contains_bg(ctx, bg))
        not_in_reply_b = sum(1 for bg in top_bi if not contains_bg(reply, bg))
        redundancy_bi.append(in_ctx_b / len(top_bi))
        net_lift_bi.append(in_reply_only_b / len(top_bi))
        noise_risk_bi.append(not_in_reply_b / len(top_bi))

    def avg(xs): return sum(xs) / len(xs) if xs else 0.0

    return {
        "persona": fixture_path.stem,
        "n_cases": len(cases),
        "n_sent": len(sent),
        "top_unigrams": top_uni,
        "top_bigrams": [" ".join(bg) for bg in top_bi],
        "unigram": {
            "redundancy_avg": avg(redundancy_uni),
            "net_lift_avg": avg(net_lift_uni),
            "noise_risk_avg": avg(noise_risk_uni),
        },
        "bigram": {
            "redundancy_avg": avg(redundancy_bi),
            "net_lift_avg": avg(net_lift_bi),
            "noise_risk_avg": avg(noise_risk_bi),
        },
    }


def main():
    fixtures = sorted(FIXTURES.glob("test_emails*.json"))
    results = []
    print(f"\nAnalyzing {len(fixtures)} persona fixtures...\n")
    print("=" * 90)

    for fx in fixtures:
        r = analyze_persona(fx)
        if r.get("skipped"):
            print(f"[SKIP] {r['persona']}: {r['reason']}")
            continue
        results.append(r)
        print(f"\n[{r['persona']}]  cases={r['n_cases']}  sent={r['n_sent']}")
        print(f"  top unigrams: {r['top_unigrams']}")
        print(f"  top bigrams:  {r['top_bigrams']}")
        u = r["unigram"]
        b = r["bigram"]
        print(f"  UNIGRAMS: redundancy={u['redundancy_avg']:.1%}  "
              f"net_lift={u['net_lift_avg']:.1%}  "
              f"noise_risk={u['noise_risk_avg']:.1%}")
        print(f"  BIGRAMS:  redundancy={b['redundancy_avg']:.1%}  "
              f"net_lift={b['net_lift_avg']:.1%}  "
              f"noise_risk={b['noise_risk_avg']:.1%}")

    print("\n" + "=" * 90)
    print("AGGREGATE (across all personas, weighted by n_cases)")
    print("=" * 90)

    total_cases = sum(r["n_cases"] for r in results)
    print(f"Total draft cases analyzed: {total_cases}")

    def weighted_avg(key1, key2):
        return sum(r[key1][key2] * r["n_cases"] for r in results) / total_cases

    print("\nUNIGRAMS (top-10 user global):")
    print(f"  Redundancy (terms already in context): {weighted_avg('unigram', 'redundancy_avg'):.1%}")
    print(f"  Net lift (terms in reply, NOT in context): {weighted_avg('unigram', 'net_lift_avg'):.1%}")
    print(f"  Noise risk (terms NOT in reply): {weighted_avg('unigram', 'noise_risk_avg'):.1%}")

    print("\nBIGRAMS (top-10 user global):")
    print(f"  Redundancy: {weighted_avg('bigram', 'redundancy_avg'):.1%}")
    print(f"  Net lift: {weighted_avg('bigram', 'net_lift_avg'):.1%}")
    print(f"  Noise risk: {weighted_avg('bigram', 'noise_risk_avg'):.1%}")

    out = ROOT / "tasks" / "vocab-mirroring-eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
