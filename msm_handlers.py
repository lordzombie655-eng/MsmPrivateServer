import logging
import time
import msm_box
import msm_cardalbum
import msm_islands
import msm_monsters
import msm_rewards
import msm_rewardtracks
import msm_structures
import msm_synthesis
from msm_playerdata import add_actual_currencies, coerce_wire_types, create_player_properties, load_player
from msm_protocol import SFSLong
from msm_store import load_db_json, load_user_data, normalize_db_payload, save_user_data
logger = logging.getLogger("msm.handlers")
DEFAULT_USERNAME = "Nextstars"
def _find_island(islands, user_island_id):
    for island in islands:
        if isinstance(island, dict) and island.get("user_island_id") == user_island_id:
            return island
    return None
def handle_gs_change_island(username, params):
    user_island_id = params.get("user_island_id")
    if user_island_id is None:
        return None
    root = load_user_data(username)
    player_object = root.get("player_object")
    islands = player_object.get("islands") or [] if player_object is not None else []
    target_island = _find_island(islands, user_island_id)
    if target_island is None:
        return {
            "success": False, "user_island_id": SFSLong(user_island_id),
            "message": "Island not found",
        }
    if player_object is not None:
        player_object["active_island"] = user_island_id
        save_user_data(username, root)
    target_island = coerce_wire_types(target_island)
    result = {
        "success": True, "user_island_id": SFSLong(user_island_id),
        "user_island": target_island, "island": target_island, "islands_data": [target_island],
    }
    return result
def handle_gs_player(username, params):
    root, player_object = load_player(username)
    for island in player_object.get("islands") or []:
        msm_monsters.grant_full_book(island)
        msm_monsters.backfill_titansoul_state(island)
        msm_structures.backfill_awakener_structures(island)
        msm_islands.backfill_island_type(island)
        msm_box.repair_broken_box_eggs(island)
        msm_synthesis.repair_glitched_synthesis(island)
    msm_islands.migrate_legacy_mirror_ids(player_object)
    save_user_data(username, root)
    return {"player_object": coerce_wire_types(player_object)}
def _simple(fn):
    def handler(username, params):
        return fn(username, params)
    return handler
def _with_structure_update(command, fn, always=False):
    def handler(username, params):
        result, update = fn(username, params)
        frames = [(command, result)]
        if update or always:
            frames.append(("gs_update_structure", update))
        return frames
    return handler
def _discard_structure_update(fn):
    def handler(username, params):
        result, _update = fn(username, params)
        return result
    return handler
def _with_monster_update(command, fn):
    def handler(username, params):
        result, update = fn(username, params)
        frames = [(command, result)]
        if update:
            frames.append(("gs_update_monster", update))
        return frames
    return handler
def _with_monster_update_first(command, fn):
    def handler(username, params):
        result, update = fn(username, params)
        frames = []
        if update:
            frames.append(("gs_update_monster", update))
        frames.append((command, result))
        return frames
    return handler
def _mega_monster_handler(username, params):
    logger.info("gs_mega_monster_message params: %r", params)
    result, update = msm_monsters.biggify_monster(username, params)
    logger.info("gs_mega_monster_message result: %r update: %r", result, update)
    frames = []
    if update:
        frames.append(("gs_update_monster", update))
    frames.append(("gs_mega_monster_message", result))
    return frames
def _generic_success(extra_array_keys=()):
    def handler(username, params):
        result = {"success": True}
        for key in extra_array_keys:
            result[key] = []
        return result
    return handler
def _finish_breeding(force_complete):
    def handler(username, params):
        return msm_monsters.finish_breeding(username, params, force_complete)
    return handler
def _teleport_monster(send_home):
    def handler(username, params):
        root, player_object = load_player(username)
        source_island_id = params.get("user_island_id") or player_object.get("active_island", 0) or 0
        source_island = _find_island(player_object.get("islands") or [], source_island_id)
        happy_effects = []
        if source_island is not None:
            for monster in source_island.get("monsters") or []:
                if monster is not None and monster.get("user_monster_id"):
                    happy_effects.append({
                        "user_monster_id": SFSLong(monster.get("user_monster_id", 0)),
                        "happiness": monster.get("happiness", 0) or 0,
                    })
        result = msm_monsters.move_battle_monster(username, params, send_home)
        if not result.get("success"):
            return result
        return [
            ("gs_send_monster_home" if send_home else "battle_teleport", result),
            ("gs_multi_update_monster", {"success": True, "monster_happy_effects": happy_effects}),
        ]
    return handler
def _send_to_magical_nexus_handler(username, params):
    logger.info("gs_send_to_magical_nexus params: %r", params)
    monster_id = (params.get("user_monster_id") or params.get("monster_id")
                  or params.get("source_user_monster_id") or params.get("id") or 0)
    root, player_object = load_player(username)
    source_island, monster = None, None
    for island in player_object.get("islands") or []:
        if island is None:
            continue
        for candidate in island.get("monsters") or []:
            if candidate is not None and candidate.get("user_monster_id") == monster_id:
                source_island, monster = island, candidate
                break
        if monster is not None:
            break
    result, nursery = msm_monsters.send_to_magical_nexus(username, params)
    if not result.get("success"):
        return result
    update_entry = {"user_monster_id": SFSLong(monster_id), "happiness": 0, "last_collection": SFSLong(int(time.time() * 1000))}
    if monster is not None:
        update_entry["happiness"] = monster.get("happiness", 0) or 0
    return [
        ("gs_send_to_magical_nexus", result),
        ("gs_multi_update_monster", {
            "success": True, "user_monster_id": SFSLong(monster_id),
            "update_monster_list": [update_entry],
        }),
    ]
def _buy_egg_handler(username, params):
    logger.info("gs_buy_egg params: %r", params)
    return msm_monsters.buy_egg(username, params)[0]
def _costume_action(command):
    def handler(username, params):
        return msm_monsters.costume_action(username, params, command)
    return handler
def _collect_monster(command):
    def handler(username, params):
        outcome = msm_monsters.collect_monster(username, params)
        if isinstance(outcome, tuple):
            result, update_bundle = outcome
            frames = [(command, result)]
            for update in update_bundle.get("monster_updates", []):
                frames.append(("gs_update_monster", update))
            return frames
        return outcome
    return handler
def _hatch_egg_handler(username, params):
    return msm_monsters.hatch_egg(username, params)
def _viewed_egg_handler(username, params):
    result, sold_update = msm_monsters.viewed_egg(username, params)
    frames = []
    if sold_update:
        frames.append(("gs_update_sold_monsters", sold_update))
    frames.append(("gs_viewed_egg", result))
    return frames
def _sell_monster_handler(username, params):
    result, sold_update = msm_monsters.sell_monster(username, params)
    frames = []
    if sold_update:
        frames.append(("gs_update_sold_monsters", sold_update))
    frames.append(("gs_sell_monster", result))
    return frames
def _facebook_help_instances_stub(username, params):
    return {"success": True, "egg_results": [], "breeding_results": [], "count": 0}
def _battle_claim_versus_rewards(username, params):
    root = load_user_data(username)
    player_object = root.get("player_object") or {}
    tier = params.get("tier", 1) or 1
    campaign_id = params.get("campaign_id", 1000) or 1000
    reward = {"coins": 500 * tier, "food": 200 * tier}
    for key, amount in reward.items():
        player_object[key] = (player_object.get(key, 0) or 0) + amount
        player_object[f"{key}_actual"] = player_object[key]
    save_user_data(username, root)
    result = {
        "success": True, "tier": tier, "campaign_id": campaign_id,
        "claimed_on": SFSLong(int(time.time() * 1000)),
        "season_rewards": reward,
        "properties": create_player_properties(player_object),
    }
    add_actual_currencies(result, player_object)
    return result
def _battle_set_music(username, params):
    return {"success": True, "currently_playing": params.get("track", params.get("currently_playing", 0)) or 0, "muted": bool(params.get("muted", False))}
def _client_keep_alive(username, params):
    return {}
def _metric_event(username, params):
    return {"event": params.get("event", "")}
def _collect_rewards_stub(username, params):
    return {"success": False, "notificationOnFail": False}
_STATIC_ALIAS_RESPONSES = {
    "gs_daily_login_reward_seen": "gs_update_island_tutorials",
    "gs_news_seen": "gs_update_island_tutorials",
    "gs_generic_success": "gs_update_island_tutorials",
    "gs_update_island_tutorials": "gs_update_island_tutorials",
}
GAMEPLAY_HANDLERS = {
    "gs_change_island": handle_gs_change_island,
    "gs_player": handle_gs_player,
    "gs_buy_island": _simple(msm_islands.buy_island),
    "update_island_mode": _simple(msm_islands.update_island_mode),
    "gs_save_island_warp_speed": _simple(msm_islands.set_warp_island),
    "gs_mute_island": _simple(msm_islands.mute_island),
    "gs_buy_structure": _simple(msm_structures.buy_structure),
    "gs_move_structure": _with_structure_update("gs_move_structure", msm_structures.move_structure, always=True),
    "move_structure": _with_structure_update("move_structure", msm_structures.move_structure, always=True),
    "gs_update_structure_position": _with_structure_update("gs_update_structure_position", msm_structures.move_structure, always=True),
    "gs_sell_structure": _simple(msm_structures.sell_structure),
    "gs_remove_obstacle": _simple(msm_structures.sell_structure),
    "gs_clear_obstacle": _simple(msm_structures.sell_structure),
    "gs_buy_remove_obstacle": _simple(msm_structures.sell_structure),
    "gs_remove_island_obstacle": _simple(msm_structures.sell_structure),
    "gs_flip_structure": _with_structure_update("gs_flip_structure", msm_structures.flip_structure, always=True),
    "gs_mute_structure": _with_structure_update("gs_mute_structure", msm_structures.mute_structure),
    "gs_start_upgrade_structure": _with_structure_update("gs_start_upgrade_structure", msm_structures.start_upgrade_structure),
    "gs_upgrade_structure": _with_structure_update("gs_upgrade_structure", msm_structures.start_upgrade_structure),
    "gs_finish_upgrade_structure": _simple(msm_structures.finish_upgrade_structure),
    "gs_speed_up_upgrade_structure": _with_structure_update("gs_speed_up_upgrade_structure", msm_structures.speed_up_upgrade_structure),
    "gs_speedup_upgrade_structure": _with_structure_update("gs_speedup_upgrade_structure", msm_structures.speed_up_upgrade_structure),
    "gs_speed_up_upgrade_structure_video": _with_structure_update("gs_speed_up_upgrade_structure_video", msm_structures.speed_up_upgrade_structure),
    "gs_speedup_upgrade_structure_video": _with_structure_update("gs_speedup_upgrade_structure_video", msm_structures.speed_up_upgrade_structure),
    "gs_start_fuguing": _with_structure_update("gs_start_fuguing", msm_structures.start_fuguing),
    "gs_finish_fuguing": _with_structure_update("gs_finish_fuguing", msm_structures.finish_fuguing),
    "gs_speed_up_fuguing": _with_structure_update("gs_speed_up_fuguing", msm_structures.speed_up_fuguing),
    "gs_speedup_fuguing": _with_structure_update("gs_speedup_fuguing", msm_structures.speed_up_fuguing),
    "gs_collect_structure": _with_structure_update("gs_collect_structure", msm_structures.collect_structure),
    "gs_collect_from_mine": _with_structure_update("gs_collect_from_mine", msm_structures.collect_mine),
    "gs_check_in_structure": _simple(msm_structures.store_structure),
    "gs_store_structure": _simple(msm_structures.store_structure),
    "gs_store_decoration": _simple(msm_structures.store_structure),
    "gs_pack_in_structure": _simple(msm_structures.store_structure),
    "gs_pack_in_decoration": _simple(msm_structures.store_structure),
    "gs_move_structure_to_storage": _simple(msm_structures.store_structure),
    "gs_check_out_structure": _simple(msm_structures.unstore_structure),
    "gs_unstore_structure": _simple(msm_structures.unstore_structure),
    "gs_unstore_decoration": _simple(msm_structures.unstore_structure),
    "gs_pack_out_structure": _simple(msm_structures.unstore_structure),
    "gs_pack_out_decoration": _simple(msm_structures.unstore_structure),
    "gs_move_structure_from_storage": _simple(msm_structures.unstore_structure),
    "gs_start_baking": _simple(msm_structures.start_baking),
    "gs_speed_up_baking": _simple(msm_structures.speed_up_baking),
    "gs_speedup_baking": _simple(msm_structures.speed_up_baking),
    "gs_finish_baking": _simple(msm_structures.finish_baking),
    "gs_move_monster": _with_monster_update("gs_move_monster", msm_monsters.move_monster),
    "move_monster": _with_monster_update("move_monster", msm_monsters.move_monster),
    "gs_update_monster_position": _with_monster_update("gs_update_monster_position", msm_monsters.move_monster),
    "gs_flip_monster": _with_monster_update("gs_flip_monster", msm_monsters.flip_monster),
    "gs_mute_monster": _with_monster_update("gs_mute_monster", msm_monsters.mute_monster),
    "gs_add_soul_link": _with_monster_update_first("gs_add_soul_link", msm_monsters.add_soul_link),
    "gs_remove_soul_link": _with_monster_update_first("gs_remove_soul_link", msm_monsters.remove_soul_link),
    "gs_toggle_titansoul_fx": _with_monster_update_first("gs_toggle_titansoul_fx", msm_monsters.toggle_titansoul_fx),
    "gs_mega_monster_message": _mega_monster_handler,
    "gs_biggify_monster": _mega_monster_handler,
    "gs_bigify_monster": _mega_monster_handler,
    "gs_bigfy_monster": _mega_monster_handler,
    "gs_mega_monster": _mega_monster_handler,
    "gs_feed_monster": _with_monster_update("gs_feed_monster", msm_monsters.feed_monster),
    "gs_sell_monster": _sell_monster_handler,
    "gs_name_monster": _simple(msm_monsters.name_monster),
    "gs_collect_monster": _collect_monster("gs_collect_monster"),
    "gs_collect_multi_monster": _collect_monster("gs_collect_multi_monster"),
    "gs_buy_egg": _buy_egg_handler,
    "gs_hatch_egg": _hatch_egg_handler,
    "gs_sell_egg": _discard_structure_update(msm_monsters.sell_egg),
    "gs_speed_up_hatching": _discard_structure_update(msm_monsters.speed_up_hatching),
    "gs_viewed_egg": _viewed_egg_handler,
    "gs_viwed_egg": _viewed_egg_handler,
    "gs_claim_hatched_egg": _simple(msm_monsters.claim_hatched_egg),
    "gs_breed_monsters": _simple(msm_monsters.breed_monsters),
    "gs_finish_breeding": _finish_breeding(True),
    "gs_finish_breed_monsters": _finish_breeding(True),
    "gs_finish_breeding_monsters": _finish_breeding(True),
    "gs_finish_breeding_video": _finish_breeding(True),
    "gs_speed_up_breeding": _with_structure_update("gs_speed_up_breeding", msm_monsters.speed_up_breeding),
    "gs_speed_up_breeding_video": _with_structure_update("gs_speed_up_breeding_video", msm_monsters.speed_up_breeding),
    "gs_speedup_breeding": _with_structure_update("gs_speedup_breeding", msm_monsters.speed_up_breeding),
    "gs_speedup_breeding_video": _with_structure_update("gs_speedup_breeding_video", msm_monsters.speed_up_breeding),
    "gs_speedup_breed_monsters": _with_structure_update("gs_speedup_breed_monsters", msm_monsters.speed_up_breeding),
    "gs_speedup_breeding_monsters": _with_structure_update("gs_speedup_breeding_monsters", msm_monsters.speed_up_breeding),
    "gs_cancel_breeding": _simple(msm_monsters.cancel_breeding),
    "gs_remove_breeding": _simple(msm_monsters.cancel_breeding),
    "gs_check_in_monster": _simple(msm_monsters.store_monster),
    "gs_store_monster": _simple(msm_monsters.store_monster),
    "gs_move_monster_to_hotel": _simple(msm_monsters.store_monster),
    "gs_unstore_monster": _simple(msm_monsters.unstore_monster),
    "gs_check_out_monster": _simple(msm_monsters.unstore_monster),
    "gs_move_monster_from_hotel": _simple(msm_monsters.unstore_monster),
    "battle_teleport": _teleport_monster(False),
    "gs_teleport_monster": _teleport_monster(False),
    "gs_teleport": _teleport_monster(False),
    "gs_transpose_monster": _teleport_monster(False),
    "gs_move_monster_to_island": _teleport_monster(False),
    "gs_send_monster_home": _teleport_monster(True),
    "gs_send_to_magical_nexus": _send_to_magical_nexus_handler,
    "gs_send_bonus_for_looking_up_friend_id": _generic_success(),
    "gs_buy_island_skin": _simple(msm_islands.buy_island_skin),
    "gs_activate_island_theme": _simple(msm_islands.activate_island_theme),
    "gs_set_active_island_theme": _simple(msm_islands.activate_island_theme),
    "gs_equip_island_skin": _simple(msm_islands.activate_island_theme),
    "gs_mute_castle": _simple(msm_islands.mute_castle),
    "gs_get_island_boosts": _simple(msm_islands.get_island_boosts),
    "gs_island_boosts": _simple(msm_islands.get_island_boosts),
    "gs_get_island_boost": _simple(msm_islands.get_island_boosts),
    "gs_save_happiness_warnings_status": _generic_success(),
    "gs_collect_daily_reward": _generic_success(["rewards"]),
    "gs_collect_flip_level": _simple(msm_rewards.collect_flip_level),
    "gs_collect_flip_mini_game": _simple(msm_rewards.collect_flip_mini_game),
    "gs_collect_scratch_off": _simple(msm_rewards.collect_scratch_off),
    "gs_create_clubbox": _generic_success(),
    "gs_daily_login_buyback": _generic_success(["rewards"]),
    "gs_delete_mail": _generic_success(),
    "gs_finish_dish_harmonizing": _with_structure_update("gs_finish_dish_harmonizing", msm_structures.finish_dish_harmonizing, always=True),
    "gs_flip_minigame_cost": _simple(msm_rewards.flip_minigame_cost),
    "gs_friend_request_manage": _generic_success(),
    "gs_get_code": _generic_success(),
    "gs_get_friend_visit_data": _generic_success(["friend_data", "islands"]),
    "gs_get_friends": _generic_success(["friends"]),
    "gs_get_island_rank": _simple(msm_islands.get_island_rank),
    "gs_get_messages": _generic_success(["messages"]),
    "gs_get_random_tribes": _generic_success(["tribes"]),
    "gs_get_ranked_island_data": _generic_success(["islands"]),
    "gs_get_top10_island_data": _generic_success(["islands"]),
    "gs_get_torchgifts": _generic_success(["torchgifts"]),
    "gs_handle_facebook_help_instances": _facebook_help_instances_stub,
    "battle_claim_versus_rewards": _battle_claim_versus_rewards,
    "battle_set_music": _battle_set_music,
    "client_keep_alive": _client_keep_alive,
    "metric_event": _metric_event,
    "gs_get_tribal_island_data": _generic_success(["tribe", "members"]),
    "gs_hype_game": _generic_success(),
    "gs_incubate_dish_harmonizer_egg": _generic_success(["egg"]),
    "gs_leave_tribe_request": _generic_success(),
    "gs_light_torch": _generic_success(),
    "gs_place_on_gold_island": _simple(msm_monsters.place_on_gold_island),
    "gs_play_scratch_off": _simple(msm_rewards.play_scratch_off),
    "gs_purchase_scratch_off": _simple(msm_rewards.play_scratch_off),
    "gs_player_has_scratch_off": _simple(msm_rewards.player_has_scratch_off),
    "gs_get_prize_wheel": _simple(msm_rewards.get_prize_wheel),
    "gs_spin_prize_wheel": _simple(msm_rewards.spin_prize_wheel),
    "gs_collect_prize_wheel": _simple(msm_rewards.collect_prize_wheel),
    "gs_get_memory_game_numbers": _simple(msm_rewards.get_memory_game_numbers),
    "gs_player_save_profile": _generic_success(),
    "gs_process_event_cleanup": _generic_success(),
    "gs_box_add_egg": _simple(msm_box.box_monster_command),
    "gs_box_add_monster": _simple(msm_box.box_monster_command),
    "gs_box_monster": _simple(msm_box.box_monster_command),
    "gs_box_purchase_fill": _with_monster_update("gs_box_purchase_fill", msm_box.box_purchase_fill),
    "gs_box_activate_monster": _with_monster_update("gs_box_activate_monster", msm_box.box_activate_monster),
    "gs_activate_box_monster": _with_monster_update("gs_activate_box_monster", msm_box.wake_wubbox),
    "gs_wake_wubbox": _with_monster_update("gs_wake_wubbox", msm_box.wake_wubbox),
    "gs_attempt_early_box_activate": _with_monster_update("gs_attempt_early_box_activate", msm_box.box_purchase_fill),
    "gs_purchase_evolve_unlock": _simple(msm_box.purchase_evolve_unlock),
    "gs_purchase_flip_mini_game": _simple(msm_rewards.purchase_flip_mini_game),
    "gs_rate_island": _generic_success(),
    "gs_refresh_tribe_requests": _generic_success(["requests"]),
    "gs_remove_friend": _generic_success(),
    "gs_save_composer_track": _generic_success(),
    "gs_set_last_timed_theme": _simple(msm_islands.set_last_timed_theme),
    "gs_speedup_dish_harmonizing": _with_structure_update("gs_speedup_dish_harmonizing", msm_structures.speed_up_dish_harmonizing, always=True),
    "gs_start_dish_harmonizing": _with_structure_update("gs_start_dish_harmonizing", msm_structures.start_dish_harmonizing, always=True),
    "gs_tribal_feed_monster": _generic_success(["rewards"]),
    "gs_start_synthesizing": _simple(msm_synthesis.start_synthesizing),
    "gs_speedup_synthesizing": _simple(msm_synthesis.speedup_synthesizing),
    "gs_collect_synthesizing_success": _simple(msm_synthesis.collect_synthesizing),
    "gs_collect_synthesizing_failure": _simple(msm_synthesis.collect_synthesizing),
    "gs_collect_synthesizing": _simple(msm_synthesis.collect_synthesizing),
    "gs_finish_synthesizing": _simple(msm_synthesis.collect_synthesizing),
    "gs_start_attuning": _simple(msm_synthesis.start_attuning),
    "gs_finish_attuning": _simple(msm_synthesis.finish_attuning),
    "gs_speedup_attuning": _simple(msm_synthesis.speedup_attuning),
    "gs_update_reattune_monster": _simple(msm_synthesis.update_reattune_monster),
    "gs_collect_reattune_monster": _simple(msm_synthesis.collect_reattune_monster),
    "gs_viewed_reattuned_monster": _simple(msm_synthesis.collect_reattune_monster),
    "purchase_costume": _costume_action("purchase_costume"),
    "equip_costume": _costume_action("equip_costume"),
    "gs_update_owned_costumes": _simple(msm_monsters.update_owned_costumes),
    "gs_update_properties": _generic_success(),
    "gs_update_sold_monsters": _generic_success(),
    "gs_update_titansoul_rewards": _generic_success(["rewards"]),
    "update_viewed_campaigns": _generic_success(),
    "gs_update_viewed_cards": _generic_success(["viewed_cards", "card_ids"]),
    "gs_open_card_packs": _simple(msm_cardalbum.open_card_packs),
    "gs_buy_card_album_store_item": _simple(msm_cardalbum.buy_card_album_store_item),
    "gs_buy_tile": _simple(msm_structures.buy_tile),
    "gs_save_paintstate": _simple(msm_structures.save_paintstate),
    "update_awakener": _simple(msm_structures.update_awakener),
    "gs_collect_card_album_rewards": _simple(msm_cardalbum.collect_card_album_rewards),
    "gs_collect_card_album_page_rewards": _simple(msm_cardalbum.collect_card_album_page_rewards),
    "card_album_reward_collect": _simple(msm_cardalbum.collect_card_album_rewards),
    "card_album_page_reward_collect": _simple(msm_cardalbum.collect_card_album_page_rewards),
    "gs_collect_rewards": _simple(msm_rewardtracks.collect_rewards),
    "gs_multi_neighbors": _generic_success(["neighbors"]),
    "gs_viewed_cruc_unlock": _generic_success(),
}
def handle_login(params):
    username = None
    for key in ("user_game_id", "username", "user_id", "bbb_id", "u"):
        if params.get(key):
            username = str(params[key])
            break
    return [("USER_LOGIN", {"data": {}, "success": True, "user": username or DEFAULT_USERNAME})]
def login_bootstrap_frames():
    frames = []
    game_settings = load_db_json("game_settings")
    if game_settings is not None:
        frames.append(("game_settings", dict(game_settings)))
    gs_initialized = load_db_json("gs_initialized")
    if gs_initialized is not None:
        frames.append(("gs_initialized", normalize_db_payload("gs_initialized", dict(gs_initialized))))
    frames.append(("gs_display_generic_message", {"force_logout": False, "msg": "Welcome to NPS!"}))
    return frames
def handle_command(command, params):
    if command == "alive":
        return []
    if command == "USER_LOGIN":
        return handle_login(params)
    aliased_command = _STATIC_ALIAS_RESPONSES.get(command)
    if aliased_command is not None:
        data = load_db_json(aliased_command)
        if data is None:
            logger.info("no captured response for %s (via %s)", command, aliased_command)
            return []
        return [(aliased_command, normalize_db_payload(aliased_command, dict(data)))]
    handler = GAMEPLAY_HANDLERS.get(command)
    if handler is not None:
        try:
            result = handler(DEFAULT_USERNAME, params)
        except Exception:
            logger.exception("handler for %s raised", command)
            return []
        if result is None:
            logger.info("handler for %s had nothing to answer", command)
            return []
        if isinstance(result, list):
            return result
        return [(command, result)]
    data = load_db_json(command)
    if data is None:
        logger.info("no captured response for %s", command)
        if "cruc" in command.lower() or "card" in command.lower():
            return [(command, {"success": True})]
        return []
    frames = [(command, normalize_db_payload(command, dict(data)))]
    for i in range(2, 10):
        chained = load_db_json(f"{command}_{i}")
        if chained is None:
            break
        frames.append((command, normalize_db_payload(command, dict(chained))))
    return frames
