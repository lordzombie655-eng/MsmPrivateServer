import json
import random
from msm_store import load_db_json
PAIRONORMAL_ISLAND_TYPE = 31
_STRUCTURE_DB_NAMES = ["db_structures", "db_structure", "db_structure_2", "db_structure_3", "db_structure_4",
                       "db_structure_5", "db_structure_6", "db_structure_7", "db_structure_8", "db_structure_9"]
_structure_defs_cache = None
_monster_defs_cache = None
def _structure_array(data):
    if not data:
        return None
    return data.get("structures_data") or data.get("structure_data")
def _build_structure_defs():
    defs = {}
    for name in _STRUCTURE_DB_NAMES:
        arr = _structure_array(load_db_json(name))
        if not arr:
            continue
        for entry in arr:
            sid = entry.get("structure_id")
            if sid is not None and sid not in defs:
                defs[sid] = entry
    return defs
def get_structure_definition(structure_id):
    global _structure_defs_cache
    if _structure_defs_cache is None:
        _structure_defs_cache = _build_structure_defs()
    return _structure_defs_cache.get(structure_id)
def _build_monster_defs():
    defs = {}
    for data in _load_db_chunk_chain("db_monster"):
        for entry in data.get("monsters_data") or []:
            mid = entry.get("monster_id")
            if mid is not None:
                defs[mid] = entry
    return defs


def _load_db_chunk_chain(name):
    data = load_db_json(name)
    if data is not None:
        yield data
    for i in range(2, 10):
        data = load_db_json(f"{name}_{i}")
        if data is None:
            break
        yield data
def get_monster_definition(monster_id):
    global _monster_defs_cache
    if _monster_defs_cache is None:
        _monster_defs_cache = _build_monster_defs()
    return _monster_defs_cache.get(monster_id)
def _all_monster_defs():
    global _monster_defs_cache
    if _monster_defs_cache is None:
        _monster_defs_cache = _build_monster_defs()
    return _monster_defs_cache
def all_monster_ids():
    return list(_all_monster_defs().keys())
def is_nursery_structure(structure_id):
    definition = get_structure_definition(structure_id)
    return bool(definition) and definition.get("structure_type") == "nursery"
def is_egg_holder_structure(structure_id):
    definition = get_structure_definition(structure_id)
    return bool(definition) and definition.get("structure_type") in ("nursery", "dish_harmonizer", "synthesizer")
_island_book_cache = None
def _build_island_book():
    book = {}
    data = load_db_json("db_island_v2") or {}
    for entry in data.get("islands_data") or []:
        island_type = entry.get("island_type")
        if island_type is None:
            continue
        ids = book.setdefault(island_type, set())
        for m in entry.get("monsters") or []:
            monster_id = m.get("monster")
            if monster_id is not None:
                ids.add(monster_id)
    return book
def _island_book():
    global _island_book_cache
    if _island_book_cache is None:
        _island_book_cache = _build_island_book()
    return _island_book_cache
def monster_allowed_on_island(definition, island_type_id):
    if not definition or not island_type_id:
        return False
    monster_id = definition.get("monster_id")
    if monster_id is None:
        return False
    return monster_id in _island_book().get(island_type_id, ())
def monster_ids_allowed_on_island(island_type_id):
    return sorted(_island_book().get(island_type_id, ()))
def resolve_monster_for_island(monster_id, island_type_id):
    definition = get_monster_definition(monster_id)
    if not definition or not island_type_id:
        return monster_id
    if monster_allowed_on_island(definition, island_type_id):
        return monster_id
    name = definition.get("name")
    if not name:
        return monster_id
    for candidate_id, candidate in _all_monster_defs().items():
        if candidate.get("name") == name and monster_allowed_on_island(candidate, island_type_id):
            return candidate_id
    return monster_id
def is_paironormal_island(island_type_id):
    return island_type_id == PAIRONORMAL_ISLAND_TYPE
def is_paironormal_multimodal(definition):
    if not definition:
        return False
    name = (definition.get("name") or "")
    common_name = (definition.get("common_name") or "")
    class_name = (definition.get("class") or "")
    combined = f"{name} {common_name} {class_name}".lower()
    if "titansoul" in combined:
        return False
    graphic = definition.get("graphic") or {}
    if (graphic.get("file") or "").lower() == "placeholder_ghost.bin":
        return True
    return "multimodal" in common_name.lower()
def resolve_paironormal_stored_monster_id(monster_id, island_type_id):
    if not is_paironormal_island(island_type_id) or not monster_id or monster_id <= 0:
        return monster_id
    definition = get_monster_definition(monster_id)
    if not definition:
        return monster_id
    if is_paironormal_multimodal(definition):
        return monster_id
    base_name = definition.get("name") or ""
    if not base_name:
        return monster_id
    for candidate_id, candidate in _all_monster_defs().items():
        if candidate.get("name") == base_name and is_paironormal_multimodal(candidate):
            return candidate_id
    return monster_id
def find_paironormal_form_id(monster_id, island_type_id, want_major):
    if not is_paironormal_island(island_type_id) or not monster_id or monster_id <= 0:
        return monster_id
    stored_id = resolve_paironormal_stored_monster_id(monster_id, island_type_id)
    definition = get_monster_definition(stored_id)
    if not definition:
        return stored_id
    base_name = definition.get("name") or ""
    if not base_name:
        return stored_id
    marker = "(major)" if want_major else "(minor)"
    for candidate_id, candidate in _all_monster_defs().items():
        if candidate.get("name") != base_name:
            continue
        if marker in (candidate.get("common_name") or "").lower():
            return candidate_id
    return stored_id
def resolve_paironormal_renderable_monster_id(monster_id, island_type_id, island_mode):
    if not is_paironormal_island(island_type_id) or not monster_id or monster_id <= 0:
        return monster_id
    stored_id = resolve_paironormal_stored_monster_id(monster_id, island_type_id)
    definition = get_monster_definition(stored_id)
    if not definition:
        return stored_id
    base_name = definition.get("name") or ""
    if not base_name:
        return stored_id
    want_major = island_mode == 0
    if not is_paironormal_multimodal(definition):
        current = (definition.get("common_name") or "").lower()
        if want_major and "(major)" in current:
            return stored_id
        if not want_major and "(minor)" in current:
            return stored_id
    multimodal_fallback = stored_id
    for candidate_id, candidate in _all_monster_defs().items():
        if candidate.get("name") != base_name:
            continue
        candidate_common = (candidate.get("common_name") or "").lower()
        if want_major and "(major)" in candidate_common:
            return candidate_id
        if not want_major and "(minor)" in candidate_common:
            return candidate_id
        if "multimodal" in candidate_common:
            multimodal_fallback = candidate_id
    return multimodal_fallback
def _paironormal_mode_entry(form_id, mode_value, is_active, unique_id):
    return {
        "monster": form_id,
        "monster_id": form_id,
        "monsterId": form_id,
        "monsterTypeId": form_id,
        "monsterEntityId": form_id,
        "mode": mode_value,
        "paironormal_mode": mode_value,
        "island_mode": mode_value,
        "uniqueMonsterId": unique_id,
        "modeMonsterUniqueId": unique_id,
        "user_monster_id": unique_id,
        "a": 1 if is_active else 0,
        "isActive": is_active,
        "is_active": is_active,
    }


def build_paironormal_modes(monster, island_type_id, island_mode):
    source_id = monster.get("monster", 0)
    stored_id = resolve_paironormal_stored_monster_id(source_id, island_type_id)
    render_id = resolve_paironormal_renderable_monster_id(stored_id, island_type_id, island_mode)
    if stored_id <= 0 or render_id <= 0:
        return
    stored_definition = get_monster_definition(stored_id)
    if not stored_definition or not is_paironormal_multimodal(stored_definition):
        return
    major_id = find_paironormal_form_id(stored_id, island_type_id, True)
    minor_id = find_paironormal_form_id(stored_id, island_type_id, False)
    monster["monster"] = stored_id
    monster["monster_id"] = stored_id
    monster["monsterId"] = render_id
    monster["monsterTypeId"] = render_id
    monster["monsterEntityId"] = render_id
    monster["paironormal_base_monster"] = stored_id
    monster["paironormal_render_monster"] = render_id
    monster["paironormal_mode"] = island_mode
    monster["island_mode"] = island_mode
    monster["mode"] = island_mode
    monster["is_modal"] = True
    monster["isModal"] = True
    unique_id = monster.get("user_monster_id", 0) or 0
    modes = []
    if major_id > 0 and major_id != stored_id:
        modes.append(_paironormal_mode_entry(major_id, 0, render_id == major_id, unique_id))
    if minor_id > 0 and minor_id != stored_id and minor_id != major_id:
        modes.append(_paironormal_mode_entry(minor_id, 1, render_id == minor_id, unique_id))
    if modes:
        monster["modes"] = modes
def get_monster_level_definition(monster_id, level):
    definition = get_monster_definition(monster_id)
    if not definition or not definition.get("levels"):
        return None
    fallback = None
    for level_def in definition["levels"]:
        if level_def is None:
            continue
        fallback = level_def
        if level_def.get("level") == level:
            return level_def
    return fallback
def get_max_monster_level(monster_id):
    definition = get_monster_definition(monster_id)
    if not definition or not definition.get("levels"):
        return 20
    max_level = 0
    for level_def in definition["levels"]:
        if level_def is None:
            continue
        max_level = max(max_level, level_def.get("level", 0) or 0)
    return max_level or 20
_COLLECTION_ALIASES = {"shards": "ethereal_currency", "eggwildcards": "egg_wildcards", "wildcards": "egg_wildcards"}
def normalize_collection_type(collection_type):
    normalized = (collection_type or "").strip().lower()
    if not normalized:
        return "coins"
    return _COLLECTION_ALIASES.get(normalized, normalized)
def _infer_monster_collection_type(existing_type, island_type, level_def):
    existing = normalize_collection_type(existing_type)
    if existing not in ("coins", "none"):
        return existing
    if island_type in (24, PAIRONORMAL_ISLAND_TYPE):
        return "starpower"
    if island_type == 25:
        return "egg_wildcards"
    if island_type in (26, 27, 28, 29):
        return "ethereal_currency"
    max_coins = max(0, (level_def or {}).get("max_coins", 0) or 0)
    max_ethereal = max(0, (level_def or {}).get("max_ethereal", 0) or 0)
    if max_coins <= 0 and max_ethereal > 0:
        return "ethereal_currency"
    return "coins"
def compute_monster_economy(monster, island_type):
    monster_id = monster.get("monster", 0)
    if not monster_id:
        return "coins", 225, 5
    level = max(1, monster.get("level", 1) or 1)
    level_def = get_monster_level_definition(monster_id, level)
    max_coins, income_rate, max_ethereal, ethereal_rate = 225, 5, 0, 0
    if level_def:
        max_coins = max(0, level_def.get("max_coins", max_coins) or max_coins)
        income_rate = max(0, level_def.get("coins", income_rate) or income_rate)
        max_ethereal = max(0, level_def.get("max_ethereal", 0) or 0)
        ethereal_rate = max(0, level_def.get("ethereal_currency", 0) or 0)
    collection_type = _infer_monster_collection_type("", island_type, level_def)
    if collection_type == "ethereal_currency":
        return "ethereal_currency", max(1, max_ethereal), max(1, ethereal_rate)
    if collection_type == "starpower":
        rate_table = _paironormal_starpower_rates()
        row = rate_table[0] if rate_table else [1.0]
        multiplier = row[min(len(row) - 1, max(0, level - 1))]
        starpower_rate = max(1, int(round(multiplier)))
        return "starpower", max(1, max_coins), starpower_rate
    return collection_type, max(1, max_coins), max(1, income_rate)
_paironormal_starpower_rates_cache = None
def _paironormal_starpower_rates():
    global _paironormal_starpower_rates_cache
    if _paironormal_starpower_rates_cache is None:
        rates = []
        data = load_db_json("game_settings") or {}
        for entry in data.get("user_game_settings") or []:
            if entry.get("key") == "USER_PAIRONORMAL_STARPOWER_RATES":
                try:
                    rates = json.loads(entry.get("value") or "[]")
                except (ValueError, TypeError):
                    rates = []
                break
        _paironormal_starpower_rates_cache = rates
    return _paironormal_starpower_rates_cache
def _parse_allowed_islands(raw):
    if not raw:
        return set()
    try:
        return set(int(x) for x in raw.strip("[] ").split(",") if x.strip() != "")
    except ValueError:
        return set()
def _all_structure_defs():
    global _structure_defs_cache
    if _structure_defs_cache is None:
        _structure_defs_cache = _build_structure_defs()
    return _structure_defs_cache
_bakery_defs_cache = None
def _build_bakery_defs():
    data = load_db_json("db_bakery_foods")
    defs = {}
    if data and data.get("bakery_data"):
        for entry in data["bakery_data"]:
            fid = entry.get("id")
            if fid is not None:
                defs[fid] = entry
    return defs
def get_bakery_food(food_id):
    global _bakery_defs_cache
    if _bakery_defs_cache is None:
        _bakery_defs_cache = _build_bakery_defs()
    return _bakery_defs_cache.get(food_id)
_island_theme_defs_cache = None
def _island_theme_defs():
    global _island_theme_defs_cache
    if _island_theme_defs_cache is None:
        data = load_db_json("db_island_themes") or {}
        _island_theme_defs_cache = data.get("island_theme_data") or []
    return _island_theme_defs_cache
_island_catalog_cache = None
def _island_catalog():
    global _island_catalog_cache
    if _island_catalog_cache is None:
        data = load_db_json("db_island_v2") or {}
        catalog = {}
        for entry in data.get("islands_data") or []:
            island_id = entry.get("island_id")
            if island_id is not None:
                catalog[island_id] = entry
        _island_catalog_cache = catalog
    return _island_catalog_cache
def resolve_island_type(island_id):
    entry = _island_catalog().get(island_id)
    if entry and entry.get("island_type") is not None:
        return entry["island_type"]
    return island_id
def is_valid_island_id(island_id):
    return island_id in _island_catalog()
def island_for_theme(theme_id):
    for theme in _island_theme_defs():
        if theme.get("theme_id") == theme_id:
            return theme.get("island", 0)
    return 0
_scratch_payload_cache = None
def _scratch_payload():
    global _scratch_payload_cache
    if _scratch_payload_cache is None:
        data = load_db_json("db_scratch_offs") or {}
        _scratch_payload_cache = data.get("payload") or data
    return _scratch_payload_cache
def get_scratch_prizes(type_code):
    prizes = _scratch_payload().get("scratch_offs") or []
    return [p for p in prizes if p.get("type") == type_code]
def get_spin_wheel_prizes():
    return _scratch_payload().get("spin_wheel_prizes") or []
_ethereal_islet_defs_cache = None
def get_ethereal_islet_definition(island_id):
    global _ethereal_islet_defs_cache
    if _ethereal_islet_defs_cache is None:
        defs = {}
        data = load_db_json("db_ethereal_islet") or {}
        for entry in data.get("ethereal_islet_data") or []:
            iid = entry.get("island_id")
            if iid is not None:
                defs[iid] = entry
        _ethereal_islet_defs_cache = defs
    return _ethereal_islet_defs_cache.get(island_id)
_breeding_data_cache = None
def _breeding_data():
    global _breeding_data_cache
    if _breeding_data_cache is None:
        rows = []
        for data in _load_db_chunk_chain("db_breeding"):
            rows.extend(data.get("breeding_data") or [])
        _breeding_data_cache = rows
    return _breeding_data_cache
def _breeding_boost_multiplier():
    try:
        now = int(__import__("time").time() * 1000)
        data = load_db_json("gs_timed_events") or {}
        boost = 0
        for event in data.get("timed_event_list") or []:
            etype = str(event.get("event_type", "")).lower()
            start = int(event.get("start_date", 0) or 0)
            end = int(event.get("end_date", 0) or 0)
            if not (start <= now <= end):
                continue
            if etype == "breedingchanceboost":
                entries = event.get("data") or []
                first = entries[0] if entries else {}
                boost = max(boost, max(0, int(first.get("multiplier", 0) or 0)))
            elif etype in ("breedingpromo", "breedingpromotion"):
                boost = max(boost, 100)
    except Exception:
        pass
    return boost

def choose_breeding_result_monster(monster_a, monster_b):
    if not monster_a or not monster_b:
        return monster_a or monster_b or 3
    weighted = []
    boost = _breeding_boost_multiplier()
    boost_factor = 1 + (boost / 100.0) * 24
    for row in _breeding_data():
        a, b = row.get("a", 0), row.get("b", 0)
        if not ((a == monster_a and b == monster_b) or (a == monster_b and b == monster_a)):
            continue
        result_id = row.get("c", 0)
        if not result_id or result_id <= 0:
            continue
        if get_monster_definition(result_id) is None:
            continue
        weight = max(1, row.get("d", 1) or 1)
        if boost > 0 and result_id not in (monster_a, monster_b):
            weight = max(1, round(weight * boost_factor))
        weighted.extend([result_id] * weight)
    return random.choice(weighted) if weighted else monster_a
def get_max_structure_id(island_type, structure_type):
    defs = _all_structure_defs()
    candidates = [
        entry for entry in defs.values()
        if entry.get("structure_type") == structure_type
        and island_type in _parse_allowed_islands(entry.get("allowed_on_island"))
    ]
    if not candidates:
        return None
    candidate_ids = {entry["structure_id"] for entry in candidates}
    upgrade_targets = {entry.get("upgrades_to") for entry in candidates if entry.get("upgrades_to")}
    roots = [entry for entry in candidates if entry["structure_id"] not in upgrade_targets]
    current = roots[0] if roots else candidates[0]
    seen = {current["structure_id"]}
    while current.get("upgrades_to"):
        next_def = get_structure_definition(current["upgrades_to"])
        if not next_def or next_def["structure_id"] in seen:
            break
        current = next_def
        seen.add(current["structure_id"])
    return current["structure_id"]
