import logging
import random
import time
from msm_gamedata import get_scratch_prizes, get_spin_wheel_prizes
from msm_playerdata import SFSLong, add_actual_currencies, create_player_properties, load_player, save_player
logger = logging.getLogger("msm.rewards")
def _weighted_pick(prizes):
    if not prizes:
        return None
    total = sum(max(0, p.get("probability", 0) or 0) for p in prizes)
    if total <= 0:
        return random.choice(prizes)
    roll = random.uniform(0, total)
    upto = 0
    for prize in prizes:
        upto += max(0, prize.get("probability", 0) or 0)
        if roll <= upto:
            return prize
    return prizes[-1]
def _ticket_from_prize(prize, request_type):
    prize = prize or {}
    return {
        "type": request_type,
        "is_top_prize": int(prize.get("is_top_prize", 0) or 0),
        "prize": prize.get("prize", "coins"),
        "id": prize.get("id", 0),
        "amount": int(prize.get("amount", 0) or 0),
    }
_SCALED_PRIZE_IDS = (2, 9, 4, 6, 5, 7, 3, 11)
def _scaled_prizes_payload(prizes):
    by_id = {p.get("id", 0): p for p in prizes if isinstance(p, dict)}
    rows = []
    for prize_id in _SCALED_PRIZE_IDS:
        prize = by_id.get(prize_id)
        if prize is not None:
            rows.append({"id": prize_id, "scaled_amount": int(prize.get("amount", 0) or 0)})
    return {"prizes": rows}
_SCRATCH_COOLDOWN_MS = 20 * 3600 * 1000
def _scratch_time_key(request_type):
    return "monsterScratchTime" if request_type == "M" else "currencyScratchTime"
def _scratch_flag_key(request_type):
    return "has_scratch_off_m" if request_type == "M" else "has_scratch_off_s"
def _scratch_available(player_object, request_type):
    if player_object.get(_scratch_flag_key(request_type), True):
        return True
    last = player_object.get(_scratch_time_key(request_type), 0) or 0
    return (int(time.time() * 1000) - last) >= _SCRATCH_COOLDOWN_MS
def player_has_scratch_off(username, params):
    request_type = str(params.get("type") or "M").upper()
    root, player_object = load_player(username)
    return {"success": _scratch_available(player_object, request_type), "type": request_type}
def play_scratch_off(username, params):
    request_type = str(params.get("type") or "M").upper()
    root, player_object = load_player(username)
    if not _scratch_available(player_object, request_type):
        return {"success": False, "type": request_type}
    prizes = get_scratch_prizes("M") if request_type == "M" else get_spin_wheel_prizes()
    prize = _weighted_pick(prizes)
    ticket = _ticket_from_prize(prize, request_type)
    now = SFSLong(int(time.time() * 1000))
    player_object[_scratch_flag_key(request_type)] = False
    player_object[_scratch_time_key(request_type)] = now
    player_object["_pending_scratch_ticket"] = ticket
    save_player(username, root)
    result = {"success": True, "ticket": ticket}
    if request_type != "M":
        result["scaled_prizes"] = _scaled_prizes_payload(prizes)
    if request_type == "S" and ticket.get("prize") == "coins":
        result["properties"] = create_player_properties(player_object)
    return result
def collect_scratch_off(username, params):
    root, player_object = load_player(username)
    ticket = player_object.pop("_pending_scratch_ticket", None) or {}
    request_type = str(ticket.get("type") or params.get("type") or "M").upper()
    prize_type = ticket.get("prize", "coins")
    amount = int(ticket.get("amount", 0) or 0)
    if prize_type != "monster":
        _add_currency(player_object, prize_type, amount)
    save_player(username, root)
    properties = create_player_properties(player_object)
    now = SFSLong(int(player_object.get(_scratch_time_key(request_type), 0) or 0))
    properties.append({_scratch_time_key(request_type): now})
    properties.append({_scratch_flag_key(request_type): bool(player_object.get(_scratch_flag_key(request_type), False))})
    return {"success": True, "rare": False, "epic": False, "properties": properties}
def _wire_prizes(prizes):
    rows = []
    for p in prizes:
        row = dict(p)
        row["amount"] = int(row.get("amount", 0) or 0)
        rows.append(row)
    return rows
def get_prize_wheel(username, params):
    prizes = _wire_prizes(get_spin_wheel_prizes())
    return {
        "success": True, "available": True, "spins_remaining": 1, "type": "S",
        "spin_wheel_prizes": prizes, "prizes": prizes,
    }
def spin_prize_wheel(username, params):
    root, player_object = load_player(username)
    raw_prizes = get_spin_wheel_prizes()
    prize = _weighted_pick(raw_prizes)
    prizes = _wire_prizes(raw_prizes)
    result = {
        "success": True, "available": True, "spins_remaining": 0, "type": "S",
        "spin_wheel_prizes": prizes, "prizes": prizes,
        "ticket": _ticket_from_prize(prize, "S"),
        "scaled_prizes": _scaled_prizes_payload(raw_prizes),
        "properties": create_player_properties(player_object),
    }
    add_actual_currencies(result, player_object)
    return result
def collect_prize_wheel(username, params):
    return collect_scratch_off(username, params)
_FLIP_LEVEL_COUNT = 9
_FLIP_SAFE_PRIZE_TYPES = ("coins", "food", "ethereal_currency")
def _flip_prize_pool():
    prizes = [p for p in get_spin_wheel_prizes() if p.get("prize") in _FLIP_SAFE_PRIZE_TYPES]
    return prizes if prizes else [{"amount": 5000, "prize": "coins", "probability": 1}]
def _add_currency(player_object, prize_type, amount):
    key = {"food": "food", "diamonds": "diamonds", "keys": "keys", "relics": "relics",
           "ethereal_currency": "ethereal_currency", "jackpot": "diamonds"}.get(prize_type, "coins")
    if amount <= 0:
        return key, 0
    player_object[key] = (player_object.get(key, 0) or 0) + amount
    return key, amount
def _flip_level(player_object):
    return max(1, min(_FLIP_LEVEL_COUNT, int(player_object.get("flip_level", 1) or 1)))
def flip_minigame_cost(username, params):
    root, player_object = load_player(username)
    level = int(params.get("level") or 0) or _flip_level(player_object)
    result = {"success": True, "coin_cost": 0, "diamond_cost": 0 if level <= 1 else 2}
    pools = []
    for pool_id in (2, 3, 4):
        prizes = [p for p in _flip_prize_pool() if p.get("is_top_prize", 0) == (1 if pool_id == 4 else 0)]
        if prizes:
            pools.append({
                "pool": pool_id,
                "remaining": [{"amt": int(p.get("amount", 0) or 0), "type": p.get("prize", "coins")} for p in prizes],
            })
    if pools:
        result["prizes_remaining"] = pools
    return result
def purchase_flip_mini_game(username, params):
    root, player_object = load_player(username)
    level = int(params.get("level") or 0) or _flip_level(player_object)
    prize = _weighted_pick(_flip_prize_pool()) or {}
    now = SFSLong(int(time.time() * 1000))
    reward = {"pool": 1, "amt": int(prize.get("amount", 0) or 0), "type": prize.get("prize", "coins")}
    scaled = [{"level": i} for i in range(1, _FLIP_LEVEL_COUNT + 1)]
    return {
        "success": True, "ingame_reward": reward, "level": level, "flipGameTime": now,
        "level_id": level, "scaled_endgame_rewards": scaled,
    }
def collect_flip_level(username, params):
    root, player_object = load_player(username)
    level = int(params.get("level") or 0) or _flip_level(player_object)
    prize = _weighted_pick(_flip_prize_pool()) or {}
    prize_type = prize.get("prize", "coins")
    amount = prize.get("amount", 0)
    _add_currency(player_object, prize_type, amount)
    next_level = level + 1 if level < _FLIP_LEVEL_COUNT else 1
    player_object["flip_level"] = next_level
    save_player(username, root)
    reward = {"pool": 1, "amt": int(amount or 0), "type": prize_type}
    result = {"silent": True, "ingame_reward": reward, "level": level, "success": True, "level_id": level}
    result["properties"] = create_player_properties(player_object)
    return result
def collect_flip_mini_game(username, params):
    root, player_object = load_player(username)
    now = SFSLong(int(time.time() * 1000))
    result = {"silent": True, "success": True}
    result["properties"] = create_player_properties(player_object)
    for prop in result["properties"]:
        if "flipGameTime" in prop:
            prop["flipGameTime"] = now
            break
    else:
        result["properties"].append({"flipGameTime": now})
    return result
def get_memory_game_numbers(username, params):
    root, player_object = load_player(username)
    active_id = player_object.get("active_island", 0)
    numbers = []
    for island in player_object.get("islands") or []:
        if island is None or island.get("user_island_id") != active_id:
            continue
        for monster in island.get("monsters") or []:
            if len(numbers) >= 12:
                break
            monster_id = monster.get("monster", 0) if monster is not None else 0
            if monster_id:
                numbers.append(monster_id)
        break
    for default_id in (3, 4, 5, 6, 7, 8):
        if len(numbers) >= 4:
            break
        numbers.append(default_id)
    return {
        "success": True, "numbers": numbers, "num_cards": len(numbers),
        "max_time": 60, "time_limit": 60, "coin_reward": SFSLong(5000),
    }
