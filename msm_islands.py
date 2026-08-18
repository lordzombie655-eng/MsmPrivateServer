import random
import time
from msm_gamedata import (
    get_max_structure_id, get_structure_definition, is_valid_island_id, island_for_theme, resolve_island_type,
)
from msm_playerdata import (
    SFSLong, add_actual_currencies, create_player_properties, find_island,
    get_active_island_id, load_player, save_player,
)
PAIRONORMAL_ISLAND_TYPE = 31
PAIRONORMAL_DEFAULT_STRUCTURES = [
    (1069, 31, 16, 0),
    (1064, 32, 29, 0),
    (1062, 17, 3, 0),
    (1051, 12, 27, 0),
]
def _make_structure(user_island_id, island_type, structure_id, pos_x, pos_y, flip, level, now):
    return {
        "user_structure_id": 10000 + random.randint(0, 989999),
        "user_island_id": user_island_id, "island": user_island_id,
        "island_type": island_type, "book_value": 100,
        "pos_x": pos_x, "pos_y": pos_y, "col": pos_x, "row": pos_y,
        "flip": flip, "flipped": flip, "muted": 0, "in_warehouse": 0,
        "is_upgrading": 0, "is_complete": 1,
        "structure": structure_id, "structure_id": structure_id,
        "scale": 1.0, "level": level,
        "building_completed": now, "date_created": now, "last_collection": now,
        "obj_data": 0, "obj_end": 0,
    }
ETHEREAL_ISLAND_TYPES = (26, 27, 28, 29)
ETHEREAL_DEFAULT_STRUCTURES = [
    (1049, 8, 14, 0),
    (1028, 6, 12, 0),
    (1028, 5, 12, 0),
    (804, 4, 4, 0),
]
def default_island_structures(user_island_id, island_type):
    now = int(time.time() * 1000)
    if island_type == PAIRONORMAL_ISLAND_TYPE:
        return [
            _make_structure(user_island_id, island_type, sid, x, y, flip,
                             (get_structure_definition(sid) or {}).get("level", 1) or 1, now)
            for sid, x, y, flip in PAIRONORMAL_DEFAULT_STRUCTURES
        ]
    if island_type in ETHEREAL_ISLAND_TYPES:
        return [
            _make_structure(user_island_id, island_type, sid, x, y, flip,
                             (get_structure_definition(sid) or {}).get("level", 1) or 1, now)
            for sid, x, y, flip in ETHEREAL_DEFAULT_STRUCTURES
        ]
    structures = []
    special_positions = {
        1: {"castle": (29, 9), "nursery": (11, 10), "breeding": (17, 37)},
        2: {"castle": (29, 9), "nursery": (24, 28), "breeding": (21, 3)},
        9: {"castle": (24, 14)},
        20: {"nursery": (29, 9)},
        25: {"nursery": (33, 22)},
    }
    overrides = special_positions.get(island_type, {})
    placements = [
        ("castle", overrides.get("castle", (29, 9))),
        ("nursery", overrides.get("nursery", (35, 17))),
        ("breeding", overrides.get("breeding", (21, 3))),
    ]
    for structure_type, (pos_x, pos_y) in placements:
        structure_id = get_max_structure_id(island_type, structure_type)
        if not structure_id:
            continue
        definition = get_structure_definition(structure_id) or {}
        level = definition.get("level", 1) or 1
        if level <= 0:
            level = 1
        structures.append(_make_structure(user_island_id, island_type, structure_id, pos_x, pos_y, 0, level, now))
    return structures
def _resolve_catalog_id(island, fallback):
    existing = island.get("island")
    if isinstance(existing, int) and is_valid_island_id(existing):
        return existing
    mirror_of = island.get("mirror_of_island_id")
    if isinstance(mirror_of, int) and is_valid_island_id(mirror_of):
        return mirror_of
    return fallback
def backfill_island_type(island):
    user_island_id = island.get("user_island_id", 0) or 0
    if user_island_id < 1000 or user_island_id >= 100000000:
        return
    fallback = island.get("mirror_of_island_id") or (user_island_id - 1000)
    catalog_id = _resolve_catalog_id(island, fallback)
    resolved = resolve_island_type(catalog_id)
    island.pop("mirror_of_island_id", None)
    island.pop("island_id", None)
    island["island"] = catalog_id
    island["type"] = resolved
    island["island_type"] = resolved
def migrate_legacy_mirror_ids(player_object):
    islands = player_object.get("islands") or []
    existing_ids = {isl.get("user_island_id") for isl in islands if isl is not None}
    active = player_object.get("active_island")
    for island in islands:
        if island is None:
            continue
        old_uid = island.get("user_island_id", 0) or 0
        if not (1100 <= old_uid < 2000):
            continue
        legacy_island_id = old_uid - 1000
        fallback = island.get("mirror_of_island_id") or legacy_island_id
        catalog_id = _resolve_catalog_id(island, fallback)
        new_uid = random.randint(100000000, 999999999)
        while new_uid in existing_ids:
            new_uid = random.randint(100000000, 999999999)
        existing_ids.discard(old_uid)
        existing_ids.add(new_uid)
        island["user_island_id"] = new_uid
        island.pop("mirror_of_island_id", None)
        island.pop("island_id", None)
        island["island"] = catalog_id
        island["type"] = resolve_island_type(catalog_id)
        island["island_type"] = island["type"]
        for structure in island.get("structures") or []:
            if structure is not None:
                if structure.get("user_island_id") == old_uid:
                    structure["user_island_id"] = new_uid
                if structure.get("island") == old_uid:
                    structure["island"] = new_uid
        for monster in island.get("monsters") or []:
            if monster is not None and monster.get("island") == old_uid:
                monster["island"] = new_uid
        for egg in island.get("eggs") or []:
            if egg is not None and egg.get("island") == old_uid:
                egg["island"] = new_uid
        if active == old_uid:
            player_object["active_island"] = new_uid
def buy_island(username, params):
    island_id = params.get("island_id", 0)
    island_type = resolve_island_type(island_id)
    root, player_object = load_player(username)
    existing_ids = {isl.get("user_island_id") for isl in player_object.get("islands") or [] if isl is not None}
    if island_id == island_type:
        user_island_id = 1000 + island_id
        if user_island_id in existing_ids:
            return {"success": False, "cmd": "gs_buy_island", "message": "Island already bought!"}
    else:
        for isl in player_object.get("islands") or []:
            if isl is not None and isl.get("island") == island_id:
                return {"success": False, "cmd": "gs_buy_island", "message": "Island already bought!"}
        user_island_id = random.randint(100000000, 999999999)
        while user_island_id in existing_ids:
            user_island_id = random.randint(100000000, 999999999)
    new_island = {
        "eggs": [], "warp_speed": 1.0, "island": island_id,
        "structures": default_island_structures(user_island_id, island_type),
        "monsters": [], "dislikes": 0, "likes": 0, "fuzer": [], "baking": [],
        "costumes_owned": [], "breeding": [], "torches": [], "last_player_level": 75,
        "num_torches": 0, "user_island_id": SFSLong(user_island_id), "user": SFSLong(100000000),
        "type": island_type, "island_type": island_type,
    }
    if island_type == 9:
        new_island["tribal_requests"] = []
        new_island["tribal_quests"] = []
        new_island["tribal_island_data"] = {
            "chief_name": "@msm_hacks", "name": "@msm_hacks",
            "user_island_id": SFSLong(user_island_id), "chief": SFSLong(100000000),
            "members": 1, "monsters": 999, "rank": 999999,
        }
    player_object.setdefault("islands", []).append(new_island)
    save_player(username, root)
    result = {
        "success": True,
        "properties": create_player_properties(player_object),
        "tracks": [],
        "user_island": new_island,
    }
    add_actual_currencies(result, player_object)
    return result
def update_island_mode(username, params):
    user_island_id = params.get("user_island_id", 0)
    if not user_island_id:
        island_field = params.get("island", 0)
        if island_field:
            user_island_id = 1000 + island_field
    mode = params.get("mode", 0)
    root, player_object = load_player(username)
    for island in player_object.get("islands") or []:
        current_id = island.get("user_island_id", 0)
        island_field = island.get("island", 0)
        if user_island_id and current_id != user_island_id and island_field != (user_island_id - 1000):
            continue
        island["mode"] = mode
        island["island_mode"] = mode
        if get_active_island_id(player_object) == current_id:
            player_object["active_island_mode"] = mode
        break
    save_player(username, root)
    result = {"success": True, "mode": mode}
    if user_island_id:
        result["user_island_id"] = SFSLong(user_island_id)
    if "island" in params:
        result["island"] = params.get("island", 0)
    return result
def mute_island(username, params):
    user_island_id = params.get("user_island_id", params.get("island_id", params.get("island", 0))) or 0
    muted = params.get("muted", 0)
    root, player_object = load_player(username)
    if not user_island_id:
        user_island_id = get_active_island_id(player_object)
    if 0 < user_island_id < 1000:
        user_island_id += 1000
    monster_ids, structure_ids = [], []
    for island in player_object.get("islands") or []:
        if island.get("user_island_id") != user_island_id:
            continue
        island["muted"] = muted
        for monster in island.get("monsters") or []:
            monster["muted"] = muted
            mid = monster.get("user_monster_id")
            if mid:
                monster_ids.append(int(mid))
        for structure in island.get("structures") or []:
            structure_def_id = structure.get("structure", structure.get("structure_id", 0))
            definition = get_structure_definition(structure_def_id)
            if not definition or definition.get("structure_type") != "castle":
                continue
            structure["muted"] = muted
            sid = structure.get("user_structure_id")
            if sid:
                structure_ids.append(int(sid))
        break
    save_player(username, root)
    return {
        "success": True, "user_island_id": SFSLong(user_island_id), "muted": muted,
        "monsters_muted": str(monster_ids), "structures_muted": str(structure_ids),
    }
def set_warp_island(username, params):
    user_island_id = params.get("user_island_id", 0)
    warp_speed = params.get("warp_speed", 1.0)
    root, player_object = load_player(username)
    island = find_island(player_object, user_island_id)
    if island is not None:
        island["warp_speed"] = warp_speed
        save_player(username, root)
    return {"success": True}
def _upsert_active_theme(player_object, theme_id, island_type):
    themes = player_object.setdefault("active_island_themes", [])
    for i in range(len(themes) - 1, -1, -1):
        existing = themes[i]
        if existing is None:
            continue
        existing_island = existing.get("i", existing.get("island", existing.get("island_id", 0))) or 0
        if existing_island >= 1000:
            existing_island -= 1000
        if existing_island == island_type:
            del themes[i]
    themes.append({"t": theme_id, "i": island_type})
    return themes
def buy_island_skin(username, params):
    theme_id = (params.get("island_theme_id") or params.get("user_island_theme_id")
                or params.get("theme_id") or params.get("skin_id") or params.get("skin")
                or params.get("theme") or params.get("id") or params.get("storeitem_id") or 1)
    requested_island = params.get("island_id") or params.get("user_island_id") or params.get("island") or 0
    island_type = requested_island - 1000 if requested_island >= 1000 else requested_island
    theme_island = island_for_theme(theme_id)
    if theme_island:
        island_type = theme_island
    elif not island_type:
        island_type = 1
    root, player_object = load_player(username)
    themes = _upsert_active_theme(player_object, theme_id, island_type)
    save_player(username, root)
    theme = {"t": theme_id, "i": island_type}
    return {
        "success": True, "cmd": "gs_buy_island_skin",
        "island_id": SFSLong(1000 + island_type), "user_island_id": SFSLong(1000 + island_type),
        "island": island_type, "user_island_theme_id": theme_id, "theme_id": theme_id, "skin_id": theme_id,
        "cost_diamonds": 0, "price": 0, "currency": "diamonds",
        "active_island_theme": theme, "island_theme": theme,
        "properties": create_player_properties(player_object), "active_island_themes": themes,
    }
def activate_island_theme(username, params):
    full = buy_island_skin(username, params)
    return {
        "success": True, "buy_and_activate_now": False,
        "island": full.get("island", 1), "user_island_theme_id": full.get("theme_id", 1),
        "trial": bool(params.get("trial")),
        "properties": full.get("properties", []),
    }
def get_island_rank(username, params):
    requested_island = params.get("island_id") or params.get("user_island_id") or params.get("island") or 0
    island_type = (requested_island - 1000 if requested_island >= 1000 else requested_island) or 1
    root, player_object = load_player(username)
    display_name = player_object.get("display_name") or username
    bbb_id = player_object.get("bbb_id", 0) or 0
    theme = {
        "i": island_type, "island": island_type, "island_id": SFSLong(1000 + island_type),
        "theme_id": 1, "skin_id": 1, "storeitem_id": 0,
        "cost_diamonds": 2500, "price": 2500, "currency": "diamonds",
    }
    entry = {
        "rank": 1, "island_rank": 1, "score": 0, "likes": 999,
        "bbb_id": SFSLong(bbb_id), "user_id": SFSLong(bbb_id),
        "display_name": display_name, "player_name": display_name,
        "island_id": SFSLong(1000 + island_type), "user_island_id": SFSLong(1000 + island_type),
        "island": island_type, "island_type": island_type,
        "active_island_theme": theme, "island_theme": theme,
    }
    return {
        "success": True, "cmd": "gs_get_island_rank",
        "island_id": SFSLong(1000 + island_type), "user_island_id": SFSLong(1000 + island_type),
        "island": island_type, "island_type": island_type,
        "rank": 1, "island_rank": 1, "total_players": 1, "score": 0, "likes": 999,
        "rankings": [entry], "island_rankings": [entry], "islands": [entry],
        "island_data": [entry], "players": [entry],
        "active_island_theme": theme, "island_theme": theme,
        "theme_id": 1, "skin_id": 1, "cost_diamonds": 2500, "price": 2500, "currency": "diamonds",
    }
def set_last_timed_theme(username, params):
    root, player_object = load_player(username)
    player_object["last_timed_theme"] = {
        "theme_id": params.get("theme_id") or params.get("island_theme_id") or 0,
        "tut_stage": params.get("tut_stage") or 0,
    }
    save_player(username, root)
    return {"success": True}
def mute_castle(username, params):
    user_island_id = params.get("user_island_id") or params.get("island_id") or params.get("island") or 0
    muted = params.get("muted", 0)
    root, player_object = load_player(username)
    if user_island_id:
        island = find_island(player_object, user_island_id + 1000 if user_island_id < 1000 else user_island_id)
    else:
        island = find_island(player_object, get_active_island_id(player_object))
    structure_ids = []
    if island is not None:
        for structure in island.get("structures") or []:
            if structure is None:
                continue
            sid = structure.get("structure", structure.get("structure_id", 0))
            definition = get_structure_definition(sid)
            if not definition or definition.get("structure_type") != "castle":
                continue
            structure["muted"] = muted
            structure_ids.append(structure.get("user_structure_id", 0))
        save_player(username, root)
    return {
        "success": True,
        "user_island_id": SFSLong((island.get("user_island_id", user_island_id) if island is not None else user_island_id) or 0),
        "muted": muted, "monsters_muted": "[]", "structures_muted": str(structure_ids),
        "properties": create_player_properties(player_object),
    }
def get_island_boosts(username, params):
    return {
        "success": True, "boosts": [], "island_boosts": [], "active_boosts": [],
        "modifiers": [], "has_boosts": False, "properties": [],
    }
