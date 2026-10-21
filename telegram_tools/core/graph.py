"""Entity / relationship graph - the backbone for the Investigateur and Nexus views.

Pure, local, no network. It turns the messages collected by one or several bots
into a typed graph:

  - **users** who posted,
  - the **groups** they posted in,
  - the **indicators** they shared (links, crypto addresses, @mentions, ...).

Two users who post in the same group - or share the same crypto address - become
connected *through that node*. That shared node is exactly the pivot an
investigation needs, so the graph makes "several users across several groups,
via several bots" one model instead of glued-together tabs.

Every edge records which **source** produced it (a bot id, or later an external
provider), so multi-bot / multi-source corroboration comes for free. External
enrichment (t.me previews, Telethon, ...) will add entities and edges to the same
graph through the same `add_entity` / `add_edge` API.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import intel

# Entity kinds.
USER = "user"
GROUP = "group"
INDICATOR = "indicator"

# "Layers" = the friendly classification a node belongs to, used for colouring
# and the Nexus layer filter. An indicator's layer comes from its type; a node
# can be reclassified by hand (attrs["_layer"]) when a loose regex mis-sorted it.
_ITYPE_LAYER = {"btc": "crypto", "eth": "crypto", "ton": "crypto", "url": "links",
                "telegram_invite": "invites", "mention": "mentions",
                "email": "emails", "phone": "phones"}
LAYERS = ["users", "groups", "crypto", "links", "invites", "mentions",
          "emails", "phones", "other"]
LAYER_LABELS = {"users": "People", "groups": "Groups", "crypto": "Crypto",
                "links": "Links", "invites": "Invite links", "mentions": "@mentions",
                "emails": "Emails", "phones": "Phones", "other": "Other"}


def entity_layer(entity) -> str:
    """The layer a node belongs to (hand override first, then kind / indicator type)."""
    ov = entity.attrs.get("_layer")
    if ov:
        return ov
    if entity.kind == USER:
        return "users"
    if entity.kind == GROUP:
        return "groups"
    return _ITYPE_LAYER.get(entity.attrs.get("itype"), "other")


# --- keys: one canonical string per entity, so the same user/group/indicator
# seen through different bots collapses to a single node. ----------------------
def user_key(uid, username: Optional[str] = None) -> str:
    if uid is not None:
        return f"user:{uid}"
    if username:
        return "user:@" + username.lstrip("@").lower()
    return "user:unknown"


def group_key(chat_id) -> str:
    return f"group:{chat_id}"


def indicator_key(itype: str, value: str) -> str:
    return f"ind:{itype}:{value}"


@dataclass
class Entity:
    kind: str
    key: str
    label: str
    attrs: dict = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    weight: int = 0
    sources: set = field(default_factory=set)   # bot ids / provider names


@dataclass
class Graph:
    entities: dict = field(default_factory=dict)          # key -> Entity
    edges: dict = field(default_factory=dict)             # (src, dst, type) -> Edge
    _adj: dict = field(default_factory=lambda: defaultdict(set))   # key -> {key}

    # ---- construction ----
    def add_entity(self, kind: str, key: str, label: str, **attrs) -> Entity:
        e = self.entities.get(key)
        if e is None:
            e = Entity(kind, key, label or key, {k: v for k, v in attrs.items() if v is not None})
            self.entities[key] = e
            return e
        # Keep the most informative label, merge any new attrs.
        if label and (not e.label or len(str(label)) > len(str(e.label))):
            e.label = label
        for k, v in attrs.items():
            if v is not None and not e.attrs.get(k):
                e.attrs[k] = v
        return e

    def add_edge(self, src: str, dst: str, etype: str, *, source=None, weight: int = 1) -> Edge:
        k = (src, dst, etype)
        edge = self.edges.get(k)
        if edge is None:
            edge = Edge(src, dst, etype)
            self.edges[k] = edge
            self._adj[src].add(dst)
            self._adj[dst].add(src)
        edge.weight += weight
        if source is not None:
            edge.sources.add(source)
        return edge

    # ---- queries ----
    def neighbors(self, key: str) -> set:
        return set(self._adj.get(key, ()))

    def degree(self, key: str) -> int:
        return len(self._adj.get(key, ()))

    def entities_of(self, kind: str) -> list:
        return [e for e in self.entities.values() if e.kind == kind]

    def shared(self, a: str, b: str) -> set:
        """Entities both a and b connect to (shared groups / indicators)."""
        return self.neighbors(a) & self.neighbors(b)

    def connections_of(self, key: str, kinds=(USER,)) -> dict:
        """Other entities (of `kinds`) linked to `key` through a shared node ->
        {other_key: [shared_keys]}. The core of "who is this user tied to"."""
        out: dict[str, list] = defaultdict(list)
        for mid in self.neighbors(key):
            for other in self.neighbors(mid):
                if other != key and self.entities.get(other) and \
                        self.entities[other].kind in kinds:
                    out[other].append(mid)
        return dict(out)

    def top_by_degree(self, kind: Optional[str] = None, n: int = 20) -> list:
        items = [e for e in self.entities.values() if kind is None or e.kind == kind]
        items.sort(key=lambda e: -self.degree(e.key))
        return items[:n] if n else items

    def subgraph(self, keys: Iterable[str]) -> "Graph":
        keys = set(keys)
        g = Graph()
        for k in keys:
            e = self.entities.get(k)
            if e is not None:
                g.add_entity(e.kind, e.key, e.label, **e.attrs)
        for (src, dst, etype), edge in self.edges.items():
            if src in keys and dst in keys:
                ne = g.add_edge(src, dst, etype, weight=edge.weight)
                ne.sources |= edge.sources
        return g

    def ego(self, key: str, radius: int = 1) -> "Graph":
        """The neighbourhood of `key` out to `radius` hops - the Investigateur view."""
        keep = {key}
        frontier = {key}
        for _ in range(max(radius, 0)):
            nxt: set = set()
            for k in frontier:
                nxt |= self.neighbors(k)
            nxt -= keep
            keep |= nxt
            frontier = nxt
        return self.subgraph(keep)

    def path(self, a: str, b: str) -> list:
        """Shortest chain of entity keys linking a to b (BFS), or [] if none.
        E.g. userA -> sharedGroup -> userB, or userA -> btcAddr -> userB."""
        if a == b:
            return [a]
        if a not in self.entities or b not in self.entities:
            return []
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            for nb in self.neighbors(cur):
                if nb not in prev:
                    prev[nb] = cur
                    if nb == b:
                        chain = [b]
                        while prev[chain[-1]] is not None:
                            chain.append(prev[chain[-1]])
                        return list(reversed(chain))
                    q.append(nb)
        return []


# --- builder -----------------------------------------------------------------
def build_graph(sources: Iterable, *, indicators: bool = True) -> Graph:
    """Build a graph from collected messages.

    `sources` is an iterable of ``(label, messages)`` where ``label`` identifies
    the origin (a bot id, typically) and ``messages`` is a list of the normalised
    message dicts kept in the store (``{message_id, chat_id, date, text, from}``).
    """
    g = Graph()
    for label, messages in sources:
        for msg in messages:
            frm = msg.get("from") or {}
            uid, uname = frm.get("id"), frm.get("username")
            label_name = (frm.get("first_name")
                          or (("@" + uname) if uname else None)
                          or (f"id {uid}" if uid is not None else "unknown"))
            uk = user_key(uid, uname)
            g.add_entity(USER, uk, label_name, id=uid, username=uname)

            chat_id = msg.get("chat_id")
            if chat_id is not None:
                gk = group_key(chat_id)
                g.add_entity(GROUP, gk, str(chat_id), chat_id=chat_id)
                g.add_edge(uk, gk, "posted_in", source=label)

            if indicators:
                text = " ".join(str(msg.get(f, "")) for f in intel._TEXT_FIELDS)
                for itype, value in intel.extract_indicators(text):
                    ik = indicator_key(itype, value)
                    g.add_entity(INDICATOR, ik, value, itype=itype)
                    g.add_edge(uk, ik, "shared:" + itype, source=label)
    return g


def user_messages(sources: Iterable) -> dict:
    """{user_key: [messages]} across every source - for per-subject profiling."""
    out: dict = defaultdict(list)
    for _label, messages in sources:
        for msg in messages:
            frm = msg.get("from") or {}
            out[user_key(frm.get("id"), frm.get("username"))].append(msg)
    return dict(out)
