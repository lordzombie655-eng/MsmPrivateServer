import json

from msm_playerdata import create_player_properties, load_player, save_player
from msm_protocol import SFSFloat
from msm_store import load_db_json

CURRENCY_LOOT_KEYS = {"coins", "diamonds", "food", "relics", "keys", "ethereal_currency", "starpower", "clubbox_tokens"}






_LOOT_WIRE_TYPES = {
    "coins": 7, "food": 4, "keys": 16, "ethereal_currency": 18,
    "diamonds": 9, "relics": 5, "starpower": 11, "clubbox_tokens": 6,
}

_cache = {}


def _reward_tracks():
    if "tracks" not in _cache:
        data = load_db_json("db_reward_tracks") or {}
        tracks = {}
        for t in data.get("reward_tracks_data") or []:
            tid = t.get("id")
            if tid is not None:
                tracks[tid] = t
        _cache["tracks"] = tracks
    return _cache["tracks"]


def active_encore_event():
    data = load_db_json("gs_timed_events") or {}
    for event in data.get("timed_event_list") or []:
        if event.get("event_type") != "Encore":
            continue
        info = (event.get("data") or [{}])[0]
        return event.get("id"), info.get("reward_track_id")
    return None, None


def _ensure_encore_state(player_object, event_id):
    state = player_object.get("current_encore_state")
    if not isinstance(state, dict) or state.get("event_id") != event_id:
        state = {"event_id": event_id, "total_points": 0.0}
        player_object["current_encore_state"] = state
    return state


def encore_progress(player_object, track_id, points):
    if points <= 0:
        return None
    event_id, active_track_id = active_encore_event()
    if event_id is None or active_track_id != track_id:
        return None
    state = _ensure_encore_state(player_object, event_id)
    before = float(state.get("total_points", 0.0) or 0.0)
    after = before + float(points)
    state["total_points"] = after
    entry = {"current_points": SFSFloat(after)}
    track = _reward_tracks().get(track_id)
    levels = sorted(track.get("levels") or [], key=lambda lv: lv.get("points", 0) or 0) if track else []
    cycle_length = levels[-1].get("points", 0) if levels else 0
    if levels and cycle_length:
        eff_before = before % cycle_length
        delta = after - before
        eff_after = eff_before + delta
        crossed = None
        for lv in levels:
            threshold = lv.get("points", 0) or 0
            if eff_before < threshold <= eff_after:
                crossed = lv
        if crossed is None and eff_after > cycle_length:
            crossed = levels[-1]
        if crossed is not None:
            items = _apply_loot(player_object, crossed.get("loot"))
            entry["loot"] = [
                {"amount": it.get("amount", 0), "premium": False, "id": 1,
                 "type": _LOOT_WIRE_TYPES.get(it.get("resource"), 1)}
                for it in items if it.get("resource") in _LOOT_WIRE_TYPES
            ]
            entry["updateCardAlbum"] = True
    return entry


def properties_with_encore(player_object, track_id, points):
    entry = encore_progress(player_object, track_id, points)
    props = create_player_properties(player_object)
    if entry is not None:
        props = [{"encore_event": entry}] + props
    return props


def _claimed_ids(player_object):
    return set(player_object.get("encore_claimed_levels") or [])


def _mark_claimed(player_object, level_id):
    ids = _claimed_ids(player_object)
    ids.add(level_id)
    player_object["encore_claimed_levels"] = sorted(ids)


def _apply_loot(player_object, loot_json):
    items = []
    try:
        loot = json.loads(loot_json) if loot_json else {}
    except ValueError:
        loot = {}
    for key, amount in loot.items():
        amount = amount or 0
        if key == "card_pack":
            import msm_cardalbum
            msm_cardalbum._grant_packs(player_object, amount)
            items.append({"amount": amount, "resource": "card_pack"})
        elif key in CURRENCY_LOOT_KEYS:
            player_object[key] = (player_object.get(key, 0) or 0) + amount
            player_object[f"{key}_actual"] = player_object[key]
            items.append({"amount": amount, "resource": key})
        else:
            items.append({"amount": amount, "resource": key})
    return items


def collect_rewards(username, params):
    event_id, track_id = active_encore_event()
    if event_id is None or track_id is None:
        return {"success": False, "notificationOnFail": False}
    root, player_object = load_player(username)
    state = _ensure_encore_state(player_object, event_id)
    points = float(state.get("total_points", 0.0) or 0.0)
    track = _reward_tracks().get(track_id)
    if track is None:
        return {"success": False, "notificationOnFail": False}
    claimed = _claimed_ids(player_object)
    levels = sorted(track.get("levels") or [], key=lambda lv: lv.get("level", 0))
    cumulative = 0
    next_level = None
    for lv in levels:
        cumulative += lv.get("points", 0) or 0
        if lv.get("id") in claimed:
            continue
        if points >= cumulative:
            next_level = lv
        break
    if next_level is None:
        return {"success": False, "notificationOnFail": False}
    items = _apply_loot(player_object, next_level.get("loot"))
    _mark_claimed(player_object, next_level.get("id"))
    save_player(username, root)
    return {"success": True, "items": items, "properties": create_player_properties(player_object)}
