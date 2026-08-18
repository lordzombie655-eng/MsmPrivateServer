import json
import logging
import random

from msm_playerdata import create_player_properties, load_player, save_player
from msm_store import load_db_json
logger = logging.getLogger("msm.cardalbum")

CARDS_PER_PACK = 3                                                                             
CURRENCY_REWARD_TYPES = {"COINS": "coins", "DIAMONDS": "diamonds", "FOOD": "food", "RELICS": "relics",
                          "KEYS": "keys", "ETHEREAL_CURRENCY": "ethereal_currency", "STARPOWER": "starpower"}

_cache = {}


def _json_list(value):
    if isinstance(value, list):
        return value
    try:
        return json.loads(value) if value else []
    except ValueError:
        return []


def _cards():
    if "cards" not in _cache:
        data = load_db_json("db_cards") or {}
        _cache["cards"] = {c["id"]: c for c in (data.get("card_data") or []) if "id" in c}
    return _cache["cards"]


def _albums():
    if "albums" not in _cache:
        data = load_db_json("db_card_albums") or {}
        albums = {}
        for album in data.get("card_album_data") or []:
            pages = [{"id": p.get("id"), "cards": _json_list(p.get("cards")), "rewards": _json_list(p.get("rewards"))}
                     for p in album.get("pages") or []]
            albums[album["id"]] = pages
        _cache["albums"] = albums
    return _cache["albums"]


def _store_items():
    if "store_items" not in _cache:
        data = load_db_json("db_card_album_store_items") or {}
        _cache["store_items"] = {
            i["id"]: {"cost": i.get("cost", 0) or 0, "contents": _json_list(i.get("contents"))}
            for i in data.get("card_album_store_item_data") or [] if "id" in i
        }
    return _cache["store_items"]


def _card_album_id(card_id):
    for album_id, pages in _albums().items():
        for page in pages:
            if card_id in page["cards"]:
                return album_id
    return 1


def _cards_for_album(album_id):
    if "cards_by_album" not in _cache:
        _cache["cards_by_album"] = {}
    per_album = _cache["cards_by_album"]
    if album_id not in per_album:
        wanted_ids = {card_id for page in _albums().get(album_id, []) for card_id in page["cards"]}
        all_cards = _cards()
        per_album[album_id] = [all_cards[cid] for cid in wanted_ids if cid in all_cards]
    return per_album[album_id]


def _album_entry(player_object, album_id):
    albums = player_object.setdefault("card_albums", [])
    for entry in albums:
        if entry.get("card_album_id") == album_id:




            entry.setdefault("data", {}).setdefault("currency", 1999999999)
            return entry
    entry = {"card_album_id": album_id, "data": {"cards": [], "currency": 1999999999}}
    albums.append(entry)
    return entry


def _owned_card_ids(player_object, album_id):
    for entry in player_object.get("card_albums") or []:
        if entry.get("card_album_id") == album_id:
            return {c["i"] for c in entry.get("data", {}).get("cards", []) if (c.get("n", 0) or 0) > 0}
    return set()


def _grant_cards(player_object, card_ids):
    for card_id in card_ids:
        cards = _album_entry(player_object, _card_album_id(card_id)).setdefault("data", {}).setdefault("cards", [])
        entry = next((c for c in cards if c["i"] == card_id), None)
        if entry is None:
            cards.append({"i": card_id, "n": 1})
        else:
            entry["n"] = entry.get("n", 0) + 1


def _target_album_id(player_object):
    return player_object.get("last_card_album") or 1


def _grant_packs(player_object, amount, pack_type=1):
    album_id = _target_album_id(player_object)
    defs = _cards_for_album(album_id)
    if not defs:
        return
    weights = [1.0 / max(1, c.get("rarity", 1)) for c in defs]
    data = _album_entry(player_object, album_id).setdefault("data", {})
    packs = data.setdefault("packs", [])
    next_pack_id = max([p.get("i", 0) for p in packs] + [0]) + 1
    for _ in range(max(1, amount)):
        picks = random.choices(defs, weights=weights, k=CARDS_PER_PACK)
        packs.append({"c": [c["id"] for c in picks], "t": pack_type, "i": next_pack_id})
        next_pack_id += 1


def _open_pending_packs(player_object, album_id, pack_ids=None):
    entry = _album_entry(player_object, album_id)
    data = entry.setdefault("data", {})
    all_packs = data.get("packs", [])
    if not all_packs:
        return
    if pack_ids:
        wanted = set(pack_ids)
        packs = [p for p in all_packs if p.get("i") in wanted]
        data["packs"] = [p for p in all_packs if p.get("i") not in wanted]
    else:
        packs = all_packs
        data["packs"] = []
    if not packs:
        return
    cards = data.setdefault("cards", [])
    currency = data.get("currency", 0) or 0
    defs = _cards()
    for pack in packs:
        for card_id in pack.get("c") or []:
            existing = next((c for c in cards if c["i"] == card_id), None)
            if existing is None:
                cards.append({"i": card_id, "n": 1})
            else:
                existing["n"] = existing.get("n", 0) + 1
                rarity = (defs.get(card_id) or {}).get("rarity", 1) or 1
                currency += max(1, 8 - rarity)
    data["currency"] = currency


def _grant_currency_rewards(player_object, rewards):
    normalized = []
    for reward in rewards:
        reward = dict(reward)
        key = CURRENCY_REWARD_TYPES.get(str(reward.get("type", "")).upper())
        if key:
            player_object[key] = (player_object.get(key, 0) or 0) + (reward.get("amount", 0) or 0)
            player_object[f"{key}_actual"] = player_object[key]
        if "amount" not in reward:
            reward["amount"] = 1
        normalized.append(reward)
    return normalized


def _card_albums_properties(player_object):
    return [{"card_albums": player_object.get("card_albums") or []}]


def open_card_packs(username, params):
    logger.info("gs_open_card_packs params: %r", params)
    root, player_object = load_player(username)
    album_id = params.get("card_album_id") or params.get("album_id") or _target_album_id(player_object)
    pack_ids = params.get("card_pack_ids") or params.get("pack_ids")
    _open_pending_packs(player_object, album_id, pack_ids)
    save_player(username, root)
    return [
        ("gs_open_card_packs", {"success": True}),
        ("gs_update_properties", {"properties": _card_albums_properties(player_object)}),
    ]


def buy_card_album_store_item(username, params):
    logger.info("gs_buy_card_album_store_item params: %r", params)
    item = _store_items().get(params.get("item_id") or params.get("id") or params.get("store_item_id") or 0)
    if item is None:
        return {"success": False}
    root, player_object = load_player(username)
    album_id = params.get("card_album_id") or params.get("album_id") or _target_album_id(player_object)
    entry = _album_entry(player_object, album_id)
    data = entry.setdefault("data", {})
    currency = data.get("currency", 0) or 0




    data["currency"] = max(0, currency - item["cost"])
    for content in item["contents"]:
        if str(content.get("type", "")).upper() == "CARD_PACK":
            _grant_packs(player_object, content.get("amount", 1) or 1)
    save_player(username, root)
    return [
        ("gs_buy_card_album_store_item", {"success": True, "rewards": {"updateCardAlbum": True}}),
        ("gs_update_properties", {"properties": _card_albums_properties(player_object)}),
    ]


def _collect(username, params, whole_album):
    root, player_object = load_player(username)
    album_id = params.get("card_album_id") or params.get("album_id") or player_object.get("last_card_album", 0) or 0
    pages = _albums().get(album_id) or []
    if not whole_album:
        page_id = params.get("page_id") or params.get("page") or 0
        pages = [p for p in pages if p["id"] == page_id]
    owned = _owned_card_ids(player_object, album_id)
    if not pages or not all(card_id in owned for page in pages for card_id in page["cards"]):
        return {"success": False}
    rewards = _grant_currency_rewards(player_object, [r for page in pages for r in page["rewards"]])
    save_player(username, root)
    return {"success": True, "rewards": rewards, "properties": create_player_properties(player_object)}


def collect_card_album_page_rewards(username, params):
    return _collect(username, params, whole_album=False)


def collect_card_album_rewards(username, params):
    return _collect(username, params, whole_album=True)
