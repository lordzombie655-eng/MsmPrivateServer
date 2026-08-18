import random
import time
from msm_box import build_placeholder_box_monster, is_box_monster_entity, requires_direct_placement, requires_direct_placement_on_purchase
from msm_gamedata import (
    build_paironormal_modes, choose_breeding_result_monster, compute_monster_economy,
    get_max_monster_level, get_monster_definition, get_monster_level_definition, get_structure_definition,
    is_egg_holder_structure, monster_allowed_on_island,
    normalize_collection_type as _normalize_collection_type, resolve_monster_for_island,
)
from msm_playerdata import (
    SFSLong, action_result, add_actual_currencies, create_player_properties,
    find_island, find_island_by_structure, find_monster, find_monster_with_island,
    find_structure, get_active_island_id, island_type_of, load_player, next_daily_reset_timestamp, save_player,
)
from msm_protocol import SFSFloat
def _nursery_touch_payload(structure, player_object):
    return {
        "user_structure_id": SFSLong(structure.get("user_structure_id", 0)),
        "properties": create_player_properties(player_object),
    }
MAGICAL_NEXUS_ISLAND_TYPE = 25
GOLD_ISLAND_TYPE = 6
TITANSOUL_REWARD_INTERVAL_MS = 15796000
BATTLE_ISLAND_STRUCTURES = [
    {"user_structure_id": 1, "structure": 535, "pos_x": 35, "pos_y": 17},
    {"user_structure_id": 2, "structure": 546, "pos_x": 29, "pos_y": 9},
    {"user_structure_id": 3, "structure": 533, "pos_x": 21, "pos_y": 3},
    {"user_structure_id": 4, "structure": 549, "pos_x": 28, "pos_y": 22},
    {"user_structure_id": 5, "structure": 614, "pos_x": 14, "pos_y": 11},
]


def _ensure_battle_island_layout(island):
    if island is None or island_type_of(island) != 20:
        return
    now = int(time.time() * 1000)
    island["type"] = 20
    island.setdefault("battle", {
        "seed": now,
        "costume_data": {"costumes": []},
        "music_data": {"currently_playing": 0, "muted": False},
        "campaign_data": {"campaigns": []},
    })
    island.setdefault("costume_data", {"costumes": []})
    island.setdefault("costumes_owned", "[]")
    island["structures"] = [
        {
            "user_structure_id": entry["user_structure_id"],
            "structure": entry["structure"],
            "pos_x": entry["pos_x"],
            "pos_y": entry["pos_y"],
            "col": entry["pos_x"],
            "row": entry["pos_y"],
            "island": 0,
            "scale": 1.0,
            "is_upgrading": 0,
            "in_warehouse": 0,
            "is_complete": 1,
            "building_completed": island.get("date_created", now) or now,
            "date_created": island.get("date_created", now) or now,
            "last_collection": island.get("date_created", now) or now,
            "muted": 0,
            "flip": 0,
        }
        for entry in BATTLE_ISLAND_STRUCTURES
    ]


def _parse_sold_monsters(island):
    raw = island.get("monsters_sold")
    if isinstance(raw, list):
        return [int(v) for v in raw if isinstance(v, (int, float))]
    if isinstance(raw, str):
        return [int(tok) for tok in raw.strip("[] ").split(",") if tok.strip().lstrip("-").isdigit()]
    return []
def _island_has_monster_type(island, monster_type):
    for m in island.get("monsters") or []:
        if m is not None and m.get("monster") == monster_type:
            return True
    return False
def _mark_monster_sold(island, monster_type):
    if _island_has_monster_type(island, monster_type):
        return None
    sold = _parse_sold_monsters(island)
    if monster_type in sold:
        return None
    sold.append(monster_type)
    island["monsters_sold"] = "[" + ",".join(str(v) for v in sold) + "]"
    return {"island_id": SFSLong(island.get("user_island_id", 0)), "monsters_sold": island["monsters_sold"]}
def _mark_monster_viewed_in_sold(island, monster_type):
    sold = _parse_sold_monsters(island)
    if monster_type and monster_type not in sold:
        sold.append(monster_type)
    island["monsters_sold"] = "[" + ",".join(str(v) for v in sold) + "]"
    return {"island_id": SFSLong(island.get("user_island_id", 0)), "monsters_sold": island["monsters_sold"]}
def _mark_monster_reacquired(island, monster_type):
    sold = _parse_sold_monsters(island)
    if monster_type not in sold:
        return None
    sold = [v for v in sold if v != monster_type]
    island["monsters_sold"] = "[" + ",".join(str(v) for v in sold) + "]"
    return {"island_id": SFSLong(island.get("user_island_id", 0)), "monsters_sold": island["monsters_sold"]}
def _classify_monster_id(monster_id):
    definition = get_monster_definition(monster_id) or {}
    monster_class = (definition.get("monster_class") or "").upper()
    name = (definition.get("name") or "").upper()
    if "EPIC" in monster_class or "EPIC" in name:
        return "epics"
    if "RARE" in monster_class or "RARE" in name:
        return "rares"
    if "SEASON" in monster_class or "SEASON" in name:
        return "seasonals"
    return "commons"
_BOOK_COUNT_FIELDS = {
    "commons": "numUniqueCommonsCollectedOnBookOfMonstersIsland",
    "rares": "numUniqueRaresCollectedOnBookOfMonstersIsland",
    "epics": "numUniqueEpicsCollectedOnBookOfMonstersIsland",
    "seasonals": "numUniqueSeasonalsCollectedOnBookOfMonstersIsland",
}
def repair_book_of_monsters_counts(island):
    if island is None:
        return
    known_ids = set(island.get("book_monster_ids") or [])
    for m in island.get("monsters") or []:
        if m is None:
            continue
        monster_id = m.get("monster") or m.get("monster_id") or 0
        if monster_id > 0:
            known_ids.add(monster_id)
    island["book_monster_ids"] = sorted(known_ids)
    buckets = {"commons": set(), "rares": set(), "epics": set(), "seasonals": set()}
    for monster_id in known_ids:
        if not monster_id or monster_id <= 0:
            continue
        buckets[_classify_monster_id(monster_id)].add(monster_id)
    for bucket, field in _BOOK_COUNT_FIELDS.items():
        island[field] = max(len(buckets[bucket]), island.get(field, 0) or 0)
    island["num_monsters"] = len(island.get("monsters") or [])
def grant_full_book(island):
    if island is None:
        return
    from msm_gamedata import all_monster_ids, monster_ids_allowed_on_island
    island_type = island_type_of(island) or 1
    known_ids = set(island.get("book_monster_ids") or [])
    if island_type == MAGICAL_NEXUS_ISLAND_TYPE:
        known_ids.update(all_monster_ids())
    else:
        known_ids.update(monster_ids_allowed_on_island(island_type))
    island["book_monster_ids"] = sorted(known_ids)
    repair_book_of_monsters_counts(island)
def _mark_monster_collected_in_book(island, monster_id):
    if island is None or not monster_id or monster_id <= 0:
        return
    collected = island.setdefault("book_monster_ids", [])
    if monster_id not in collected:
        collected.append(monster_id)
    repair_book_of_monsters_counts(island)
def _monster_update(monster, mode="full"):
    monster_id = SFSLong(monster.get("user_monster_id", 0))
    update = {"user_monster_id": monster_id}
    if mode == "move":
        update["pos_x"] = monster.get("pos_x", 0)
        update["pos_y"] = monster.get("pos_y", 0)
        update["volume"] = SFSFloat(monster.get("volume", 1.0) or 1.0)
        update["col"] = monster.get("col", monster.get("pos_x", 0))
        update["row"] = monster.get("row", monster.get("pos_y", 0))
        update["scale"] = SFSFloat(monster.get("scale", 1.0) or 1.0)
    elif mode == "flip":
        update["flip"] = monster.get("flip", 0)
    elif mode == "mute":
        update["muted"] = monster.get("muted", 0)
    elif mode == "biggify":
        update["megamonster"] = monster.get("megamonster", {})
    elif mode == "titansoul":
        update["titansoul"] = monster.get("titansoul") or _default_titansoul_state()
    elif mode == "collect":
        update["collected_coins"] = monster.get("collected_coins", 0)
        update["last_collection"] = SFSLong(monster.get("last_collection", 0) or 0)
    elif mode == "feed":
        update["level"] = monster.get("level", 1)
        update["happiness"] = monster.get("happiness", 0)
        update["times_fed"] = monster.get("times_fed", 0)
        update["last_fed"] = SFSLong(monster.get("last_fed", 0) or 0)
        update["last_collection"] = SFSLong(monster.get("last_collection", 0) or 0)
    return update
def _first_param(params, keys, default=0):
    for key in keys:
        value = params.get(key)
        if value is not None:
            return value
    return default
def _as_enabled(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() not in ("0", "false", "no", "off")
    return bool(value)
def move_monster(username, params):
    monster_id = _first_param(params, ("user_monster_id", "userMonsterId", "monster_id", "monsterId", "id"), 0)
    pos_x = _first_param(params, ("pos_x", "x", "col", "column"), 0)
    pos_y = _first_param(params, ("pos_y", "y", "row"), 0)
    volume = _first_param(params, ("volume", "vol"), 1.0)
    scale = _first_param(params, ("scale", "size"), None)
    root, player_object = load_player(username)
    island_id = _first_param(params, ("user_island_id", "userIslandId", "island_id", "island"), get_active_island_id(player_object))
    island = find_island(player_object, island_id) or find_island(player_object, get_active_island_id(player_object))
    monster = find_monster(island, monster_id)
    if monster is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True), {}
    monster["pos_x"] = pos_x
    monster["pos_y"] = pos_y
    monster["col"] = pos_x
    monster["row"] = pos_y
    monster["volume"] = volume
    if scale is not None:
        monster["scale"] = scale
    save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id, with_properties=True)
    return result, _monster_update(monster, "move")
_MEGA_MONSTER_DURATION_MS = 24 * 60 * 60 * 1000
def biggify_monster(username, params):
    monster_id = _first_param(params, ("user_monster_id", "userMonsterId", "monster_id", "monsterId", "id"), 0)
    root, player_object = load_player(username)
    island, monster = find_monster_with_island(player_object, monster_id)
    if monster is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True), {}
    existing_mega = monster.get("megamonster") or {}
    permamega = bool(existing_mega.get("permamega", False))
    now = int(time.time() * 1000)
    finished_at = 0
    if "permanent" in params:
        permamega = _as_enabled(params.get("permanent"), False)
        enabled = True
        if not permamega:
            finished_at = now + _MEGA_MONSTER_DURATION_MS
    elif "mega_enable" in params:
        enabled = _as_enabled(params.get("mega_enable"), False)
        if not enabled:
            finished_at = 0
        elif not permamega:
            finished_at = now + _MEGA_MONSTER_DURATION_MS
    else:
        enabled = True
    mega = {
        "permamega": permamega,
        "currently_mega": enabled,
        "mega_enable": enabled,
        "mega_enabled": enabled,
        "prev_permamega": permamega,
        "started_at": now if enabled else 0,
        "finished_at": finished_at,
        "end_time": finished_at,
        "mega_end_time": finished_at,
        "expires": finished_at,
        "expiration": finished_at,
        "time_remaining": (finished_at - now) if finished_at > now else 0,
        "mega_time_remaining": (finished_at - now) if finished_at > now else 0,
    }
    monster["biggified"] = 1 if enabled else 0
    monster["is_big"] = 1 if enabled else 0
    monster["scale"] = 1.5 if enabled else 1.0
    monster["megamonster"] = mega
    save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id)
    update = {
        "user_monster_id": SFSLong(monster_id),
        "megamonster": mega,
        "properties": create_player_properties(player_object),
    }
    return result, update
def flip_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    flip = 1 if params.get("flipped") else 0
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    monster = find_monster(island, monster_id)
    if monster is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True), {}
    monster["flip"] = flip
    save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id, with_properties=True)
    return result, _monster_update(monster, "flip")
def sell_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    root, player_object = load_player(username)
    island, monster = find_monster_with_island(player_object, monster_id)
    sold_update = None
    if island is not None:
        monsters = island.get("monsters") or []
        monster_type = monster.get("monster", 0) if monster is not None else 0
        for i in range(len(monsters) - 1, -1, -1):
            if monsters[i] is not None and monsters[i].get("user_monster_id") == monster_id:
                del monsters[i]
                break
        if monster_type:
            sold_update = _mark_monster_sold(island, monster_type)
        save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id)
    result["pure_destroy"] = bool(params.get("pure_destroy"))
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, sold_update
def name_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    name = params.get("name", "")
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    monster = find_monster(island, monster_id)
    if monster is not None:
        monster["name"] = name
        save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id)
    result["name"] = name
    return result
def mute_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    muted = params.get("muted", 0)
    root, player_object = load_player(username)
    island, monster = find_monster_with_island(player_object, monster_id)
    if monster is None:
        return {"success": False}, {}
    monster["muted"] = muted
    save_player(username, root)
    return {"success": True}, _monster_update(monster, "mute")
def _monster_rarity(definition):
    cls = (definition.get("class") or "").upper() if definition else ""
    if "EPIC" in cls:
        return "epic"
    if "RARE" in cls:
        return "rare"
    return "common"
def _count_soul_link_rarities(island, soul_links):
    counts = {"common": 0, "rare": 0, "epic": 0}
    for link in soul_links:
        if not isinstance(link, dict):
            continue
        linked = find_monster(island, link.get("id"))
        if linked is None:
            continue
        definition = get_monster_definition(linked.get("monster", 0))
        counts[_monster_rarity(definition)] += 1
    return counts
def _recompute_titansoul_unlocks(island, titansoul):
    soul_links = titansoul.get("soul_links") or []
    titansoul["num_links"] = len(soul_links)
    counts = _count_soul_link_rarities(island, soul_links)
    titansoul["rare_unlocked"] = counts["common"] >= 1
    titansoul["epic_unlocked"] = counts["rare"] >= 1
    was_can_awaken = bool(titansoul.get("can_awaken"))
    can_awaken_now = counts["common"] >= 4 and counts["rare"] >= 4 and counts["epic"] >= 4
    titansoul["can_awaken"] = can_awaken_now
    if can_awaken_now and not was_can_awaken:
        from msm_structures import find_awakener_structure
        awakener = find_awakener_structure(island)
        if awakener is not None:
            awakener.setdefault("ext", {})["awakened_state"] = 1
def add_soul_link(username, params):
    titansoul_id = params.get("titansoul_id", 0) or 0
    linked_monster_id = params.get("user_monster_id", params.get("linked_monster_id", 0)) or 0
    root, player_object = load_player(username)
    island, titansoul_monster = find_monster_with_island(player_object, titansoul_id)
    result = {
        "success": titansoul_monster is not None, "titansoul_id": SFSLong(titansoul_id),
        "user_monster_id": SFSLong(linked_monster_id),
        "properties": create_player_properties(player_object),
    }
    monster_update = None
    if titansoul_monster is not None:
        titansoul = titansoul_monster.setdefault("titansoul", _default_titansoul_state())
        soul_links = titansoul.setdefault("soul_links", [])
        if not any(isinstance(link, dict) and link.get("id") == linked_monster_id for link in soul_links):
            soul_links.append({"id": linked_monster_id})
        if titansoul.get("create_reward_time", 0) == 0 and len(soul_links) > 0:
            now = int(time.time() * 1000)
            titansoul["create_reward_time"] = TITANSOUL_REWARD_INTERVAL_MS
            titansoul["next_reward_time"] = now + TITANSOUL_REWARD_INTERVAL_MS
            titansoul["link_reset_time"] = next_daily_reset_timestamp()
        _recompute_titansoul_unlocks(island, titansoul)
        save_player(username, root)
        monster_update = _monster_update(titansoul_monster, "titansoul")
    return result, monster_update
def remove_soul_link(username, params):
    titansoul_id = params.get("titansoul_id", 0) or 0
    linked_monster_id = params.get("user_monster_id", params.get("linked_monster_id", 0)) or 0
    root, player_object = load_player(username)
    island, titansoul_monster = find_monster_with_island(player_object, titansoul_id)
    result = {
        "success": titansoul_monster is not None, "titansoul_id": SFSLong(titansoul_id),
        "user_monster_id": SFSLong(linked_monster_id),
        "properties": create_player_properties(player_object),
    }
    monster_update = None
    if titansoul_monster is not None:
        titansoul = titansoul_monster.setdefault("titansoul", _default_titansoul_state())
        soul_links = titansoul.setdefault("soul_links", [])
        before = len(soul_links)
        soul_links[:] = [link for link in soul_links if not (isinstance(link, dict) and link.get("id") == linked_monster_id)]
        if len(soul_links) < before:
            titansoul["num_unlinks"] = (titansoul.get("num_unlinks", 0) or 0) + 1
        _recompute_titansoul_unlocks(island, titansoul)
        save_player(username, root)
        monster_update = _monster_update(titansoul_monster, "titansoul")
    return result, monster_update
def toggle_titansoul_fx(username, params):
    titansoul_id = params.get("titansoul_id", params.get("user_monster_id", 0)) or 0
    root, player_object = load_player(username)
    island, titansoul_monster = find_monster_with_island(player_object, titansoul_id)
    monster_update = None
    if titansoul_monster is not None:
        titansoul = titansoul_monster.setdefault("titansoul", _default_titansoul_state())
        titansoul["show_fx"] = not titansoul.get("show_fx", True)
        save_player(username, root)
        monster_update = _monster_update(titansoul_monster, "titansoul")
    return {"success": titansoul_monster is not None, "titansoul_id": SFSLong(titansoul_id)}, monster_update
def feed_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    monster = find_monster(island, monster_id)
    if monster is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True), {}
    level = max(1, monster.get("level", 1) or 1)
    max_level = get_max_monster_level(monster.get("monster", 0))
    if level >= max_level:
        result = action_result(True, "user_monster_id", monster_id)
        result["food"] = player_object.get("food", 0) or 0
        result["properties"] = create_player_properties(player_object)
        add_actual_currencies(result, player_object)
        result["level"] = level
        result["times_fed"] = monster.get("times_fed", 0)
        result["max_level"] = max_level
        return result, _monster_update(monster, "feed")
    level_def = get_monster_level_definition(monster.get("monster", 0), level)
    food_cost = max(1, level_def.get("food", 20)) if level_def else 20
    times_fed = monster.get("times_fed", 0) + 1
    if times_fed >= 4:
        level = min(level + 1, max_level)
        times_fed = 0
    monster["times_fed"] = times_fed
    monster["level"] = level
    monster["happiness"] = 0
    now = int(time.time() * 1000)
    monster["last_fed"] = now
    monster["last_collection"] = now
    player_object["food"] = max(0, (player_object.get("food", 0) or 0) - food_cost)
    save_player(username, root)
    result = action_result(True, "user_monster_id", monster_id)
    result["food"] = player_object["food"]
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    result["level"] = level
    result["times_fed"] = times_fed
    return result, _monster_update(monster, "feed")
_COLLECTION_PLAYER_KEY = {"ethereal_currency": "ethereal_currency", "starpower": "starpower", "egg_wildcards": "wildcards"}
def _collection_player_key(collection_type):
    return _COLLECTION_PLAYER_KEY.get(_normalize_collection_type(collection_type), "coins")
def _monster_stored_coins(monster, max_coins, income_rate):
    stored = 0
    now = int(time.time() * 1000)
    last_collection = monster.get("last_collection", 0) or 0
    if last_collection <= 0:
        last_collection = monster.get("date_created", 0) or 0
    if 0 < last_collection < now:
        elapsed_seconds = max(0, (now - last_collection) // 1000)
        per_minute = max(1, income_rate)
        stored += (elapsed_seconds * per_minute) // 60
    cap = max_coins if max_coins > 0 else 2147483647
    return min(stored, cap)
def _add_collected_currency(player_object, collection_type, amount):
    if amount <= 0:
        return
    player_key = _collection_player_key(collection_type)
    updated = (player_object.get(player_key, 0) or 0) + amount
    if player_key == "coins":
        updated = min(1999999999, updated)
    player_object[player_key] = updated
    if player_key == "wildcards":
        player_object["egg_wildcards"] = updated
        player_object["playerEggWildcards"] = updated
def collect_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    now = int(time.time() * 1000)
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    if island is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True)
    island_type = island_type_of(island) or 1

    if monster_id == -1:
        monster_collections = []
        update_monster_list = []
        for monster in island.get("monsters") or []:
            if monster is None:
                continue
            collection_type, max_coins, income_rate = compute_monster_economy(monster, island_type)
            payout = _monster_stored_coins(monster, max_coins, income_rate)
            if payout <= 0:
                continue
            player_key = _collection_player_key(collection_type)
            _add_collected_currency(player_object, collection_type, payout)
            monster["collected_coins"] = 0
            monster["last_collection"] = now
            mid = monster.get("user_monster_id", 0)
            monster_collections.append({player_key: payout, "user_monster_id": SFSLong(mid)})
            update_monster_list.append({
                "collected_coins": 0, "user_monster_id": SFSLong(mid),
                "last_collection": SFSLong(now),
            })
        save_player(username, root)
        result = {
            "success": True,
            "monster_collections": monster_collections,
            "update_monster_list": update_monster_list,
        }
        return result, {}

    island2, monster = find_monster_with_island(player_object, monster_id, island)
    if monster is None:
        return action_result(False, "user_monster_id", monster_id, with_properties=True)
    collection_type, max_coins, income_rate = compute_monster_economy(monster, island_type)
    payout = _monster_stored_coins(monster, max_coins, income_rate)
    player_key = _collection_player_key(collection_type)
    if payout <= 0:
        result = {
            player_key: 0, "success": False,
            "message": "Normal monster: nothing to collect",
            "user_monster_id": SFSLong(monster_id),
        }
        return result, {}
    monster["collected_coins"] = 0
    monster["last_collection"] = now
    _add_collected_currency(player_object, collection_type, payout)
    save_player(username, root)
    result = {player_key: payout, "success": True, "user_monster_id": SFSLong(monster_id)}
    update = _monster_update(monster, "collect")
    update["properties"] = create_player_properties(player_object)
    return result, {"monster_updates": [update]}
def _find_nursery(island, requested_structure_id):
    structures = island.get("structures") or []
    if requested_structure_id:
        for structure in structures:
            if structure is not None and structure.get("user_structure_id") == requested_structure_id:
                return structure
    holders = [s for s in structures if s is not None and is_egg_holder_structure(s.get("structure", 0))]
    def _is_plain_nursery(holder):
        definition = get_structure_definition(holder.get("structure", 0))
        return bool(definition) and definition.get("structure_type") == "nursery"
    holders.sort(key=lambda h: 0 if _is_plain_nursery(h) else 1)
    for holder in holders:
        if not holder.get("occupied") and not holder.get("has_egg"):
            return holder
    return holders[0] if holders else None
def _find_fallback_egg(eggs):
    return eggs[-1] if eggs else None
def _find_egg(island, user_egg_id):
    for egg in island.get("eggs") or []:
        if egg is not None and egg.get("user_egg_id") == user_egg_id:
            return egg
    return None
def _find_island_with_egg(player_object, user_egg_id):
    for island in player_object.get("islands") or []:
        if island is not None and _find_egg(island, user_egg_id) is not None:
            return island
    return None
def buy_egg(username, params):
    monster_id = (params.get("monster_id") or params.get("monsterId") or params.get("monster")
                  or params.get("entity_id") or params.get("id") or 0)
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    if island is None:
        return {"success": False}, {}
    island_type = island_type_of(island) or 1
    definition = get_monster_definition(monster_id)
    if (definition is not None and island_type != MAGICAL_NEXUS_ISLAND_TYPE
            and not monster_allowed_on_island(definition, island_type)):
        resolved = resolve_monster_for_island(monster_id, island_type)
        if resolved != monster_id:
            monster_id = resolved

    if requires_direct_placement_on_purchase(get_monster_definition(monster_id), island_type):
        island_uid = island.get("user_island_id", 1000 + island_type)
        now = int(time.time() * 1000)
        build_ms = int((get_monster_definition(monster_id) or {}).get("build_time", 0) or 0) * 1000
        hatches_on = now if build_ms <= 0 else now + build_ms
        book_value = (get_monster_definition(monster_id) or {}).get("cost_coins", 0) or 0
        user_egg = {
            "monster": monster_id, "monster_id": monster_id,
            "laid_on": SFSLong(now), "hatches_on": SFSLong(hatches_on),
            "structure": SFSLong(0), "island": SFSLong(island_uid),
            "user_egg_id": SFSLong(monster_id), "costume": {"eq": 0, "p": []},
            "book_value": book_value,
        }
        island.setdefault("eggs", []).append(user_egg)
        import msm_rewardtracks
        properties = msm_rewardtracks.properties_with_encore(player_object, 2, 2)
        save_player(username, root)
        result = {
            "success": True, "remove_buyback": False,
            "properties": properties, "user_egg": user_egg,
        }
        return result, {}

    requested_structure_id = params.get("nursery_id") or params.get("structure_id") or 0
    nursery = _find_nursery(island, requested_structure_id)
    if nursery is None:
        result = {
            "success": False,
            "message": "Please use the island's egg holder for buying eggs!",
        }
        return result, {}
    next_egg_id = int(player_object.get("last_user_egg_id", 0) or 0) + 1
    player_object["last_user_egg_id"] = next_egg_id
    island_uid = island.get("user_island_id", 1000 + island_type)
    nursery_sid = nursery.get("user_structure_id", 0)
    now = int(time.time() * 1000)
    build_ms = int((get_monster_definition(monster_id) or {}).get("build_time", 0) or 0) * 1000
    hatches_on = now if build_ms <= 0 else now + build_ms
    book_value = (get_monster_definition(monster_id) or {}).get("cost_coins", 0) or 0
    user_egg = {
        "monster": monster_id, "monster_id": monster_id,
        "laid_on": SFSLong(now), "hatches_on": SFSLong(hatches_on),
        "structure": SFSLong(nursery_sid), "island": SFSLong(island_uid),
        "user_egg_id": SFSLong(next_egg_id), "costume": {"eq": 0, "p": []},
        "book_value": book_value,
    }
    eggs = island.setdefault("eggs", [])
    for i in range(len(eggs) - 1, -1, -1):
        if eggs[i] is not None and eggs[i].get("structure") == nursery_sid:
            del eggs[i]
    eggs.append(user_egg)
    nursery["occupied"] = True
    nursery["has_egg"] = True
    nursery["viewed"] = False
    nursery["obj_data"] = 1
    nursery["obj_end"] = 0
    nursery["finishing_time"] = 0
    nursery["building_completed"] = 0
    import msm_rewardtracks
    properties = msm_rewardtracks.properties_with_encore(player_object, 2, 2)
    save_player(username, root)
    result = {
        "success": True, "remove_buyback": False,
        "properties": properties,
        "user_egg": user_egg,
    }
    nursery_update = _nursery_touch_payload(nursery, player_object)
    return result, nursery_update
def _is_titansoul_definition(definition):
    if not definition:
        return False
    return (definition.get("class") or definition.get("fam") or "").upper() == "CLASS_TITANSOUL"
def backfill_titansoul_state(island):
    for monster in island.get("monsters") or []:
        if monster is None or monster.get("titansoul"):
            continue
        if _is_titansoul_definition(get_monster_definition(monster.get("monster"))):
            monster["titansoul"] = _default_titansoul_state()
def _default_titansoul_state():
    return {
        "create_reward_time": 0, "link_reset_time": 0, "num_links": 0, "soul_links": [],
        "rare_unlocked": False, "show_fx": True, "epic_unlocked": False, "num_unlinks": 0,
        "can_awaken": False, "rewards": [], "next_reward_time": 0,
    }
def _build_hatched_monster(monster_id, island, island_type, user_monster_id, pos_x, pos_y, flip, now, in_hotel=0):
    definition = get_monster_definition(monster_id)
    island_uid = island.get("user_island_id", 1000 + island_type)
    if is_box_monster_entity(definition):
        monster = build_placeholder_box_monster(monster_id, definition, island_uid, user_monster_id, pos_x, pos_y, flip, now, island_type)
    else:
        monster = {
            "user_monster_id": SFSLong(user_monster_id),
            "island": SFSLong(island_uid), "monster": monster_id,
            "pos_x": pos_x, "pos_y": pos_y, "flip": flip, "muted": 0,
            "level": 1, "happiness": 0, "times_fed": 0,
            "name": definition.get("common_name") or definition.get("name") or "",
            "in_hotel": in_hotel, "volume": SFSFloat(1.0),
            "last_collection": SFSLong(now), "last_feeding": SFSLong(now),
            "costume": {"eq": 0, "p": []},
            "book_value": definition.get("cost_coins", 0) or 0,
        }
        if _is_titansoul_definition(definition):
            monster["titansoul"] = _default_titansoul_state()
        common_name_lower = (definition.get("common_name") or "").lower()
        if "(major)" in common_name_lower:
            island_mode = 0
        elif "(minor)" in common_name_lower:
            island_mode = 1
        else:
            stored_mode = island.get("mode", island.get("island_mode"))
            island_mode = stored_mode if stored_mode is not None else 1
        build_paironormal_modes(monster, island_type, island_mode)
    return monster
def hatch_egg(username, params):
    pos_x = params.get("pos_x", 0)
    pos_y = params.get("pos_y", 0)
    flip = params.get("flip", 0)
    user_egg_id = params.get("user_egg_id", params.get("userEggId", 0)) or 0
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    if island is None or _find_egg(island, user_egg_id) is None:
        by_egg = _find_island_with_egg(player_object, user_egg_id)
        if by_egg is not None:
            island = by_egg
    if island is None:
        return {"success": False, "user_egg_id": SFSLong(user_egg_id)}
    eggs = island.setdefault("eggs", [])
    matched_egg = _find_egg(island, user_egg_id) or _find_fallback_egg(eggs)
    island_type = island_type_of(island) or 1
    nursery = None
    if matched_egg is None:
        candidate_definition = get_monster_definition(user_egg_id)
        if user_egg_id > 0 and requires_direct_placement(candidate_definition, island_type):
            monster_id = user_egg_id
        else:
            return {"success": False, "user_egg_id": SFSLong(user_egg_id)}
    else:
        monster_id = max(1, matched_egg.get("monster", 3) or 3)
        nursery_id = matched_egg.get("structure", 0)
        for structure in island.get("structures") or []:
            if structure is not None and structure.get("user_structure_id") == nursery_id:
                nursery = structure
                break
        if nursery is not None:
            nursery["occupied"] = False
            nursery["has_egg"] = False
            nursery["obj_data"] = 0
            nursery["obj_end"] = 0
        eggs.remove(matched_egg)
    monster_id = resolve_monster_for_island(monster_id, island_type)
    definition = get_monster_definition(monster_id)
    if definition is None:
        result = {
            "success": False, "error": "monster_not_available",
            "user_egg_id": SFSLong(user_egg_id),
        }
        return result
    user_monster_id = max(int(player_object.get("last_user_monster_id", 0) or 0) + 1, 20000 + random.randint(0, 899999))
    player_object["last_user_monster_id"] = user_monster_id
    island_uid = island.get("user_island_id", 1000 + island_type)
    now = int(time.time() * 1000)
    monster = _build_hatched_monster(monster_id, island, island_type, user_monster_id, pos_x, pos_y, flip, now)
    monsters = island.setdefault("monsters", [])
    monsters.append(monster)
    island_monster_count = len(monsters)
    island["num_monsters"] = island_monster_count
    _mark_monster_collected_in_book(island, monster_id)
    import msm_rewardtracks
    properties = msm_rewardtracks.properties_with_encore(player_object, 2, 5)
    save_player(username, root)
    result = {
        "success": True, "create_in_storage": False, "directPlace": nursery is None,
        "user_egg_id": SFSLong(user_egg_id), "island": SFSLong(island_uid),
        "properties": properties,
        "monster": monster,
    }
    return result
def sell_egg(username, params):
    user_egg_id = params.get("user_egg_id", params.get("userEggId", 0)) or 0
    root, player_object = load_player(username)
    island = _find_island_with_egg(player_object, user_egg_id) or find_island(player_object, get_active_island_id(player_object))
    result = {"success": False, "user_egg_id": SFSLong(user_egg_id), "properties": create_player_properties(player_object)}
    if island is None:
        return result, {}
    eggs = island.get("eggs") or []
    matched_egg = _find_egg(island, user_egg_id) or _find_fallback_egg(eggs)
    if matched_egg is None:
        return result, {}
    nursery_id = matched_egg.get("structure", 0)
    nursery = None
    for structure in island.get("structures") or []:
        if structure is not None and structure.get("user_structure_id") == nursery_id:
            nursery = structure
            break
    if nursery is not None:
        nursery["occupied"] = False
        nursery["has_egg"] = False
        nursery["obj_data"] = 0
        nursery["obj_end"] = 0
    eggs.remove(matched_egg)
    save_player(username, root)
    result["success"] = True
    result["properties"] = create_player_properties(player_object)
    nursery_update = _nursery_touch_payload(nursery, player_object) if nursery is not None else {}
    return result, nursery_update
def speed_up_hatching(username, params):
    user_egg_id = params.get("user_egg_id", params.get("userEggId", 0)) or 0
    root, player_object = load_player(username)
    result = {"success": False, "properties": create_player_properties(player_object)}
    add_actual_currencies(result, player_object)
    if not user_egg_id:
        return result, {}
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        egg = _find_egg(island, user_egg_id)
        if egg is None:
            continue
        laid_on = egg.get("laid_on", 0) or 0
        egg["hatches_on"] = SFSLong(laid_on)
        egg["ready"] = True
        nursery_id = egg.get("structure", 0)
        nursery = None
        for structure in island.get("structures") or []:
            if structure is not None and structure.get("user_structure_id") == nursery_id:
                nursery = structure
                break
        if nursery is not None:
            nursery["occupied"] = True
            nursery["has_egg"] = True
            nursery["obj_data"] = 1
            nursery["obj_end"] = laid_on
        save_player(username, root)
        result["success"] = True
        result["user_egg_id"] = SFSLong(user_egg_id)
        result["laid_on"] = SFSLong(laid_on)
        result["hatches_on"] = SFSLong(laid_on)
        result["properties"] = create_player_properties(player_object)
        add_actual_currencies(result, player_object)
        nursery_update = _nursery_touch_payload(nursery, player_object) if nursery is not None else {}
        return result, nursery_update
    return result, {}
def viewed_egg(username, params):
    user_egg_id = params.get("user_egg_id", params.get("userEggId", 0)) or 0
    root, player_object = load_player(username)
    island = _find_island_with_egg(player_object, user_egg_id) or find_island(player_object, get_active_island_id(player_object))
    egg = _find_egg(island, user_egg_id) if island is not None else None
    sold_update = None
    if egg is not None:
        egg["viewed"] = True
        _mark_monster_collected_in_book(island, egg.get("monster", 0))
        sold_update = _mark_monster_viewed_in_sold(island, egg.get("monster", 0))
        nursery_id = egg.get("structure", 0)
        nursery = None
        for structure in island.get("structures") or []:
            if structure is not None and structure.get("user_structure_id") == nursery_id:
                nursery = structure
                break
        if nursery is None:
            nursery = _find_nursery(island, nursery_id)
        if nursery is not None:
            nursery["viewed"] = True
            nursery["has_egg"] = True
            nursery["occupied"] = True
        save_player(username, root)
    return {"success": True}, sold_update
def claim_hatched_egg(username, params):
    result = {"success": True, "properties": []}
    for key in ("user_egg_id", "user_monster_id", "island", "structure_id"):
        value = params.get(key, 0) or 0
        if value:
            result[key] = SFSLong(value)
    monster = params.get("monster")
    if isinstance(monster, dict):
        result["monster"] = monster
    return result
def store_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    root, player_object = load_player(username)
    island, monster = find_monster_with_island(player_object, monster_id)
    if monster is not None:
        monster["in_hotel"] = 1
        save_player(username, root)
    return {"success": monster is not None, "user_monster_id": SFSLong(monster_id)}
def unstore_monster(username, params):
    monster_id = params.get("user_monster_id", 0)
    root, player_object = load_player(username)
    island, monster = find_monster_with_island(player_object, monster_id)
    if monster is not None:
        monster["in_hotel"] = 0
        pos_x = params.get("pos_x", monster.get("pos_x", 0))
        pos_y = params.get("pos_y", monster.get("pos_y", 0))
        flip = params.get("flip", monster.get("flip", 0))
        monster["pos_x"] = pos_x
        monster["pos_y"] = pos_y
        monster["col"] = pos_x
        monster["row"] = pos_y
        monster["flip"] = flip
        monster["flipped"] = flip
        save_player(username, root)
    return {"success": monster is not None, "user_monster_id": SFSLong(monster_id)}
def costume_action(username, params, command):
    costume_id = params.get("costume_id") or params.get("costume") or params.get("id") or 0
    monster_id = params.get("monster_id") or params.get("user_monster_id") or params.get("userMonsterId") or 0
    result = {"success": True}
    if monster_id:
        result["monster_id"] = SFSLong(monster_id)
    if costume_id:
        result["costume_id"] = costume_id
    root, player_object = load_player(username)
    if monster_id:
        _, monster = find_monster_with_island(player_object, monster_id)
        if monster is not None:
            existing = monster.get("costume") or {}
            monster["costume"] = {"eq": costume_id, "p": existing.get("p", [])}
            save_player(username, root)
    if command == "purchase_costume":
        result["properties"] = create_player_properties(player_object)
    return result
def update_owned_costumes(username, params):
    root, player_object = load_player(username)
    island_id = player_object.get("active_island", 1001) or 1001
    return {
        "success": True,
        "costumes_owned": "[" + ",".join(str(i) for i in range(1, 901)) + "]",
        "island_id": SFSLong(island_id),
        "properties": create_player_properties(player_object),
    }
def _find_breeding_record(player_object, breeding_id):
    if not breeding_id:
        return None, None
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        for record in island.get("breeding") or []:
            if record is not None and record.get("user_breeding_id") == breeding_id:
                return island, record
    return None, None
def _find_breeding_record_by_structure(player_object, structure_id):
    if not structure_id:
        return None, None
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        for record in island.get("breeding") or []:
            if record is not None and record.get("structure") == structure_id:
                return island, record
    return None, None
def _locate_breeding_structure(player_object, structure_id):
    island, structure = (None, None)
    if structure_id:
        island, structure = find_island_by_structure(player_object, structure_id)
    return island, structure
def breed_monsters(username, params):
    structure_id = params.get("structure_id") or params.get("user_structure_id") or params.get("user_breeding_id") or 0
    parent_a_id = params.get("user_monster_id_1", 0)
    parent_b_id = params.get("user_monster_id_2", 0)
    root, player_object = load_player(username)
    island, structure = _locate_breeding_structure(player_object, structure_id)
    if island is None:
        island = find_island(player_object, get_active_island_id(player_object))
    if structure is None and structure_id and island is not None:
        structure = find_structure(island, structure_id)
    if island is None or structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    parent_a = find_monster(island, parent_a_id)
    parent_b = find_monster(island, parent_b_id)
    if parent_a is None or parent_b is None or parent_a_id == parent_b_id:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    structure_sid = structure.get("user_structure_id", 0)
    breeding_list = island.setdefault("breeding", [])
    for i in range(len(breeding_list) - 1, -1, -1):
        if breeding_list[i] is not None and breeding_list[i].get("structure") == structure_sid:
            del breeding_list[i]
    monster_id = choose_breeding_result_monster(parent_a.get("monster", 0), parent_b.get("monster", 0))
    now = int(time.time() * 1000)
    build_ms = int((get_monster_definition(monster_id) or {}).get("build_time", 0) or 0) * 1000
    complete_on = now + build_ms
    next_breeding_id = max(int(player_object.get("last_user_breeding_id", 0) or 0) + 1, structure_sid + 1)
    player_object["last_user_breeding_id"] = next_breeding_id
    island_uid = island.get("user_island_id", 0)
    record = {
        "started_on": SFSLong(now), "island": SFSLong(island_uid),
        "new_monster": monster_id, "complete_on": SFSLong(complete_on),
        "user_breeding_id": SFSLong(next_breeding_id), "structure": SFSLong(structure_sid),
        "monster_1": parent_a.get("monster", 0), "monster_2": parent_b.get("monster", 0),
    }
    breeding_list.append(record)
    import msm_rewardtracks
    properties = msm_rewardtracks.properties_with_encore(player_object, 2, 2)
    save_player(username, root)
    return {
        "success": True, "user_structure_id": SFSLong(structure_sid),
        "user_monster_1": SFSLong(parent_a_id), "user_monster_2": SFSLong(parent_b_id),
        "user_breeding": record,
        "properties": properties,
    }
def speed_up_breeding(username, params):
    breeding_id = params.get("user_breeding_id") or params.get("breeding_id") or 0
    structure_id = params.get("structure_id") or params.get("user_structure_id") or params.get("breeding_structure_id") or 0
    root, player_object = load_player(username)
    island, record = _find_breeding_record(player_object, breeding_id)
    if record is None:
        island, record = _find_breeding_record_by_structure(player_object, breeding_id or structure_id)
    if record is None:
        result = {"success": False, "properties": create_player_properties(player_object)}
        return result, {}
    now = int(time.time() * 1000)
    complete_on = now - 1000
    record["complete_on"] = SFSLong(complete_on)
    save_player(username, root)
    result = {
        "success": True, "started_on": record.get("started_on"), "complete_on": SFSLong(complete_on),
        "userBreedingId": record.get("user_breeding_id"), "properties": create_player_properties(player_object),
    }
    return result, {}
def finish_breeding(username, params, force_complete=False):
    breeding_id = params.get("user_breeding_id") or params.get("breeding_id") or 0
    structure_id = params.get("structure_id") or params.get("user_structure_id") or params.get("breeding_structure_id") or 0
    root, player_object = load_player(username)
    island, record = _find_breeding_record(player_object, breeding_id)
    if record is None:
        island, record = _find_breeding_record_by_structure(player_object, breeding_id or structure_id)
    if record is None:
        island = find_island(player_object, get_active_island_id(player_object))
        for candidate in (island.get("breeding") or []) if island is not None else []:
            if candidate is not None:
                record = candidate
                break
    if island is None or record is None:
        return action_result(False, "user_breeding_id", breeding_id, with_properties=True)
    now = int(time.time() * 1000)
    complete_on = record.get("complete_on", 0) or 0
    if not force_complete and complete_on > now:
        result = action_result(False, "user_breeding_id", breeding_id, with_properties=True)
        result["complete_on"] = SFSLong(complete_on)
        return result
    nursery = _find_nursery(island, 0)
    if nursery is None or nursery.get("occupied") or (nursery.get("obj_data", 0) or 0) > 0:
        return action_result(False, "user_breeding_id", breeding_id, with_properties=True)
    monster_id = record.get("new_monster") or 0
    if not monster_id:
        parent_a_monster = record.get("monster_1", 0)
        parent_b_monster = record.get("monster_2", 0)
        monster_id = choose_breeding_result_monster(parent_a_monster, parent_b_monster)
    if not monster_id:
        return action_result(False, "user_breeding_id", breeding_id, with_properties=True)
    nursery_sid = nursery.get("user_structure_id", 0)
    eggs = island.setdefault("eggs", [])
    for i in range(len(eggs) - 1, -1, -1):
        if eggs[i] is not None and eggs[i].get("structure") == nursery_sid:
            del eggs[i]
    next_egg_id = int(player_object.get("last_user_egg_id", 0) or 0) + 1
    player_object["last_user_egg_id"] = next_egg_id
    build_ms = int((get_monster_definition(monster_id) or {}).get("build_time", 0) or 0) * 1000
    hatches_on = now if build_ms <= 0 else now + build_ms
    island_uid = island.get("user_island_id", 0)
    user_egg = {
        "hatches_on": SFSLong(hatches_on), "laid_on": SFSLong(now),
        "island": SFSLong(island_uid), "user_egg_id": next_egg_id,
        "costume": {"p": [], "eq": 0}, "structure": SFSLong(nursery_sid),
        "monster": monster_id,
    }
    eggs.append(user_egg)
    nursery["occupied"] = True
    nursery["has_egg"] = True
    nursery["viewed"] = True
    nursery["obj_data"] = 1
    nursery["obj_end"] = hatches_on
    finished_breeding_id = record.get("user_breeding_id", 0) or breeding_id
    breeding_list = island.get("breeding") or []
    if record in breeding_list:
        breeding_list.remove(record)
    import msm_rewardtracks
    encore_entry = msm_rewardtracks.encore_progress(player_object, 2, 2)
    result = {
        "success": True, "user_structure_id": SFSLong(nursery_sid),
        "user_egg": user_egg, "user_breeding_id": SFSLong(finished_breeding_id),
    }
    if encore_entry is not None:
        result["properties"] = [{"encore_event": encore_entry}] + create_player_properties(player_object)
    save_player(username, root)
    return result
def _resolve_teleport_target_island(player_object, requested_island_id, requested_island_type, send_home):
    if not send_home and not requested_island_id and not requested_island_type:
        requested_island_type = 20
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        user_island_id = island.get("user_island_id", 0)
        island_type = island_type_of(island)
        looks_like_type = 0 < requested_island_id < 1000
        matches_requested = requested_island_id > 0 and (
            user_island_id == requested_island_id
            or (looks_like_type and island_type == requested_island_id)
            or (looks_like_type and user_island_id == requested_island_id + 1000)
        )
        if not send_home:
            if (matches_requested
                    or (not requested_island_id and requested_island_type and island_type == requested_island_type)
                    or (not requested_island_id and not requested_island_type and island_type == 20)):
                return island
        elif matches_requested or user_island_id == requested_island_id:
            return island
    return None
def move_battle_monster(username, params, send_home):
    monster_id = (params.get("user_monster_id") or params.get("monster_id")
                  or params.get("source_user_monster_id") or params.get("id") or 0)
    requested_island_id = (
        params.get("destination_user_island_id") or params.get("target_user_island_id")
        or params.get("dest_island_id") or params.get("destination_island_id")
        or params.get("to_user_island_id") or 0
    )
    requested_island_type = (
        params.get("destination_island") or params.get("target_island") or params.get("dest_island")
        or params.get("sent_to_island") or params.get("island_type") or params.get("to_island_type") or 0
    )
    raw_island = params.get("island") or params.get("to_island") or 0
    if raw_island:
        if raw_island >= 1000 and not requested_island_id:
            requested_island_id = raw_island
        if raw_island < 1000 and not requested_island_type:
            requested_island_type = raw_island
    if not monster_id:
        return {"success": False}
    root, player_object = load_player(username)
    source_island, monster = find_monster_with_island(player_object, monster_id)
    if monster is None:
        return {"success": False}
    target_island = _resolve_teleport_target_island(player_object, requested_island_id, requested_island_type, send_home)
    if target_island is None and send_home:
        home_island_id = monster.get("battle_home_island_id", 0)
        target_island = find_island(player_object, home_island_id) if home_island_id else None
    if target_island is None:
        return {"success": False}
    _ensure_battle_island_layout(target_island)
    source_island_id = source_island.get("user_island_id", 0)
    if not send_home:
        monster["battle_home_island_id"] = source_island_id
        monster["battle_home_island"] = island_type_of(source_island)
    if source_island is not target_island:
        source_island["monsters"] = [m for m in (source_island.get("monsters") or []) if m is not monster]
        target_island.setdefault("monsters", []).append(monster)
    target_island_id = target_island.get("user_island_id", 0)
    target_type = island_type_of(target_island)
    monster["island"] = target_island_id
    monster["island_type"] = target_type
    monster["user_island_id"] = target_island_id
    if send_home:
        monster.pop("battle_home_island_id", None)
        monster.pop("battle_home_island", None)
    save_player(username, root)
    return {
        "success": True, "user_monster_id": SFSLong(monster_id),
        "sent_to_island": target_type,
        "dest_nursery": SFSLong(1 if (not send_home and target_type == 20) else 2),
    }
def send_to_magical_nexus(username, params):
    monster_id = (params.get("user_monster_id") or params.get("monster_id")
                  or params.get("source_user_monster_id") or params.get("id") or 0)
    if not monster_id:
        return {"success": False}, None
    root, player_object = load_player(username)
    source_island, monster = find_monster_with_island(player_object, monster_id)
    if monster is None:
        return {"success": False}, None
    target_island = None
    for island in player_object.get("islands") or []:
        if island is not None and island_type_of(island) == MAGICAL_NEXUS_ISLAND_TYPE:
            target_island = island
            break
    if target_island is None:
        return {"success": False}, None
    nursery = _find_nursery(target_island, 0)
    if nursery is None or nursery.get("occupied") or (nursery.get("obj_data", 0) or 0) > 0:
        return {"success": False}, None
    monster_type = monster.get("monster", 0)
    source_island["monsters"] = [m for m in (source_island.get("monsters") or []) if m is not monster]
    nursery_sid = nursery.get("user_structure_id", 0)
    eggs = target_island.setdefault("eggs", [])
    for i in range(len(eggs) - 1, -1, -1):
        if eggs[i] is not None and eggs[i].get("structure") == nursery_sid:
            del eggs[i]
    next_egg_id = int(player_object.get("last_user_egg_id", 0) or 0) + 1
    player_object["last_user_egg_id"] = next_egg_id
    now = int(time.time() * 1000)
    build_ms = int((get_monster_definition(monster_type) or {}).get("build_time", 0) or 0) * 1000
    hatches_on = now if build_ms <= 0 else now + build_ms
    island_uid = target_island.get("user_island_id", 0)
    user_egg = {
        "monster": monster_type, "monster_id": monster_type,
        "laid_on": SFSLong(now), "hatches_on": SFSLong(hatches_on),
        "structure": SFSLong(nursery_sid), "nursery_id": SFSLong(nursery_sid),
        "user_structure_id": SFSLong(nursery_sid),
        "user_island_id": SFSLong(island_uid), "island": SFSLong(island_uid),
        "user_egg_id": next_egg_id, "viewed": True, "ready": build_ms <= 0,
        "costume": {"eq": 0, "p": []},
    }
    eggs.append(user_egg)
    nursery["occupied"] = True
    nursery["has_egg"] = True
    nursery["viewed"] = True
    nursery["obj_data"] = 1
    nursery["obj_end"] = hatches_on
    save_player(username, root)
    return {
        "success": True, "user_monster_id": SFSLong(monster_id),
        "sent_to_island": island_type_of(target_island),
        "dest_nursery": SFSLong(1),
    }, nursery
def place_on_gold_island(username, params):
    monster_id = (params.get("user_monster_id") or params.get("monster_id")
                  or params.get("source_user_monster_id") or params.get("id") or 0)
    pos_x = params.get("pos_x", 20)
    pos_y = params.get("pos_y", 18)
    if not monster_id:
        return {"success": False}
    root, player_object = load_player(username)
    source_island, monster = find_monster_with_island(player_object, monster_id)
    if monster is None:
        return {"success": False}
    gold_island = None
    for island in player_object.get("islands") or []:
        if island is not None and island_type_of(island) == GOLD_ISLAND_TYPE:
            gold_island = island
            break
    if gold_island is None:
        return {"success": False}
    next_id = max(int(player_object.get("last_user_monster_id", 0) or 0) + 1, 20000 + random.randint(0, 899999))
    player_object["last_user_monster_id"] = next_id
    now = int(time.time() * 1000)
    clone = {
        "level": monster.get("level", 1),
        "island": SFSLong(gold_island.get("user_island_id", 0)),
        "last_feeding": SFSLong(now),
        "in_hotel": 0,
        "parent_island": SFSLong(source_island.get("user_island_id", 0)),
        "last_collection": SFSLong(now),
        "monster": monster.get("monster", 0),
        "pos_y": pos_y, "volume": SFSFloat(1.0), "pos_x": pos_x,
        "times_fed": 0, "happiness": 0,
        "name": monster.get("name", ""),
        "parent_monster": SFSLong(monster_id),
        "muted": 0, "flip": 0,
        "costume": monster.get("costume", {"eq": 0, "p": []}),
        "user_monster_id": SFSLong(next_id),
    }
    if "box_requirements" in monster:
        clone["box_requirements"] = monster.get("box_requirements")
    if "boxed_eggs" in monster:
        clone["boxed_eggs"] = monster.get("boxed_eggs")
    gold_island.setdefault("monsters", []).append(clone)
    save_player(username, root)
    return {"success": True, "user_monster_id": SFSLong(monster_id), "monster": clone}
def cancel_breeding(username, params):
    structure_id = params.get("structure_id") or params.get("user_structure_id") or 0
    root, player_object = load_player(username)
    island, record = _find_breeding_record_by_structure(player_object, structure_id)
    if island is None or record is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    breeding_list = island.get("breeding") or []
    if record in breeding_list:
        breeding_list.remove(record)
    save_player(username, root)
    return {"success": True, "user_structure_id": SFSLong(structure_id)}
