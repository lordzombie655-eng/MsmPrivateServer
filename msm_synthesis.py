import time
from msm_playerdata import SFSLong, create_player_properties, find_island_by_structure, load_player, save_player
from msm_structures import _structure_update
def repair_glitched_synthesis(island):
    synthesizing = island.get("synthesizing")
    if not synthesizing:
        return
    valid_ids = {s.get("structure", s.get("structure_id")) for s in (island.get("structures") or []) if s}
    island["synthesizing"] = [s for s in synthesizing if s and s.get("structure") in valid_ids]
_WORKSHOP_MONSTER_FOR_GENES = {
    "GJK": 682, "GJM": 683, "GKM": 684, "GJL": 685, "GKL": 686, "GLM": 736,
    "JKL": 737, "JKM": 757, "JLM": 777, "KLM": 796, "GJKL": 708, "GJKM": 758,
    "GJLM": 778, "GKLM": 798, "JKLM": 807, "GJKLM": 710,
}
def _workshop_monster_for_genes(genes):
    normalized = "".join(sorted((genes or "").strip().upper()))
    return _WORKSHOP_MONSTER_FOR_GENES.get(normalized, 682)
def _workshop_synthesis_duration_ms(genes):
    count = len((genes or "").strip())
    if count >= 5:
        return 7200000
    if count == 4:
        return 3600000
    return 1800000
def _find_island_with_structure_or_synthesizing(player_object, structure_id):
    if structure_id:
        island, _ = find_island_by_structure(player_object, structure_id)
        if island is not None:
            return island
    for island in player_object.get("islands") or []:
        if island is not None and island.get("synthesizing"):
            return island
    return None
def _synth_structure_id(params):
    return (params.get("user_structure_id") or params.get("structure_id")
            or params.get("synthesizer_id") or params.get("id") or 0)
def start_synthesizing(username, params):
    structure_id = _synth_structure_id(params)
    genes = (params.get("genes") or "").strip().upper()
    root, player_object = load_player(username)
    island = _find_island_with_structure_or_synthesizing(player_object, structure_id)
    result = {"success": True, "user_structure_id": SFSLong(structure_id)}
    if island is None:
        result["properties"] = create_player_properties(player_object)
        return result
    now = int(time.time() * 1000)
    complete_on = now + _workshop_synthesis_duration_ms(genes)
    monster_id = _workshop_monster_for_genes(genes)
    synthesis = {
        "used_critters": [{"gene": g, "num": 1} for g in genes],
        "started_on": SFSLong(now), "success": False, "failed": False,
        "failure_chance": 0, "chance_of_failure": 0,
        "complete_on": SFSLong(complete_on), "structure": SFSLong(structure_id), "monster": monster_id,
    }
    synthesizing = island.setdefault("synthesizing", [])
    synthesizing.append(synthesis)
    last_synthesis = {"genes": genes, "structure": SFSLong(structure_id)}
    island["last_synthesis"] = [last_synthesis]
    save_player(username, root)
    result.update({
        "last_synthesis": last_synthesis, "started_on": SFSLong(now), "complete_on": SFSLong(complete_on),
        "user_synthesizing_data": synthesis, "properties": create_player_properties(player_object),
    })
    return result
def speedup_synthesizing(username, params):
    structure_id = _synth_structure_id(params)
    root, player_object = load_player(username)
    island = _find_island_with_structure_or_synthesizing(player_object, structure_id)
    now = int(time.time() * 1000)
    result = {"success": True, "user_structure_id": SFSLong(structure_id)}
    if island is not None:
        synthesizing = island.setdefault("synthesizing", [])
        matched = next((s for s in synthesizing if s is not None and s.get("structure") == structure_id), None)
        if matched is not None:
            matched.update({"complete_on": SFSLong(now), "success": True, "failed": False,
                            "failure_chance": 0, "chance_of_failure": 0})
            result["started_on"] = matched.get("started_on", SFSLong(now - 3600000))
            result["user_synthesizing_data"] = matched
        else:
            started = now - 3600000
            result["started_on"] = SFSLong(started)
            result["user_synthesizing_data"] = {
                "structure": SFSLong(structure_id), "started_on": SFSLong(started), "complete_on": SFSLong(now),
                "success": True, "failed": False, "failure_chance": 0, "chance_of_failure": 0,
            }
        result["complete_on"] = SFSLong(now)
        save_player(username, root)
    result["properties"] = create_player_properties(player_object)
    return result
def collect_synthesizing(username, params):
    structure_id = _synth_structure_id(params)
    genes = (params.get("genes") or "").strip().upper()
    root, player_object = load_player(username)
    island = _find_island_with_structure_or_synthesizing(player_object, structure_id)
    reattuned = []
    if island is not None:
        synthesizing = island.setdefault("synthesizing", [])
        for i in range(len(synthesizing) - 1, -1, -1):
            synthesis = synthesizing[i]
            if synthesis is not None and synthesis.get("structure") == structure_id:
                reattuned.extend(synthesis.get("used_critters") or [])
                del synthesizing[i]
                break
        save_player(username, root)
    if not reattuned:
        reattuned = [{"gene": (genes[:1] if genes else "G"), "num": max(1, len(genes))}]
    return {
        "success": True, "user_structure_id": SFSLong(structure_id),
        "reattuned_critters": reattuned, "properties": create_player_properties(player_object),
    }
_ATTUNING_DURATION_MS = 18000000
def _attune_structure_id(params):
    return params.get("user_structure_id") or params.get("structure_id") or params.get("structure") or 0
def start_attuning(username, params):
    structure_id = _attune_structure_id(params)
    end_gene = params.get("end_gene") or params.get("gene") or params.get("genes") or ""
    root, player_object = load_player(username)
    island, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    now = int(time.time() * 1000)
    complete_on = now + _ATTUNING_DURATION_MS
    attuning_data = {
        "reattuned_monster": 0, "started_on": SFSLong(now), "start_gene": "",
        "complete_on": SFSLong(complete_on), "end_gene": end_gene, "structure": SFSLong(structure_id),
    }
    result = {
        "success": True, "user_structure_id": SFSLong(structure_id), "structure_id": SFSLong(structure_id),
        "started_on": SFSLong(now), "complete_on": SFSLong(complete_on),
        "time_remaining": SFSLong(_ATTUNING_DURATION_MS), "seconds_remaining": SFSLong(_ATTUNING_DURATION_MS // 1000),
        "user_attuning_data": attuning_data,
    }
    if structure is not None:
        structure.update({
            "active": True, "is_active": True, "in_use": True, "is_processing": True, "is_attuning": True,
            "collectable": False, "ready": False, "obj_data": 1, "obj_end": complete_on,
            "started_on": now, "startTime": now, "complete_on": complete_on,
            "finishing_time": complete_on, "finished_at": complete_on,
            "seconds_remaining": _ATTUNING_DURATION_MS // 1000, "time_remaining": _ATTUNING_DURATION_MS,
            "end_gene": end_gene, "genes": end_gene, "user_attuning_data": attuning_data,
            "attuner_gene_granted": False,
        })
        save_player(username, root)
        result["updated_structure"] = _structure_update(structure, "full")
    result["properties"] = create_player_properties(player_object)
    return result
def _grant_attuner_gene(player_object, island, gene):
    gene = (gene or "").strip().upper()[:1] or "J"
    genes = player_object.setdefault("attuner_genes", {})
    genes[gene] = (genes.get(gene, 0) or 0) + 1
    player_object["attunerGenes"] = genes
    player_object["genes"] = genes
    gene_inventory = [{"gene": g, "letter": g, "amount": genes.get(g, 0), "count": genes.get(g, 0)}
                       for g in ("G", "J", "K", "L", "M")]
    player_object["attuner_gene_inventory"] = gene_inventory
    player_object["attunerGenesData"] = gene_inventory
    player_object["meebs"] = gene_inventory
    if island is not None:
        critters = island.setdefault("attuned_critters", [])
        match = next((e for e in critters if e is not None
                      and (e.get("gene") or e.get("critterGene", "")).upper() == gene), None)
        if match is None:
            match = {"gene": gene, "critterGene": gene, "amount": 0, "count": 0, "num": 0}
            critters.append(match)
        count = max(0, match.get("count", 0) or 0) + 1
        match["amount"] = count
        match["count"] = count
        match["num"] = count
        island["reattuned_critters"] = critters
        island.setdefault("used_critters", [])
    return gene
def _finish_attuning_and_grant_gene(username, structure_id, requested_gene):
    root, player_object = load_player(username)
    island, structure = find_island_by_structure(player_object, structure_id) if structure_id else (None, None)
    gene = requested_gene
    if not gene and structure is not None:
        gene = structure.get("end_gene") or structure.get("genes") or (structure.get("user_attuning_data") or {}).get("end_gene", "")
    gene = (gene or "J").strip().upper()[:1]
    already_granted = bool(structure.get("attuner_gene_granted")) if structure is not None else False
    if not already_granted:
        gene = _grant_attuner_gene(player_object, island, gene)
    if structure is not None:
        structure.update({
            "active": False, "is_active": False, "in_use": False, "is_processing": False, "is_attuning": False,
            "collectable": False, "can_collect": False, "ready": False, "ready_to_collect": False,
            "obj_data": 0, "obj_end": 0, "started_on": 0, "startTime": 0, "complete_on": 0,
            "finishing_time": 0, "finished_at": 0, "seconds_remaining": 0, "time_remaining": 0,
            "attuner_gene_granted": False,
        })
    save_player(username, root)
    return player_object, structure, gene
def _attuning_ack(started, finished, structure_id, structure_update=None, player_object=None):
    now = int(time.time() * 1000)
    complete_on = now + _ATTUNING_DURATION_MS if started else 0
    result = {
        "success": True, "active": started and not finished, "is_active": started and not finished,
        "in_use": started and not finished, "is_processing": started and not finished,
        "is_attuning": started and not finished,
        "collectable": finished, "can_collect": finished, "ready": finished, "ready_to_collect": finished,
        "started_on": SFSLong(now if started else 0), "complete_on": SFSLong(complete_on),
        "finishing_time": SFSLong(complete_on), "finished_at": SFSLong(complete_on),
        "seconds_remaining": SFSLong(18000 if started else 0),
        "time_remaining": SFSLong(_ATTUNING_DURATION_MS if started else 0),
        "state": 1 if started else (2 if finished else 0),
        "status": 1 if started else (2 if finished else 0),
        "gene_results": [], "monster_results": [], "monster_targets": [],
    }
    if structure_id:
        result["structure_id"] = SFSLong(structure_id)
        result["user_structure_id"] = SFSLong(structure_id)
    if structure_update is not None:
        result["updated_structure"] = structure_update
    if player_object is not None:
        result["properties"] = create_player_properties(player_object)
    return result
def finish_attuning(username, params):
    structure_id = _attune_structure_id(params)
    gene = params.get("end_gene") or params.get("gene") or params.get("genes") or ""
    player_object, structure, resolved_gene = _finish_attuning_and_grant_gene(username, structure_id, gene)
    result = _attuning_ack(False, True, structure_id,
                           _structure_update(structure, "full") if structure is not None else None, player_object)
    result["end_gene"] = resolved_gene
    result["genes"] = resolved_gene
    return result
def collect_reattune_monster(username, params):
    return finish_attuning(username, params)
def speedup_attuning(username, params):
    structure_id = _attune_structure_id(params)
    _, player_object = load_player(username)
    return _attuning_ack(True, False, structure_id, None, player_object)
def update_reattune_monster(username, params):
    structure_id = _attune_structure_id(params)
    _, player_object = load_player(username)
    return _attuning_ack(True, False, structure_id, None, player_object)
