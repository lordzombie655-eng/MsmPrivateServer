import json
import random
import time
from msm_gamedata import (
    build_paironormal_modes, get_bakery_food, get_ethereal_islet_definition,
    get_monster_level_definition, get_structure_definition,
)
from msm_playerdata import (
    SFSLong, action_result, add_actual_currencies, create_player_properties,
    find_island, find_island_by_structure, find_monster_with_island, find_structure,
    get_active_island_id, island_type_of, load_player, save_player,
)
from msm_protocol import SFSFloat
def _is_movable(structure_id):
    definition = get_structure_definition(structure_id)
    return definition is None or definition.get("movable", 1) != 0
def _upgrade_target(structure_id):
    definition = get_structure_definition(structure_id)
    if not definition:
        return 0
    return definition.get("upgrades_to", 0) or 0
def _locate(player_object, structure_id):
    island, structure = find_island_by_structure(player_object, structure_id)
    if island is None:
        island = find_island(player_object, get_active_island_id(player_object))
        structure = find_structure(island, structure_id)
    return island, structure
def _structure_update(structure, mode="full"):
    structure_id = SFSLong(structure.get("user_structure_id", 0))
    user_island_id = structure.get("user_island_id", 0)
    island_type = structure.get("island_type", structure.get("island", 0)) or 0
    if (island_type <= 0 or island_type >= 1000) and user_island_id >= 1000:
        island_type = user_island_id - 1000
    raw_island = structure.get("island", user_island_id if user_island_id > 0 else island_type)
    if 0 < raw_island < 1000 and user_island_id >= 1000:
        raw_island = user_island_id
    pos_x = structure.get("pos_x", structure.get("col", 0))
    pos_y = structure.get("pos_y", structure.get("row", 0))
    flip = structure.get("flip", structure.get("flipped", 0))
    scale = SFSFloat(structure.get("scale", 1.0) or 1.0)
    update = {
        "user_structure_id": structure_id,
        "user_island_id": SFSLong(user_island_id),
        "island": SFSLong(raw_island),
        "island_type": int(island_type),
    }
    if mode == "move":
        update["pos_x"] = pos_x
        update["pos_y"] = pos_y
        update["scale"] = scale
        update["properties"] = [{"pos_x": pos_x}, {"pos_y": pos_y}, {"scale": scale}]
    elif mode == "flip":
        update["flip"] = flip
    elif mode == "upgrade":
        building_completed = structure.get("building_completed", 0) or 0
        remaining = max(0, (building_completed - int(time.time() * 1000)) // 1000) if building_completed else 0
        update.update({
            "structure": structure.get("structure", 0),
            "structure_id": structure.get("structure", 0),
            "pos_x": pos_x, "pos_y": pos_y, "col": pos_x, "row": pos_y,
            "scale": scale, "flip": flip, "flipped": flip,
            "muted": structure.get("muted", 0), "in_warehouse": structure.get("in_warehouse", 0),
            "occupied": structure.get("occupied", 0), "has_egg": structure.get("has_egg", 0),
            "viewed": structure.get("viewed", 0), "book_value": structure.get("book_value", 100),
            "date_created": SFSLong(structure.get("date_created", 0) or 0),
            "last_collection": SFSLong(structure.get("last_collection", 0) or 0),
            "last_collected": SFSLong(structure.get("last_collected", structure.get("last_collection", 0)) or 0),
            "level": structure.get("level", 1),
            "is_upgrading": structure.get("is_upgrading", 0), "is_complete": structure.get("is_complete", 1),
            "building_completed": SFSLong(building_completed),
            "finishing_time": SFSLong(structure.get("finishing_time", structure.get("obj_end", 0)) or 0),
            "obj_data": structure.get("obj_data", 0), "obj_end": SFSLong(structure.get("obj_end", 0) or 0),
            "pending_upgrade_structure": structure.get("pending_upgrade_structure", 0),
            "complete_on": SFSLong(building_completed), "seconds_remaining": SFSLong(remaining),
            "time_remaining": SFSLong(remaining),
        })
    else:
        update.update({
            "structure": structure.get("structure", 0),
            "pos_x": pos_x, "pos_y": pos_y, "scale": scale, "flip": flip,
            "muted": structure.get("muted", 0), "in_warehouse": structure.get("in_warehouse", 0),
            "is_upgrading": structure.get("is_upgrading", 0), "is_complete": structure.get("is_complete", 1),
            "building_completed": SFSLong(structure.get("building_completed", 0) or 0),
            "last_collection": SFSLong(structure.get("last_collection", 0) or 0),
            "obj_data": structure.get("obj_data", 0), "obj_end": SFSLong(structure.get("obj_end", 0) or 0),
            "level": structure.get("level", 1),
            "occupied": bool(structure.get("occupied", False)),
            "has_egg": bool(structure.get("has_egg", False)),
            "viewed": bool(structure.get("viewed", False)),
        })
    update.setdefault("properties", [])
    return update
def _first_param(params, keys, default=0):
    for key in keys:
        value = params.get(key)
        if value is not None:
            return value
    return default
def move_structure(username, params):
    structure_id = _first_param(params, ("user_structure_id", "userStructureId", "structure_id", "structureId", "id"), 0)
    pos_x = _first_param(params, ("pos_x", "x", "col", "column"), 0)
    pos_y = _first_param(params, ("pos_y", "y", "row"), 0)
    scale = _first_param(params, ("scale", "size"), 1.0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    if _is_movable(structure.get("structure", 0)):
        structure["pos_x"] = pos_x
        structure["pos_y"] = pos_y
        structure["col"] = pos_x
        structure["row"] = pos_y
        structure["scale"] = scale
        save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, _structure_update(structure, "move")
def flip_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    flipped = params.get("flipped", False)
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    structure = find_structure(island, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    structure["flip"] = 1 if flipped else 0
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    return result, _structure_update(structure, "flip")
def sell_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island = find_island(player_object, get_active_island_id(player_object))
    if island is not None:
        structures = island.get("structures") or []
        for i in range(len(structures) - 1, -1, -1):
            if structures[i] is not None and structures[i].get("user_structure_id") == structure_id:
                del structures[i]
                break
        save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result
def mute_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    result = action_result(structure is not None, "user_structure_id", structure_id)
    muted = 0
    update = {}
    if structure is not None:
        current = structure.get("muted", 0)
        muted = params.get("muted", 0 if current else 1)
        structure["muted"] = muted
        save_player(username, root)
        update = _structure_update(structure, "full")
    result["muted"] = muted
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, update
def _flat_structure_snapshot(structure):
    return {
        "user_structure_id": SFSLong(structure.get("user_structure_id", 0)),
        "island": SFSLong(structure.get("island", 0) or 0),
        "structure": structure.get("structure", 0),
        "pos_x": structure.get("pos_x", 0),
        "pos_y": structure.get("pos_y", 0),
        "scale": SFSFloat(structure.get("scale", 1.0) or 1.0),
        "flip": structure.get("flip", 0),
        "muted": structure.get("muted", 0),
        "in_warehouse": structure.get("in_warehouse", 0),
        "is_upgrading": structure.get("is_upgrading", 0),
        "is_complete": structure.get("is_complete", 1),
        "building_completed": SFSLong(structure.get("building_completed", 0) or 0),
        "last_collection": SFSLong(structure.get("last_collection", 0) or 0),
    }
def start_upgrade_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    next_id = _upgrade_target(structure.get("structure", 0))
    success = next_id > 0
    if success:
        now = int(time.time() * 1000)
        definition = get_structure_definition(next_id)
        build_ms = max(0, (definition.get("build_time", 0) if definition else 0)) * 1000
        if build_ms <= 0:
            structure["structure"] = next_id
            structure["level"] = structure.get("level", 0) + 1
            structure["is_upgrading"] = 0
            structure["is_complete"] = 1
            structure["building_completed"] = 0
            structure["obj_end"] = 0
            structure["pending_upgrade_structure"] = 0
        else:
            complete_on = now + build_ms
            structure["is_upgrading"] = 1
            structure["is_complete"] = 0
            structure["obj_data"] = 1
            structure["building_completed"] = complete_on
            structure["obj_end"] = complete_on
            structure["finishing_time"] = complete_on
            structure["pending_upgrade_structure"] = next_id
        save_player(username, root)
    result = action_result(success, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    update = {}
    if success:
        result["user_structure"] = _flat_structure_snapshot(structure)



        update = _structure_update(structure, "upgrade")
    return result, update
def speed_up_upgrade_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None or not structure.get("is_upgrading"):
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    finished_at = int(time.time() * 1000)
    structure["building_completed"] = finished_at
    structure["obj_end"] = finished_at
    structure["finishing_time"] = finished_at
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    result["building_completed"] = SFSLong(finished_at)
    return result, _structure_update(structure, "upgrade")
def finish_upgrade_structure(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    next_id = structure.get("pending_upgrade_structure") or _upgrade_target(structure.get("structure", 0))
    success = next_id > 0
    if success:
        structure["structure"] = next_id
        structure["level"] = structure.get("level", 0) + 1
        structure["is_upgrading"] = 0
        structure["is_complete"] = 1
        structure["building_completed"] = 0
        structure["obj_end"] = 0
        structure["finishing_time"] = 0
        structure["pending_upgrade_structure"] = 0
        structure["obj_data"] = 0
        save_player(username, root)
    result = action_result(success, "user_structure_id", structure_id)
    result["properties"] = create_player_properties(player_object)
    if success:
        result["user_structure"] = _flat_structure_snapshot(structure)
    return result
def start_fuguing(username, params):
    structure_id = params.get("user_structure_id", 0)
    monster_id = params.get("user_monster_id", params.get("monster_id", 0)) or 0
    activated_mode = params.get("activated_mode", 1) or 1
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    definition = get_structure_definition(structure.get("structure", 0)) or {}
    now = int(time.time() * 1000)
    duration_ms = max(0, definition.get("build_time", 0) or 0) * 1000
    complete_on = now + duration_ms
    structure["is_upgrading"] = 1
    structure["obj_data"] = 1
    structure["obj_end"] = complete_on
    structure["fuguing_monster"] = monster_id
    structure["fuguing_mode"] = activated_mode
    _, fuguing_monster = find_monster_with_island(player_object, monster_id) if monster_id else (None, None)
    if fuguing_monster is not None:
        level = max(1, fuguing_monster.get("level", 1) or 1)
        times_fed = (fuguing_monster.get("times_fed", 0) or 0) + 1
        if times_fed >= 4:
            level += 1
            times_fed = 0
        fuguing_monster["times_fed"] = times_fed
        fuguing_monster["level"] = level
        fuguing_monster["happiness"] = 0
        fuguing_monster["last_fed"] = now
        fuguing_monster["last_collection"] = now
    save_player(username, root)
    result = {
        "success": True, "user_structure_id": SFSLong(structure_id), "used_monster": monster_id,
        "user_fuguing_data": {
            "started_on": SFSLong(now), "complete_on": SFSLong(complete_on),
            "activated_mode": activated_mode, "structure": structure_id, "monster": monster_id,
            "success": True,
        },
        "properties": create_player_properties(player_object),
    }
    add_actual_currencies(result, player_object)
    return result, {}
def speed_up_fuguing(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    finished_at = int(time.time() * 1000)
    structure["obj_end"] = finished_at
    result = action_result(True, "user_structure_id", structure_id)
    result["obj_end"] = SFSLong(finished_at)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    save_player(username, root)
    return result, {}
def finish_fuguing(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True), {}
    reward = 99
    player_object["starpower"] = (player_object.get("starpower", 0) or 0) + reward
    player_object["starpower_actual"] = player_object["starpower"]
    player_object["earned_starpower"] = (player_object.get("earned_starpower", 0) or 0) + reward
    monster_id = structure.pop("fuguing_monster", 0) or 0
    structure.pop("fuguing_mode", None)
    monster_update = {}
    if monster_id:
        monster_island, monster = find_monster_with_island(player_object, monster_id)
        island_type = island_type_of(monster_island or island)
        if monster is not None and island_type:
            current_mode = monster.get("paironormal_mode", monster.get("mode", 0)) or 0
            new_mode = 1 if current_mode == 0 else 0
            build_paironormal_modes(monster, island_type, new_mode)
            monster_update = monster
    structure["is_upgrading"] = 0
    structure["obj_data"] = 0
    structure["obj_end"] = 0
    save_player(username, root)
    result = {
        "success": True, "user_structure_id": SFSLong(structure_id),
        "properties": create_player_properties(player_object),
    }
    if monster_update:
        result["monster"] = monster_update
    add_actual_currencies(result, player_object)
    return result, {}
def buy_structure(username, params):
    pos_x = params.get("pos_x", params.get("col", 0)) or 0
    pos_y = params.get("pos_y", params.get("row", 0)) or 0
    scale = params.get("scale", 1.0) or 1.0
    structure_id = params.get("structure_id", params.get("structure", params.get("id", 0))) or 0
    flip = params.get("flip", params.get("flipped", 0)) or 0
    root, player_object = load_player(username)
    island_id = get_active_island_id(player_object)
    island = find_island(player_object, island_id)
    island_type = island.get("island_type", island.get("island", max(1, island_id - 1000))) if island else max(1, island_id - 1000)
    if island_type >= 1000 and island_id >= 1000:
        island_type = island_id - 1000
    new_structure_id = 10000 + random.randint(0, 989999)
    now = int(time.time() * 1000)
    new_structure = {
        "user_structure_id": new_structure_id, "user_island_id": island_id, "island": island_id,
        "island_type": island_type, "book_value": 100, "pos_x": pos_x, "pos_y": pos_y,
        "col": pos_x, "row": pos_y, "flip": flip, "flipped": flip, "muted": 0,
        "in_warehouse": 0, "is_upgrading": 0, "is_complete": 1,
        "structure": structure_id, "structure_id": structure_id, "scale": scale,
        "building_completed": now, "date_created": now, "last_collection": now,
        "obj_data": 0, "obj_end": 0,
    }
    definition = get_structure_definition(structure_id)
    if definition:
        level = definition.get("level", 1) or 1
        new_structure["level"] = level
        cost_diamonds = definition.get("cost_diamonds", 0) or 0
        cost_coins = definition.get("cost_coins", 0) or 0
        cost_relics = definition.get("cost_relics", 0) or 0
        cost_keys = definition.get("cost_keys", 0) or 0
        cost_starpower = definition.get("cost_starpower", 0) or 0
        if params.get("starpower_purchase") and cost_starpower > 0:
            player_object["starpower"] = max(0, (player_object.get("starpower", 0) or 0) - cost_starpower)
        elif cost_diamonds > 0:
            player_object["diamonds"] = max(0, (player_object.get("diamonds", 0) or 0) - cost_diamonds)
        elif cost_coins > 0:
            player_object["coins"] = max(0, (player_object.get("coins", 0) or 0) - cost_coins)
        elif cost_relics > 0:
            player_object["relics"] = max(0, (player_object.get("relics", 0) or 0) - cost_relics)
        elif cost_keys > 0:
            player_object["keys"] = max(0, (player_object.get("keys", 0) or 0) - cost_keys)
    if island is not None:
        island.setdefault("structures", []).append(new_structure)
        save_player(username, root)
    result = action_result(True, "user_structure_id", new_structure_id)
    result["user_structure"] = _structure_update(new_structure, "full")
    result["monster_happy_effects"] = []
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result
def _properties_with_inventory(player_object):
    properties = create_player_properties(player_object)
    properties.append({"items": player_object.get("inventory") or []})
    return properties
AWAKENER_STRUCTURES = {
    1: (801, 6, 31), 2: (814, 9, 30), 3: (829, 6, 31), 4: (847, 6, 31), 5: (855, 6, 31),
}
def backfill_awakener_structures(island):
    catalog_id = island.get("island", 0)
    island_type = island.get("island_type", island.get("type", catalog_id))
    if catalog_id != island_type:
        awakener_ids = {sid for sid, _, _ in AWAKENER_STRUCTURES.values()}
        structures = island.get("structures")
        if structures:
            island["structures"] = [s for s in structures if s is None or s.get("structure") not in awakener_ids]
        return
    entry = AWAKENER_STRUCTURES.get(island_type)
    if not entry:
        return
    structure_id, pos_x, pos_y = entry
    structures = island.setdefault("structures", [])
    for structure in structures:
        if structure is not None and structure.get("structure") == structure_id:
            structure.setdefault("ext", {})
            return
    now = int(time.time() * 1000)
    new_uid = 10000 + random.randint(0, 989999)
    structures.append({
        "user_structure_id": new_uid, "structure": structure_id, "structure_id": structure_id,
        "pos_x": pos_x, "pos_y": pos_y, "col": pos_x, "row": pos_y, "flip": 0, "flipped": 0,
        "muted": 0, "in_warehouse": 0, "is_upgrading": 0, "is_complete": 1, "scale": 1.0,
        "building_completed": now, "date_created": now, "last_collection": now,
        "obj_data": 0, "obj_end": 0, "ext": {"awakened_state": 0},
    })
def find_awakener_structure(island):
    island_type = island.get("island_type", island.get("type", island.get("island", 0)))
    entry = AWAKENER_STRUCTURES.get(island_type)
    if not entry:
        return None
    structure_id = entry[0]
    for structure in island.get("structures") or []:
        if structure is not None and structure.get("structure") == structure_id:
            return structure
    return None
def update_awakener(username, params):
    structure_id = params.get("user_structure_id", params.get("structure_id", 0)) or 0
    root, player_object = load_player(username)
    island, structure = find_island_by_structure(player_object, structure_id)
    if structure is None:
        return {"success": False}
    ext = structure.setdefault("ext", {})
    ext["awakened_state"] = 0 if ext.get("awakened_state", 1) else 1
    save_player(username, root)
    return {"success": True, "awakened_state": ext["awakened_state"]}
def _allowed_island_types(definition):
    if not definition:
        return None
    raw = definition.get("allowed_on_island")
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return set(parsed)
def buy_tile(username, params):
    pos_x = params.get("pos_x", params.get("col", 0)) or 0
    pos_y = params.get("pos_y", params.get("row", 0)) or 0
    flip = params.get("flip", params.get("flipped", 0)) or 0
    scale = params.get("scale", 1.0) or 1.0
    structure_id = params.get("structure_id", params.get("structure", params.get("id", 0))) or 0
    root, player_object = load_player(username)
    island_id = get_active_island_id(player_object)
    island = find_island(player_object, island_id)
    island_type = island.get("island_type", island.get("island", max(1, island_id - 1000))) if island else max(1, island_id - 1000)
    if island_type >= 1000 and island_id >= 1000:
        island_type = island_id - 1000
    definition = get_structure_definition(structure_id)
    allowed = _allowed_island_types(definition)
    if allowed and island_type not in allowed:
        for candidate in player_object.get("islands") or []:
            candidate_type = candidate.get("island_type", candidate.get("type", candidate.get("island"))) if candidate is not None else None
            if candidate_type in allowed:
                island = candidate
                island_id = candidate.get("user_island_id", island_id)
                island_type = candidate_type
                break
        else:
            return {"success": False, "tile": 0, "structure_id": structure_id,
                    "properties": _properties_with_inventory(player_object)}
    new_tile_id = 10000 + random.randint(0, 989999)
    now = int(time.time() * 1000)
    new_structure = {
        "user_structure_id": new_tile_id, "user_island_id": island_id, "island": island_id,
        "island_type": island_type, "book_value": 0, "pos_x": pos_x, "pos_y": pos_y,
        "col": pos_x, "row": pos_y, "flip": flip, "flipped": flip, "muted": 0,
        "in_warehouse": 0, "is_upgrading": 0, "is_complete": 1,
        "structure": structure_id, "structure_id": structure_id, "scale": scale,
        "building_completed": now, "date_created": now, "last_collection": now,
        "obj_data": 0, "obj_end": 0,
    }
    if definition:
        new_structure["level"] = definition.get("level", 1) or 1
        cost_coins = definition.get("cost_coins", 0) or 0
        cost_diamonds = definition.get("cost_diamonds", 0) or 0
        cost_relics = definition.get("cost_relics", 0) or 0
        cost_keys = definition.get("cost_keys", 0) or 0
        cost_starpower = definition.get("cost_starpower", 0) or 0
        cost_eth = definition.get("cost_eth_currency", 0) or 0
        if params.get("starpower_purchase") and cost_starpower > 0:
            player_object["starpower"] = max(0, (player_object.get("starpower", 0) or 0) - cost_starpower)
        elif cost_diamonds > 0:
            player_object["diamonds"] = max(0, (player_object.get("diamonds", 0) or 0) - cost_diamonds)
        elif cost_coins > 0:
            player_object["coins"] = max(0, (player_object.get("coins", 0) or 0) - cost_coins)
        elif cost_relics > 0:
            player_object["relics"] = max(0, (player_object.get("relics", 0) or 0) - cost_relics)
        elif cost_keys > 0:
            player_object["keys"] = max(0, (player_object.get("keys", 0) or 0) - cost_keys)
        elif cost_eth > 0:
            player_object["ethereal_currency"] = max(0, (player_object.get("ethereal_currency", 0) or 0) - cost_eth)
    if island is not None:
        island.setdefault("structures", []).append(new_structure)
        save_player(username, root)
    result = {
        "success": True, "tile": 1315679, "structure_id": structure_id,
        "properties": _properties_with_inventory(player_object),
    }
    return result
def save_paintstate(username, params):
    tiles = params.get("tiles") or {}
    root, player_object = load_player(username)
    island_id = get_active_island_id(player_object)
    island = find_island(player_object, island_id)
    if island is not None and isinstance(tiles, dict):
        paint_state = island.setdefault("paint_state", {})
        paint_state.update(tiles)
        save_player(username, root)
    result = {
        "tiles": tiles, "success": True,
        "properties": _properties_with_inventory(player_object),
    }
    return result
def _collected_structure_update(structure, player_object):
    properties = [{"last_collection": SFSLong(structure.get("last_collection", 0) or 0)}]
    properties.extend(create_player_properties(player_object))
    return {"user_structure_id": SFSLong(structure.get("user_structure_id", 0)), "properties": properties}
def store_structure(username, params):
    structure_id = params.get("user_structure_id", params.get("structure_id", 0)) or 0
    root, player_object = load_player(username)
    _, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    if structure is not None:
        structure["in_warehouse"] = 1
        structure["occupied"] = False
        save_player(username, root)
    return {"success": structure is not None, "user_structure_id": SFSLong(structure_id)}
def unstore_structure(username, params):
    structure_id = params.get("user_structure_id", params.get("structure_id", 0)) or 0
    root, player_object = load_player(username)
    _, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    if structure is not None:
        structure["in_warehouse"] = 0
        pos_x = params.get("pos_x", structure.get("pos_x", 0))
        pos_y = params.get("pos_y", structure.get("pos_y", 0))
        flip = params.get("flip", structure.get("flip", 0))
        structure["pos_x"] = pos_x
        structure["pos_y"] = pos_y
        structure["col"] = pos_x
        structure["row"] = pos_y
        structure["flip"] = flip
        structure["flipped"] = flip
        save_player(username, root)
    return {"success": structure is not None, "user_structure_id": SFSLong(structure_id)}
def collect_mine(username, params):
    structure_id = params.get("user_structure_id", params.get("structure_id", 0)) or 0
    root, player_object = load_player(username)
    _, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    if structure is None:
        return {"success": True}, None
    now = int(time.time() * 1000)
    definition = get_structure_definition(structure.get("structure", 0)) or {}
    extra = definition.get("extra") or {}
    payout = max(1, int(extra.get("diamonds", 1) or 1))
    cooldown_seconds = max(1, int(extra.get("time", 720) or 720))
    last_collection = structure.get("last_collection", 0) or 0
    if last_collection > 0 and now < last_collection + cooldown_seconds * 1000:
        return {"success": False, "message": "Mine is not ready yet"}, None
    diamonds = min(1999999999, (player_object.get("diamonds", 0) or 0) + payout)
    player_object["diamonds"] = diamonds
    player_object["diamonds_actual"] = diamonds
    structure["last_collection"] = now
    save_player(username, root)
    return {"success": True}, _collected_structure_update(structure, player_object)
def collect_structure(username, params):
    structure_id = params.get("user_structure_id", 0) or 0
    root, player_object = load_player(username)
    _, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    if structure is None:
        return {"success": False, "message": "Structure not found"}, None
    payout = structure.get("obj_data", 0) or 0
    if payout > 0:
        if structure.get("structure", 0) == 801:
            player_object["diamonds"] = (player_object.get("diamonds", 0) or 0) + payout
        else:
            player_object["coins"] = min(1999999999, (player_object.get("coins", 0) or 0) + payout)
    now = int(time.time() * 1000)
    structure["obj_data"] = 0
    structure["last_collection"] = now
    structure["last_collected"] = now
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["collected_coins"] = payout
    result["coins"] = payout
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, _collected_structure_update(structure, player_object)
def start_baking(username, params):
    structure_id = params.get("user_structure_id", 0)
    food_id = params.get("food_id", params.get("food_option_id", 0))
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    food = get_bakery_food(food_id)
    if food is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    now = int(time.time() * 1000)
    finish = now + int(food.get("time", 0) or 0) * 1000
    cost = int(food.get("cost", 0) or 0)
    player_object["coins"] = max(0, (player_object.get("coins", 0) or 0) - cost)
    structure["obj_data"] = food_id
    structure["obj_end"] = finish
    structure["num_bakes"] = structure.get("num_bakes", 0) + 1
    structure["building_completed"] = finish
    structure["finishing_time"] = finish
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["food_option_id"] = food_id
    result["user_baking"] = {
        "user_baking_id": SFSLong(structure_id), "user_structure": SFSLong(structure_id),
        "island": SFSLong(island.get("user_island_id", 0) if island else 0),
        "food_option_id": food_id, "food_count": food.get("quantity", 0),
        "started_at": SFSLong(now), "finished_at": SFSLong(finish),
    }
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result
def speed_up_baking(username, params):
    structure_id = params.get("user_structure_id", params.get("user_baking_id", 0))
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_baking_id", structure_id, with_properties=True)
    finished_at = int(time.time() * 1000)
    structure["obj_end"] = finished_at
    structure["building_completed"] = finished_at
    structure["finishing_time"] = finished_at
    save_player(username, root)
    result = action_result(True, "user_baking_id", structure_id)
    result["user_structure_id"] = SFSLong(structure_id)
    result["finished_at"] = SFSLong(finished_at)
    result["finishing_time"] = SFSLong(finished_at)
    result["obj_end"] = SFSLong(finished_at)
    result["building_completed"] = SFSLong(finished_at)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result
def start_dish_harmonizing(username, params):
    structure_id = params.get("user_structure_id", 0)
    genes = params.get("genes") or []
    num_genes = len(genes) if isinstance(genes, list) and genes else int(params.get("num_genes", 2) or 2)
    num_genes = min(3, max(2, num_genes))
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    island_id = island.get("island", 0) if island is not None else 0
    definition = get_ethereal_islet_definition(island_id) or {}
    cost = int(definition.get(f"target_cost_{num_genes}_gene", 0) or 0)
    time_per_gene = int(definition.get("dish_harmonizing_time_per_gene", 0) or 0)
    base_time = int(definition.get("dish_harmonizing_base_time", 0) or 0)
    now = int(time.time() * 1000)
    finish = now + (base_time + time_per_gene * num_genes) * 1000
    player_object["diamonds"] = max(0, (player_object.get("diamonds", 0) or 0) - cost)
    structure["obj_data"] = num_genes
    structure["obj_end"] = finish
    structure["is_upgrading"] = 1
    structure["building_completed"] = finish
    structure["finishing_time"] = finish
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["started_at"] = SFSLong(now)
    result["finished_at"] = SFSLong(finish)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, _structure_update(structure, "full")
def speed_up_dish_harmonizing(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    finished_at = int(time.time() * 1000)
    structure["obj_end"] = finished_at
    structure["building_completed"] = finished_at
    structure["finishing_time"] = finished_at
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    result["finished_at"] = SFSLong(finished_at)
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, _structure_update(structure, "full")
def finish_dish_harmonizing(username, params):
    structure_id = params.get("user_structure_id", 0)
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_structure_id", structure_id, with_properties=True)
    island_id = island.get("island", 0) if island is not None else 0
    definition = get_ethereal_islet_definition(island_id) or {}
    monster_id = int(definition.get("primordial", 0) or 0)
    structure["obj_data"] = 0
    structure["obj_end"] = 0
    structure["is_upgrading"] = 0
    structure["building_completed"] = 0
    structure["finishing_time"] = 0
    user_egg = None
    if monster_id and island is not None:
        next_egg_id = int(player_object.get("last_user_egg_id", 0) or 0) + 1
        player_object["last_user_egg_id"] = next_egg_id
        island_uid = island.get("user_island_id", 0)
        nursery_sid = structure.get("user_structure_id", 0)
        user_egg = {
            "monster": monster_id, "monster_id": monster_id,
            "laid_on": SFSLong(0), "hatches_on": SFSLong(0),
            "structure": SFSLong(nursery_sid), "island": SFSLong(island_uid),
            "user_egg_id": SFSLong(next_egg_id), "costume": {"eq": 0, "p": []},
        }
        eggs = island.setdefault("eggs", [])
        for i in range(len(eggs) - 1, -1, -1):
            if eggs[i] is not None and eggs[i].get("structure") == nursery_sid:
                del eggs[i]
        eggs.append(user_egg)
    save_player(username, root)
    result = action_result(True, "user_structure_id", structure_id)
    if user_egg is not None:
        result["user_egg"] = user_egg
    result["properties"] = create_player_properties(player_object)
    add_actual_currencies(result, player_object)
    return result, _structure_update(structure, "full")
def finish_baking(username, params):
    structure_id = params.get("user_structure_id", params.get("user_baking_id", 0))
    root, player_object = load_player(username)
    island, structure = _locate(player_object, structure_id)
    if structure is None:
        return action_result(False, "user_baking_id", structure_id, with_properties=True)
    food_id = structure.get("obj_data", 0)
    food = get_bakery_food(food_id)
    quantity = max(0, (food.get("quantity", 0) if food else 0) or 0)
    player_object["food"] = min(1999999999, (player_object.get("food", 0) or 0) + quantity)
    structure["obj_data"] = 0
    structure["obj_end"] = 0
    structure["building_completed"] = 0
    structure["finishing_time"] = 0
    import msm_rewardtracks
    properties = msm_rewardtracks.properties_with_encore(player_object, 4, 2)
    save_player(username, root)
    result = action_result(True, "user_baking_id", structure_id)
    result["properties"] = properties
    return result
