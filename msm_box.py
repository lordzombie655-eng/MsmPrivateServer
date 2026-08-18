from msm_gamedata import get_monster_definition
from msm_playerdata import (
    SFSLong, add_actual_currencies, create_player_properties, find_island,
    find_island_by_structure, find_monster_with_island, get_active_island_id, island_type_of, load_player, save_player,
)
from msm_protocol import SFSFloat

SPECIAL_BOX_PLACEMENT_ISLANDS = (10, 12, 22)


def is_box_monster_entity(definition):
    return bool(definition) and (definition.get("entity_type") or "").lower() == "box_monster"


def repair_broken_box_eggs(island):
    eggs = island.get("eggs")
    if not eggs:
        return
    def _is_broken(egg):
        if not egg:
            return False
        structure = egg.get("structure", 0) or 0
        monster = egg.get("monster")
        return structure == 0 and monster is not None and egg.get("user_egg_id") == monster
    island["eggs"] = [egg for egg in eggs if not _is_broken(egg)]


def is_special_box_placement_island(island_type):
    return island_type in SPECIAL_BOX_PLACEMENT_ISLANDS


def is_direct_box_placement_id(requested_id, island_type):
    if requested_id <= 0 or not is_special_box_placement_island(island_type):
        return False
    return is_box_monster_entity(get_monster_definition(requested_id))


_DIRECT_PLACEMENT_CLASSES = ("CLASS_DIPSTER",)
def requires_direct_placement_on_purchase(definition, island_type):
    if island_type in (10, 11, 12, 22):
        return True
    return bool(definition and definition.get("class") in _DIRECT_PLACEMENT_CLASSES)


def requires_direct_placement(definition, island_type):
    if requires_direct_placement_on_purchase(definition, island_type):
        return True
    return bool(definition) and is_box_monster_entity(definition)


def is_amber_no_vessel_island(island_type):
    return island_type == 22


def box_requirements(definition):
    if not definition:
        return []
    raw = definition.get("box_monster_requirements")
    if isinstance(raw, list):
        return [int(v) for v in raw if isinstance(v, (int, float))]
    if isinstance(raw, str):
        return [int(tok) for tok in raw.strip("[] ").split(",") if tok.strip().lstrip("-").isdigit()]
    return []


def _ints_to_json_array(values):
    return "[" + ",".join(str(v) for v in values) + "]"


def boxed_eggs(monster):
    raw = monster.get("boxed_eggs")
    if isinstance(raw, list):
        return [int(v) for v in raw if isinstance(v, (int, float))]
    if isinstance(raw, str):
        return [int(tok) for tok in raw.strip("[] ").split(",") if tok.strip().lstrip("-").isdigit()]
    return []


def _count(values, wanted):
    return sum(1 for v in values if v == wanted)


def append_boxed_egg(monster, boxed_monster_id):
    if not boxed_monster_id:
        return
    values = boxed_eggs(monster)
    requirements = box_requirements(get_monster_definition(monster.get("monster", 0)))
    required_count = _count(requirements, boxed_monster_id)
    current_count = _count(values, boxed_monster_id)
    if required_count == 0 or current_count < required_count:
        values.append(boxed_monster_id)
    monster["boxed_eggs"] = _ints_to_json_array(values)


def is_awakened_box_monster(monster):
    return bool(monster.get("awakened"))


def ensure_box_progress_fields(monster, definition):
    requirements = box_requirements(definition)
    eggs = boxed_eggs(monster)
    required = len(requirements) or monster.get("minNumEggsRequiredInUnderling", 0) or 0
    current = max(len(eggs), monster.get("numEggsInInventory", 0) or 0)
    monster["box_requirements"] = _ints_to_json_array(requirements)
    monster["boxed_eggs"] = _ints_to_json_array(eggs)
    monster["minNumEggsRequiredInUnderling"] = required
    monster["numEggsInInventory"] = current


def apply_inactive_box_state(monster, definition):
    monster["happiness"] = 0
    monster["awakened"] = False
    monster["inactive_box_monster"] = True
    monster["is_inactive_box_monster"] = True
    monster["box_monster"] = True
    monster["is_box_monster"] = True
    monster.setdefault("book_value", (definition or {}).get("cost_sale") or 75000000)
    ensure_box_progress_fields(monster, definition)
    if not boxed_eggs(monster):
        monster.pop("egg_timer_start", None)


def start_amber_vessel_timer_if_needed(monster, island_type):
    if island_type != 22 or not boxed_eggs(monster) or (monster.get("egg_timer_start", 0) or 0) > 0:
        return
    import time
    monster["egg_timer_start"] = int(time.time() * 1000)


def apply_awakened_box_state(monster, definition, island_type):
    monster["awakened"] = True
    monster["inactive_box_monster"] = False
    monster["is_inactive_box_monster"] = False
    monster["box_monster"] = False
    monster["is_box_monster"] = False
    monster["box_requirements"] = "[]"
    monster["boxed_eggs"] = ""
    monster["numEggsInInventory"] = 0
    monster["minNumEggsRequiredInUnderling"] = 0
    monster["numSoulLinks"] = 0
    monster["num_soul_links"] = 0
    if (monster.get("level", 0) or 0) <= 0:
        monster["level"] = 1
    monster["happiness"] = max(0, monster.get("happiness", 0) or 0)
    if not monster.get("book_value"):
        monster["book_value"] = (definition or {}).get("cost_sale", 0) or 75000000


def build_placeholder_box_monster(monster_id, definition, island_uid, user_monster_id, pos_x, pos_y, flip, now, island_type=0):
    monster = {
        "user_monster_id": SFSLong(user_monster_id), "user_island_id": SFSLong(island_uid),
        "island": SFSLong(island_uid), "monster": monster_id, "monster_id": monster_id,
        "pos_x": pos_x, "pos_y": pos_y, "flip": flip, "flipped": flip, "muted": 0,
        "level": 1, "happiness": 0, "times_fed": 0,
        "name": definition.get("common_name") or definition.get("name") or "",
        "in_hotel": 0, "volume": SFSFloat(1.0), "last_collection": SFSLong(now), "last_fed": SFSLong(now),
        "last_feeding": SFSLong(now), "date_created": SFSLong(now),
        "collected_coins": 0, "costume": {"eq": 0, "p": []}, "awakened": False,
        "is_modal": False, "isModal": False,
    }
    if is_amber_no_vessel_island(island_type):
        apply_awakened_box_state(monster, definition, island_type)
    else:
        apply_inactive_box_state(monster, definition)
    return monster


def _find_box_island(player_object, params):
    island_id = params.get("user_island_id") or params.get("island_id") or params.get("dest_island_id") or 0
    if island_id:
        island = find_island(player_object, island_id if island_id >= 1000 else island_id + 1000)
        if island is not None:
            return island
    return find_island(player_object, get_active_island_id(player_object))


def _box_monster_id(params):
    for key in ("box_monster_id", "boxMonsterId", "user_box_monster_id", "box_user_monster_id",
                "underling_id", "user_underling_id"):
        value = params.get(key)
        if value:
            return value
    return 0


def _box_progress_update(monster):
    return {
        "user_monster_id": SFSLong(monster.get("user_monster_id", 0)),
        "egg_timer_start": SFSLong(monster.get("egg_timer_start", -1) if monster.get("egg_timer_start") is not None else -1),
        "boxed_eggs": _ints_to_json_array(boxed_eggs(monster)),
    }


def _box_activate_update(monster):
    return {
        "user_monster_id": SFSLong(monster.get("user_monster_id", 0)),
        "egg_timer_start": SFSLong(-1),
        "boxed_eggs": "",
        "book_value": monster.get("book_value", 0) or 0, "evolve_unlocked": monster.get("evolve_unlocked", 0) or 0,
        "last_collection": SFSLong(monster.get("last_collection", 0) or 0),
    }


def box_add_egg(username, params):
    user_egg_id = params.get("user_egg_id", 0) or 0
    user_monster_id = params.get("user_monster_id", 0) or 0
    root, player_object = load_player(username)
    result = {"success": False, "user_egg_id": SFSLong(user_egg_id), "user_monster_id": SFSLong(user_monster_id)}
    if not user_egg_id or not user_monster_id:
        result["error"] = "zap_target_or_egg_not_found"
        return result

    target_island, target_box = find_monster_with_island(player_object, user_monster_id)
    target_definition = get_monster_definition(target_box.get("monster", 0)) if target_box is not None else None
    if target_island is None or target_box is None or not is_box_monster_entity(target_definition) or is_awakened_box_monster(target_box):
        result["error"] = "zap_target_or_egg_not_found"
        return result

    source_island = None
    egg = None
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        for candidate in island.get("eggs") or []:
            if candidate is not None and candidate.get("user_egg_id") == user_egg_id:
                source_island = island
                egg = candidate
                break
        if egg is not None:
            break
    if egg is None:
        result["error"] = "zap_target_or_egg_not_found"
        return result

    egg_type = egg.get("monster", 0)
    if not egg_type:
        result["error"] = "zap_monster_type_not_found"
        return result

    island_type = island_type_of(target_island)
    append_boxed_egg(target_box, egg_type)
    start_amber_vessel_timer_if_needed(target_box, island_type)
    apply_inactive_box_state(target_box, target_definition)

    eggs = source_island.get("eggs") or []
    for i in range(len(eggs) - 1, -1, -1):
        if eggs[i] is egg:
            del eggs[i]
            break
    nursery_id = egg.get("structure", 0)
    if nursery_id:
        for structure in source_island.get("structures") or []:
            if structure is not None and structure.get("user_structure_id") == nursery_id:
                structure["occupied"] = False
                structure["has_egg"] = False
                structure["obj_data"] = 0
                structure["obj_end"] = 0
                break
    save_player(username, root)

    return {
        "success": True, "underling": True,
        "dest_island_id": SFSLong(target_island.get("user_island_id", 0)),
        "egg_type": egg_type, "isWublin": island_type == 10,
        "user_box_monster_id": SFSLong(user_monster_id), "gi_monster_id": SFSLong(user_monster_id),
        "user_egg_id": SFSLong(user_egg_id), "user_monster_id": SFSLong(user_monster_id),
    }


def box_monster_command(username, params):
    if params.get("user_egg_id") and params.get("user_monster_id"):
        return box_add_egg(username, params)
    return box_add_monster(username, params)


def box_add_monster(username, params):
    user_monster_id = params.get("user_monster_id", 0) or 0
    requested_box_id = _box_monster_id(params)
    root, player_object = load_player(username)
    island = _find_box_island(player_object, params)
    result = {"success": False, "properties": []}
    add_actual_currencies(result, player_object)
    if island is None or not user_monster_id:
        return result
    monsters = island.get("monsters") or []

    target_box = None
    for m in monsters:
        if m is None:
            continue
        definition = get_monster_definition(m.get("monster", 0))
        if not is_box_monster_entity(definition) or is_awakened_box_monster(m):
            continue
        if not requested_box_id or m.get("user_monster_id") == requested_box_id:
            target_box = m
            requested_box_id = m.get("user_monster_id")
            break
    if target_box is None or requested_box_id == user_monster_id:
        result["error"] = "missing_inactive_box_monster"
        return result

    boxed_monster_type = 0
    found_index = None
    for i in range(len(monsters) - 1, -1, -1):
        m = monsters[i]
        if m is not None and m.get("user_monster_id") == user_monster_id:
            boxed_monster_type = m.get("monster", 0)
            if is_box_monster_entity(get_monster_definition(boxed_monster_type)):
                result["error"] = "cannot_box_box_monster"
                return result
            found_index = i
            break
    if found_index is None:
        result["error"] = "boxed_monster_not_found"
        return result
    del monsters[found_index]

    island_type = island_type_of(island)
    box_definition = get_monster_definition(target_box.get("monster", 0))
    append_boxed_egg(target_box, boxed_monster_type)
    start_amber_vessel_timer_if_needed(target_box, island_type)
    target_box["numEggsInInventory"] = max(len(boxed_eggs(target_box)), target_box.get("numEggsInInventory", 0) or 0)
    target_box["awakened"] = False
    apply_inactive_box_state(target_box, box_definition)
    save_player(username, root)

    return {
        "success": True, "user_monster_id": SFSLong(user_monster_id),
        "user_box_monster_id": SFSLong(requested_box_id), "gi_monster_id": SFSLong(user_monster_id),
        "monster_type": boxed_monster_type, "dest_island_id": SFSLong(island.get("user_island_id", 0)),
        "isWublin": island_type == 22,
    }


def box_purchase_fill(username, params):
    user_monster_id = _box_monster_id(params) or params.get("user_monster_id", 0) or 0
    root, player_object = load_player(username)
    island = _find_box_island(player_object, params)
    result = {"success": False, "cmd": "gs_box_purchase_fill", "properties": []}
    add_actual_currencies(result, player_object)
    if island is None or not user_monster_id:
        result["error"] = "missing_box_monster_id"
        return result, {}

    target_island, box_monster = find_monster_with_island(player_object, user_monster_id, island)
    if box_monster is None:
        result["error"] = "box_monster_not_found"
        return result, {}
    island = target_island or island
    definition = get_monster_definition(box_monster.get("monster", 0))
    if not is_box_monster_entity(definition):
        result["error"] = "not_box_monster"
        return result, {}

    requirements = box_requirements(definition)
    boxed = boxed_eggs(box_monster)
    before = len(boxed)
    for i, wanted in enumerate(requirements):
        required_through_slot = _count(requirements[:i + 1], wanted)
        if _count(boxed, wanted) < required_through_slot:
            boxed.append(wanted)
    filled = max(0, len(boxed) - before)

    pref_wildcards = params.get("pref_wildcards", True)
    wildcards_spent = 0
    diamonds_spent = 0
    if filled > 0:
        egg_wildcards = max(player_object.get("egg_wildcards", 0) or 0, player_object.get("playerEggWildcards", 0) or 0)
        remaining = filled
        if pref_wildcards and egg_wildcards > 0:
            wildcards_spent = min(remaining, egg_wildcards)
            new_wildcards = max(0, egg_wildcards - wildcards_spent)
            player_object["egg_wildcards"] = new_wildcards
            player_object["egg_wildcards_actual"] = new_wildcards
            player_object["playerEggWildcards"] = new_wildcards
            remaining -= wildcards_spent
        if remaining > 0:
            diamonds_spent = remaining
            diamonds = player_object.get("diamonds", 0) or 0
            new_diamonds = max(0, diamonds - diamonds_spent)
            player_object["diamonds"] = new_diamonds
            player_object["diamonds_actual"] = new_diamonds

    box_monster["boxed_eggs"] = _ints_to_json_array(boxed)
    box_monster["numEggsInInventory"] = len(boxed)
    box_monster["minNumEggsRequiredInUnderling"] = len(requirements)
    box_monster["awakened"] = False
    island_type = island_type_of(island)
    start_amber_vessel_timer_if_needed(box_monster, island_type)
    apply_inactive_box_state(box_monster, definition)
    save_player(username, root)

    result = {
        "success": True, "user_monster_id": SFSLong(user_monster_id),
        "properties": create_player_properties(player_object),
    }
    return result, _box_progress_update(box_monster)


def wake_wubbox(username, params):
    user_monster_id = params.get("user_monster_id", 0) or 0
    validate_only = bool(params.get("validate_only"))
    root, player_object = load_player(username)
    island = _find_box_island(player_object, params)
    result = {"success": False, "properties": []}
    add_actual_currencies(result, player_object)
    if island is None:
        return result, {}

    monster = None
    if user_monster_id:
        _, monster = find_monster_with_island(player_object, user_monster_id, island)
    if monster is None:
        for m in island.get("monsters") or []:
            if m is not None and not is_awakened_box_monster(m) and is_box_monster_entity(get_monster_definition(m.get("monster", 0))):
                monster = m
                user_monster_id = m.get("user_monster_id", 0)
                break
    if monster is None:
        return result, {}

    definition = get_monster_definition(monster.get("monster", 0))
    if validate_only:
        return {"success": True, "user_monster_id": SFSLong(user_monster_id)}, {}

    island_type = island_type_of(island)
    apply_awakened_box_state(monster, definition, island_type)
    save_player(username, root)

    client_result = {"success": True, "user_monster_id": SFSLong(user_monster_id)}
    return client_result, _box_activate_update(monster)


def box_activate_monster(username, params):
    return wake_wubbox(username, params)


def purchase_evolve_unlock(username, params):
    user_monster_id = params.get("user_monster_id", 0) or 0
    root, player_object = load_player(username)
    result = {"success": False, "user_monster_id": SFSLong(user_monster_id), "properties": create_player_properties(player_object)}
    if not user_monster_id:
        result["error"] = "evolve_monster_not_found"
        return result
    _, monster = find_monster_with_island(player_object, user_monster_id)
    if monster is None:
        result["error"] = "evolve_monster_not_found"
        return result
    definition = get_monster_definition(monster.get("monster", 0))
    evolve_into = (definition or {}).get("evolve_into", 0) or 0
    if evolve_into <= 0:
        result["error"] = "evolve_not_available"
        return result
    monster["evolve_unlocked"] = 1
    monster["evolve_enabled"] = 1
    monster["evolve_into"] = evolve_into
    monster["has_evolve_reqs"] = (definition or {}).get("evolve_requirements") or "[]"
    monster["has_evolve_flexeggs"] = (definition or {}).get("evolve_req_flexeggs") or "[]"
    save_player(username, root)
    return {"success": True, "user_monster_id": SFSLong(user_monster_id), "properties": create_player_properties(player_object)}
