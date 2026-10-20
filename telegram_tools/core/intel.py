"""Turn an archived NDJSON dump into investigation intelligence (IOCs).

Pure local processing - no network, no API. Scans the captured message text and
extracts indicators useful for anti-scam work: URLs, emails, @usernames, t.me
invite links, phone numbers, and crypto addresses (BTC, ETH, TON). Produces a
structured report (dict), renderable as Markdown / JSON / CSV.

Every indicator keeps the list of message ids it appeared in, so a finding can
always be traced back to its source message (provenance).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

# --- Indicator patterns ---------------------------------------------------
# Deliberately conservative to limit false positives; this is triage, not proof.
_PATTERNS: dict[str, re.Pattern] = {
    "url": re.compile(r"https?://[^\s<>()\"']+", re.I),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "telegram_invite": re.compile(r"(?:https?://)?t\.me/(?:joinchat/|\+)[\w-]+", re.I),
    "mention": re.compile(r"(?<![\w@])@([A-Za-z]\w{3,31})\b"),
    "phone": re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,17}\d(?!\w)"),
    # Crypto
    "btc": re.compile(r"\b(?:bc1[0-9ac-hj-np-z]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
    "eth": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
    "ton": re.compile(r"\b(?:EQ|UQ)[A-Za-z0-9_-]{46}\b"),
}

# Message text fields to scan.
_TEXT_FIELDS = ("text", "caption")


@dataclass
class IntelReport:
    messages: int = 0
    with_text: int = 0
    senders: dict[str, int] = field(default_factory=dict)
    indicators: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    media_count: int = 0

    def total_indicators(self) -> int:
        return sum(len(v) for v in self.indicators.values())


def _iter_messages(ndjson_path: str) -> Iterable[dict]:
    with open(ndjson_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_messages(ndjson_path: str) -> list[dict]:
    """Read a dump into memory (the GUI dashboard keeps it around to drill into)."""
    return list(_iter_messages(ndjson_path))


def _msg_date(msg: dict) -> Optional[int]:
    # Prefer the ORIGINAL message date (it's what matters for OSINT), not the
    # date of the forwarded copy.
    fo = msg.get("forward_origin") or {}
    for v in (fo.get("date"), msg.get("forward_date"), msg.get("date")):
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _sender_label(msg: dict) -> str:
    # The forwarded copy records the ORIGINAL sender under forward_from /
    # forward_origin; fall back to the live 'from'.
    fo = msg.get("forward_origin") or {}
    sender = fo.get("sender_user") or msg.get("forward_from") or msg.get("from") or {}
    if isinstance(sender, dict):
        if sender.get("username"):
            return "@" + sender["username"]
        name = f"{sender.get('first_name','')} {sender.get('last_name','')}".strip()
        if name:
            return name
        if sender.get("id"):
            return f"id:{sender['id']}"
    if fo.get("sender_user_name"):
        return fo["sender_user_name"]
    return "unknown"


def analyze(ndjson_path: str) -> IntelReport:
    report = IntelReport()
    found: dict[str, dict[str, list[int]]] = {k: defaultdict(list) for k in _PATTERNS}
    senders: dict[str, int] = defaultdict(int)

    for msg in _iter_messages(ndjson_path):
        report.messages += 1
        mid = msg.get("message_id", 0)
        if msg.get("_media"):
            report.media_count += sum(1 for m in msg["_media"] if "path" in m)

        text = " ".join(str(msg.get(f, "")) for f in _TEXT_FIELDS).strip()
        if not text:
            continue
        report.with_text += 1
        senders[_sender_label(msg)] += 1

        for kind, pat in _PATTERNS.items():
            for m in pat.finditer(text):
                value = m.group(0).strip()
                if mid not in found[kind][value]:
                    found[kind][value].append(mid)

    report.senders = dict(sorted(senders.items(), key=lambda kv: -kv[1]))
    report.indicators = {k: dict(v) for k, v in found.items() if v}
    return report


# --- Rendering ------------------------------------------------------------

def to_json(report: IntelReport) -> str:
    return json.dumps({
        "messages": report.messages,
        "with_text": report.with_text,
        "media_count": report.media_count,
        "senders": report.senders,
        "indicators": report.indicators,
    }, ensure_ascii=False, indent=2)


def to_markdown(report: IntelReport, source: str = "") -> str:
    lines = ["# Intel report", ""]
    if source:
        lines.append(f"Source: `{source}`")
    lines += [
        f"- Messages: **{report.messages}** ({report.with_text} with text)",
        f"- Media captured: **{report.media_count}**",
        f"- Distinct indicators: **{report.total_indicators()}**",
        "",
        "## Top senders",
    ]
    for name, n in list(report.senders.items())[:15]:
        lines.append(f"- {name} - {n}")
    for kind, values in report.indicators.items():
        lines += ["", f"## {kind} ({len(values)})"]
        for value, mids in sorted(values.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(str(x) for x in mids[:5])
            more = "..." if len(mids) > 5 else ""
            lines.append(f"- `{value}` - {len(mids)}x (msg {sample}{more})")
    return "\n".join(lines) + "\n"


def to_csv(report: IntelReport) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "value", "count", "message_ids"])
    for kind, values in report.indicators.items():
        for value, mids in sorted(values.items(), key=lambda kv: -len(kv[1])):
            w.writerow([kind, value, len(mids), " ".join(str(x) for x in mids)])
    return buf.getvalue()


# --------------------------------------------------------------------------
# Rich index for the in-app dashboard: keeps dates, so we can draw trends and
# drill from an overview into a per-item panel (Splunk style).
# --------------------------------------------------------------------------

@dataclass
class Occurrence:
    message_id: int
    date: Optional[int]   # unix ts of the original message
    sender: str
    text: str = ""


@dataclass
class SenderStat:
    label: str
    count: int = 0
    dates: list = field(default_factory=list)
    types: Counter = field(default_factory=Counter)   # indicator type -> n
    message_ids: list = field(default_factory=list)


@dataclass
class Index:
    messages: int = 0
    with_text: int = 0
    media_count: int = 0
    date_min: Optional[int] = None
    date_max: Optional[int] = None
    # type -> value -> [Occurrence]
    indicators: dict = field(default_factory=dict)
    # sender label -> SenderStat
    senders: dict = field(default_factory=dict)

    def type_totals(self) -> dict:
        return {t: sum(len(v) for v in vals.values()) for t, vals in self.indicators.items()}

    def distinct_total(self) -> int:
        return sum(len(v) for v in self.indicators.values())

    def top_values(self, types, n=None):
        """Ranked (value, type, count) across one or several indicator types."""
        if isinstance(types, str):
            types = [types]
        rows = []
        for t in types:
            for value, occ in self.indicators.get(t, {}).items():
                rows.append((value, t, len(occ)))
        rows.sort(key=lambda r: -r[2])
        return rows[:n] if n else rows

    def occurrences(self, type_, value) -> list:
        return self.indicators.get(type_, {}).get(value, [])

    def top_senders(self, n=None):
        rows = sorted(self.senders.values(), key=lambda s: -s.count)
        return rows[:n] if n else rows


# Indicator types grouped for the dashboard cards.
LINK_TYPES = ("url", "telegram_invite")
CRYPTO_TYPES = ("btc", "eth", "ton")


def scan_messages(messages: Iterable[dict]) -> Index:
    """Build a dated Index from in-memory messages (what the dashboard loads)."""
    idx = Index(indicators={k: defaultdict(list) for k in _PATTERNS})
    senders: dict[str, SenderStat] = {}

    for msg in messages:
        idx.messages += 1
        mid = msg.get("message_id", 0)
        date = _msg_date(msg)
        if date is not None:
            idx.date_min = date if idx.date_min is None else min(idx.date_min, date)
            idx.date_max = date if idx.date_max is None else max(idx.date_max, date)
        if msg.get("_media"):
            idx.media_count += sum(1 for m in msg["_media"] if "path" in m)

        text = " ".join(str(msg.get(f, "")) for f in _TEXT_FIELDS).strip()
        if not text:
            continue
        idx.with_text += 1
        label = _sender_label(msg)
        st = senders.setdefault(label, SenderStat(label))
        st.count += 1
        if date is not None:
            st.dates.append(date)
        st.message_ids.append(mid)

        for kind, pat in _PATTERNS.items():
            seen_here = set()
            for m in pat.finditer(text):
                value = m.group(0).strip()
                if value in seen_here:
                    continue
                seen_here.add(value)
                idx.indicators[kind][value].append(
                    Occurrence(mid, date, label, text[:160]))
                st.types[kind] += 1

    idx.indicators = {k: dict(v) for k, v in idx.indicators.items() if v}
    idx.senders = senders
    return idx


# --- per-sender profiling helpers (used by the dashboard's sender panel) ------

# Common words skipped when ranking a sender's vocabulary (EN + FR + chat noise).
_STOPWORDS = set((
    "the a an and or of to in is it be as at by for on with that this they you i we he "
    "she him her his hers them are was were will would can could should have has had not "
    "but if so do does did my your our their its from up out just about more me no yes ok "
    "okay get got good one all any now then than too very also into over who what when "
    "where why how which "
    "le la les un une des de du et ou qui que quoi dont ou a au aux ce ces cet cette mon "
    "ton son ma ta sa mes tes ses nos vos leurs je tu il elle on nous vous ils elles pas "
    "plus moins tres bien oui non pour avec sans sur sous dans par est sont etre avoir fait "
    "comme mais donc car si ne se me te lui leur y en"
).split())

# Letters only (any language), 3+ chars, so digits and short noise are ignored.
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# Stripped before ranking words, else a crypto address or URL leaks letter-runs
# (qar, srrr, ...) that aren't real words.
_NOISE_TYPES = ("url", "telegram_invite", "email", "btc", "eth", "ton", "phone")


def _strip_noise(text: str) -> str:
    for t in _NOISE_TYPES:
        text = _PATTERNS[t].sub(" ", text)
    return text


def word_frequencies(texts, n: int = 12):
    """Most-used meaningful words across some message texts -> [(word, count)].

    URLs, crypto addresses and the like are removed first so their character
    runs don't masquerade as words.
    """
    counter: Counter = Counter()
    for t in texts:
        for w in _WORD_RE.findall(_strip_noise(t or "").lower()):
            if w not in _STOPWORDS:
                counter[w] += 1
    return counter.most_common(n)


def hour_histogram(dates):
    """Count of messages per UTC hour (0..23) -> [(hour, count)] for all 24 hours.

    Useful OSINT: the quiet hours hint at the poster's real-world timezone.
    """
    counter: Counter = Counter()
    for d in dates:
        if d:
            counter[datetime.fromtimestamp(d, tz=timezone.utc).hour] += 1
    return [(h, counter.get(h, 0)) for h in range(24)]


def sender_texts(messages, label: str):
    """The text of every message a given sender posted, oldest first."""
    rows = []
    for msg in messages:
        if _sender_label(msg) != label:
            continue
        text = " ".join(str(msg.get(f, "")) for f in _TEXT_FIELDS).strip()
        if text:
            rows.append((_msg_date(msg), msg.get("message_id", 0), text))
    rows.sort(key=lambda r: (r[0] or 0))
    return rows


def time_buckets(dates, max_buckets: int = 24):
    """Bucket unix timestamps into ordered (label, count) bins.

    Granularity adapts to the span: hours for a short range, days for a few
    months, then weeks/months. Good enough for a trend bar chart.
    """
    ts = sorted(d for d in dates if d)
    if not ts:
        return []
    span = ts[-1] - ts[0]
    if span <= 2 * 86400:
        step, fmt = 3600, "%m-%d %Hh"          # hourly
    elif span <= 90 * 86400:
        step, fmt = 86400, "%m-%d"             # daily
    elif span <= 540 * 86400:
        step, fmt = 7 * 86400, "%Y-%m-%d"      # weekly
    else:
        step, fmt = 30 * 86400, "%Y-%m"        # ~monthly
    start = ts[0] - (ts[0] % step)
    counts: dict[int, int] = defaultdict(int)
    for t in ts:
        counts[start + ((t - start) // step) * step] += 1
    buckets = sorted(counts.items())
    # Cap the number of bars by merging from the coarse end if needed.
    if len(buckets) > max_buckets:
        factor = (len(buckets) + max_buckets - 1) // max_buckets
        merged: dict[int, int] = defaultdict(int)
        for i, (b, c) in enumerate(buckets):
            merged[buckets[(i // factor) * factor][0]] += c
        buckets = sorted(merged.items())
    out = []
    for b, c in buckets:
        try:
            lbl = datetime.fromtimestamp(b, tz=timezone.utc).strftime(fmt)
        except (OSError, ValueError, OverflowError):
            lbl = str(b)
        out.append((lbl, c))
    return out
