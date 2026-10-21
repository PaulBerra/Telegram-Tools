"""Offline unit tests for the relationship graph backbone (no network/env)."""

from telegram_tools.core import graph


def _msg(uid, chat, text="", username=None, name=None):
    return {"message_id": 1, "chat_id": chat, "date": 0,
            "text": text, "from": {"id": uid, "username": username, "first_name": name}}


def test_same_user_across_bots_collapses_and_counts_sources():
    # Same numeric user id, seen by two different bots, in one group.
    g = graph.build_graph([
        ("botA", [_msg(7, -100, name="Al"), _msg(7, -100)]),
        ("botB", [_msg(7, -100)]),
    ])
    uk, gk = graph.user_key(7), graph.group_key(-100)
    assert uk in g.entities and gk in g.entities
    assert len(g.entities_of(graph.USER)) == 1          # not duplicated per bot
    edge = g.edges[(uk, gk, "posted_in")]
    assert edge.weight == 3                              # 3 messages total
    assert edge.sources == {"botA", "botB"}             # multi-bot corroboration


def test_users_linked_through_shared_indicator():
    # Two different users who posted the SAME btc address become connected
    # through that indicator node - the investigation pivot.
    addr = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
    g = graph.build_graph([("bot", [
        _msg(1, -1, text=f"send to {addr}"),
        _msg(2, -2, text=f"my wallet {addr}"),
    ])])
    u1, u2 = graph.user_key(1), graph.user_key(2)
    ik = graph.indicator_key("btc", addr)
    assert ik in g.entities and g.entities[ik].kind == graph.INDICATOR
    assert ik in g.shared(u1, u2)                       # shared pivot node
    assert u2 in g.connections_of(u1)                   # u1 is tied to u2
    assert g.path(u1, u2) == [u1, ik, u2]               # the chain that links them


def test_users_linked_through_shared_group():
    g = graph.build_graph([("bot", [_msg(1, -100), _msg(2, -100)])])
    u1, u2 = graph.user_key(1), graph.user_key(2)
    assert g.path(u1, u2) == [u1, graph.group_key(-100), u2]
    assert g.connections_of(u1).get(u2) == [graph.group_key(-100)]


def test_ego_graph_is_the_subject_neighbourhood():
    g = graph.build_graph([("bot", [
        _msg(1, -100), _msg(2, -100),       # 1 and 2 share group -100
        _msg(3, -200),                       # 3 is elsewhere, unrelated
    ])])
    ego = g.ego(graph.user_key(1), radius=1)
    assert graph.user_key(1) in ego.entities
    assert graph.group_key(-100) in ego.entities        # its group
    assert graph.user_key(3) not in ego.entities        # unrelated user excluded
    assert graph.group_key(-200) not in ego.entities


def test_user_keyed_by_username_when_no_id():
    g = graph.build_graph([("bot", [_msg(None, -1, username="Scammer")])])
    assert graph.user_key(None, "Scammer") == "user:@scammer"
    assert "user:@scammer" in g.entities


def test_entity_layer_classification_and_override():
    g = graph.build_graph([("bot", [
        _msg(1, -100, text="pay bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx and call +12025550147"),
    ])])
    layers = {graph.entity_layer(e) for e in g.entities.values()}
    assert "users" in layers and "groups" in layers and "crypto" in layers
    # A phone indicator starts in the 'phones' layer and can be reclassified.
    phone = next(e for e in g.entities_of(graph.INDICATOR)
                 if e.attrs.get("itype") == "phone")
    assert graph.entity_layer(phone) == "phones"
    phone.attrs["_layer"] = "other"
    assert graph.entity_layer(phone) == "other"


def test_degree_and_top_by_degree():
    g = graph.build_graph([("bot", [
        _msg(1, -100), _msg(1, -200), _msg(1, -300),   # user 1 in 3 groups
        _msg(2, -100),
    ])])
    assert g.degree(graph.user_key(1)) == 3
    top = g.top_by_degree(kind=graph.USER, n=1)
    assert top[0].key == graph.user_key(1)
