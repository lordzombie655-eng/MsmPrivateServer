from msm_protocol import SFSFloat, SFSLong
from msm_store import load_user_data, save_user_data

_WIRE_LONG_KEYS = {
    "user_structure_id", "user_island_id", "user_monster_id", "user_egg_id", "user_breeding_id",
    "user_baking_id", "user_box_monster_id", "underlingUid", "underling_id", "user_underling_id",
    "selectedUnderlingUid", "parent_monster", "parent_user_monster_id", "parent_island",
    "parent_user_island_id", "active_island", "last_user_monster_id", "last_user_egg_id",
    "last_user_island_id", "last_collection", "last_collected", "last_fed", "date_created",
    "building_completed", "obj_end", "finishing_time", "complete_on", "seconds_remaining",
    "time_remaining", "started_at", "finished_at", "user", "chief", "last_login", "hatches_on", "laid_on",
    "bakery", "bbb_id", "c", "clubbox_tokens", "clubbox_tokens_actual", "coins_actual",
    "currencyScratchTime", "diamonds_actual", "egg_wildcards", "egg_wildcards_actual", "end_date",
    "entity_id", "ethereal_currency_actual", "event_start_time", "flipGameTime", "food_actual",
    "friend_gift", "keys", "keys_actual", "last_collect_all", "last_fb_post_reward", "last_feeding",
    "last_speed_up", "last_speed_up_breeding", "last_speed_up_nursery", "monsterScratchTime",
    "nextDailyLogin", "next_collect", "next_relic_reset", "prev_rank", "recipient_bbbid", "relics",
    "relics_actual", "s", "schedule_started_on", "seed", "speed_up_credit", "starpower",
    "starpower_actual", "start_date", "started_on", "time_of_next_gift", "total_starpower_collected",
    "user_achievement_id", "user_monster_1", "user_monster_2", "user_structure", "user_torch_id",
    "user_track_id",
}
_WIRE_FLOAT_KEYS = {
    "scale", "volume", "warp_speed", "coin_production_mod", "nursery_speed_mod", "total_points",
}


def coerce_wire_types(value):
    if isinstance(value, dict):
        for key, sub in value.items():
            if isinstance(sub, dict) or isinstance(sub, list):
                coerce_wire_types(sub)
            elif key in _WIRE_LONG_KEYS and isinstance(sub, int) and not isinstance(sub, bool):
                value[key] = SFSLong(sub)
            elif key in _WIRE_FLOAT_KEYS and isinstance(sub, (int, float)) and not isinstance(sub, bool):
                value[key] = SFSFloat(sub)
    elif isinstance(value, list):
        for item in value:
            coerce_wire_types(item)
    return value

PROPERTY_ALIASES = [
    ("coins", "coins_actual"), ("diamonds", "diamonds_actual"), ("food", "food_actual"),
    ("ethereal_currency", "ethereal_currency_actual"), ("keys", "keys_actual"),
    ("relics", "relics_actual"), ("egg_wildcards", "egg_wildcards_actual"),
    ("clubbox_tokens", "clubbox_tokens_actual"), ("starpower", "starpower_actual"),
]

def _clamp_i32(value):
    return int(value)


def load_player(username):
    root = load_user_data(username)
    return root, root.get("player_object") or {}


def save_player(username, root):
    save_user_data(username, root)


def get_active_island_id(player_object):
    return player_object.get("active_island", 0)


def find_island(player_object, island_id):
    for island in player_object.get("islands") or []:
        if island is not None and island.get("user_island_id") == island_id:
            return island
    return None


def island_type_of(island):
    if not island:
        return 0
    return island.get("island_type", island.get("type", island.get("island", 0))) or 0


def find_structure(island, structure_id):
    if island is None:
        return None
    for structure in island.get("structures") or []:
        if structure is not None and structure.get("user_structure_id") == structure_id:
            return structure
    return None


def find_monster(island, monster_id):
    if island is None:
        return None
    for monster in island.get("monsters") or []:
        if monster is not None and monster.get("user_monster_id") == monster_id:
            return monster
    return None


def find_island_by_structure(player_object, structure_id):
    for island in player_object.get("islands") or []:
        structure = find_structure(island, structure_id)
        if structure is not None:
            return island, structure
    return None, None


def find_monster_with_island(player_object, monster_id, preferred_island=None):
    if preferred_island is not None:
        monster = find_monster(preferred_island, monster_id)
        if monster is not None:
            return preferred_island, monster
    for island in player_object.get("islands") or []:
        monster = find_monster(island, monster_id)
        if monster is not None:
            return island, monster
    return None, None


_DAILY_RESET_HOUR_UTC = 15


def next_daily_reset_timestamp(now_ms=None):
    import time as _time
    now_ms = now_ms if now_ms is not None else int(_time.time() * 1000)
    day_ms = 86400000
    today_start = (now_ms // day_ms) * day_ms
    reset = today_start + _DAILY_RESET_HOUR_UTC * 3600000
    if reset <= now_ms:
        reset += day_ms
    return reset


def create_player_properties(player_object):
    properties = []
    for source_key, actual_key in PROPERTY_ALIASES:
        properties.append({actual_key: _clamp_i32(player_object.get(source_key, 0) or 0)})
    properties.append({"xp": _clamp_i32(player_object.get("xp", 0) or 0)})
    properties.append({"level": _clamp_i32(player_object.get("level", 0) or 0)})
    properties.append({"daily_bonus_type": player_object.get("daily_bonus_type") or "none"})
    properties.append({"daily_bonus_amount": _clamp_i32(player_object.get("daily_bonus_amount", 0) or 0)})
    properties.append({"has_free_ad_scratch": bool(player_object.get("has_free_ad_scratch", True))})
    properties.append({"daily_relic_purchase_count": _clamp_i32(player_object.get("daily_relic_purchase_count", 0) or 0)})
    properties.append({"relic_diamond_cost": _clamp_i32(player_object.get("relic_diamond_cost", 1) or 1)})
    properties.append({"next_relic_reset": SFSLong(next_daily_reset_timestamp())})
    properties.append({"premium": _clamp_i32(player_object.get("premium", 0) or 0)})
    properties.append({"earned_starpower": _clamp_i32(player_object.get("earned_starpower", 0) or 0)})
    properties.append({"speed_up_credit": _clamp_i32(player_object.get("speed_up_credit", 0) or 0)})
    properties.append({"battle_xp": _clamp_i32(player_object.get("battle_xp", 0) or 0)})
    properties.append({"battle_level": _clamp_i32(player_object.get("battle_level", 0) or 0)})
    properties.append({"medals": _clamp_i32(player_object.get("medals", 0) or 0)})
    return properties


def add_actual_currencies(result, player_object):
    for source_key, actual_key in PROPERTY_ALIASES:
        result[actual_key] = _clamp_i32(player_object.get(source_key, 0) or 0)


def action_result(success, id_key, id_value, with_properties=False):
    result = {"success": bool(success), id_key: SFSLong(id_value)}
    if with_properties:
        result["properties"] = []
    return result
