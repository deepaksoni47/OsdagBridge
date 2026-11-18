import math
from collections import defaultdict


GROUP_KEYS = [
    "transverse_slab",
    "longitudinal_members",
    "transverse_members",
    "exterior_main_beam_1",
    "exterior_main_beam_2"
]


# ---------------- KEEP DEFINITIONS ---------------- #

FORCE_KEEP = {
    "Mx_i", "Mx_j",
    "My_i", "My_j",
    "Mz_i", "Mz_j",
    "Vx_i", "Vx_j",
    "Vy_i", "Vy_j",
    "Vz_i", "Vz_j"
}

DISP_KEEP = {
    "theta_x", "theta_y", "theta_z",
    "x", "y", "z"
}


# ---------------- CHAIN BUILD ---------------- #

def build_chains(member_ids, members_dict):

    member_ids = [str(m) for m in member_ids]

    conn = {
        m: members_dict[m]
        for m in member_ids
        if m in members_dict
    }

    i_map = {}
    for m, (i, j) in conn.items():
        i_map.setdefault(str(i), []).append(m)

    visited = set()
    chains = []

    for m in member_ids:

        if m in visited or m not in conn:
            continue

        chain = [m]
        visited.add(m)

        cur = m

        while True:
            _, j = conn[cur]
            j = str(j)

            nxt = None
            for nm in i_map.get(j, []):
                if nm not in visited:
                    nxt = nm
                    break

            if not nxt:
                break

            chain.append(nxt)
            visited.add(nxt)
            cur = nxt

        chains.append(chain)

    return chains


# ---------------- MIDPOINT (CURVED SAFE) ---------------- #

def compute_mid_coords(chain, members_dict, node_coords):

    nodes = []

    for m in chain:
        i, j = members_dict[m]
        nodes.append(str(i))
        nodes.append(str(j))

    seen = set()
    ordered = []

    for n in nodes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    segs = []
    lengths = []

    for i in range(len(ordered) - 1):

        a = node_coords.get(ordered[i])
        b = node_coords.get(ordered[i + 1])

        if not a or not b:
            continue

        dx = b[0] - a[0]
        dy = b[1] - a[1]
        dz = b[2] - a[2]

        L = math.sqrt(dx*dx + dy*dy + dz*dz)

        segs.append((a, b, L))
        lengths.append(L)

    total = sum(lengths)
    if total == 0:
        return None

    target = total / 2
    acc = 0

    for a, b, L in segs:

        if acc + L >= target:

            t = (target - acc) / L if L != 0 else 0

            return {
                "coords": [
                    a[0] + t * (b[0] - a[0]),
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2])
                ]
            }

        acc += L

    return None


# ---------------- CLEAN FORCES ---------------- #

def clean_forces(forces_dict):

    # Lazy tables (LazyLoadcaseResults, a Mapping rather than a dict) apply the
    # FORCE_KEEP whitelist during materialization — nothing to strip, and
    # mutating them here would be lost on LRU eviction anyway.
    if not isinstance(forces_dict, dict):
        return

    for loadcase in forces_dict.values():
        for _, values in loadcase.items():
            for k in list(values.keys()):
                if k not in FORCE_KEEP:
                    values.pop(k, None)


# ---------------- CLEAN DISPLACEMENTS ---------------- #

def clean_displacements(disp_dict):

    # See clean_forces: lazy tables whitelist during materialization.
    if not isinstance(disp_dict, dict):
        return

    for loadcase in disp_dict.values():
        for _, values in loadcase.items():
            for k in list(values.keys()):
                if k not in DISP_KEEP:
                    values.pop(k, None)


# ---------------- COMPONENTS ---------------- #

def rebuild_components(data):

    data["force_components"] = list(FORCE_KEEP)
    data["disp_components"] = list(DISP_KEEP)


# ---------------- FIX LONGITUDINAL INPUT ---------------- #

def extract_longitudinal_ids(data):

    raw = data.get("longitudinal_members", [])

    ids = set()

    for item in raw:
        if isinstance(item, dict):
            ids.update(item.get("members", []))
        else:
            ids.add(item)

    return ids


# ---------------- GIRDER LOGIC ---------------- #

def _girder_nodes(member_list, members_dict) -> list:
    """Sorted list of all unique node tags belonging to a girder's members."""
    nodes: set = set()
    for m in member_list:
        n1, n2 = members_dict[str(m)]
        nodes.add(n1)
        nodes.add(n2)
    return sorted(nodes)


def merge_chains(chains, members_dict, node_coords):
    all_members = []
    for ch in chains:
        all_members.extend(ch["members"])
    return {
        "members": all_members,
        "nodes":   _girder_nodes(all_members, members_dict),
        "start":   chains[0]["start"],
        "end":     chains[-1]["end"],
        "mid":     compute_mid_coords(all_members, members_dict, node_coords),
    }


def build_girders(data):

    beam1_chains = data.get("exterior_main_beam_1", [])
    beam2_chains = data.get("exterior_main_beam_2", [])
    longitudinal_chains = data.get("longitudinal_members", [])

    if not beam1_chains or not beam2_chains:
        return {}

    members_dict = {str(k): v for k, v in data["members"].items()}
    node_coords  = {str(k): v for k, v in data["nodes"].items()}

    # Reference transverse vector: middle chain midpoint of each exterior beam.
    # Projecting any chain's midpoint onto this vector gives its normalised
    # transverse position: 0 = on beam1, 1 = on beam2, (0,1) = interior.
    p1 = beam1_chains[len(beam1_chains) // 2]["mid"]["coords"]
    p2 = beam2_chains[len(beam2_chains) // 2]["mid"]["coords"]

    dx = p2[0] - p1[0]
    dz = p2[2] - p1[2]
    len2 = dx*dx + dz*dz

    if len2 == 0:
        return {}

    def transverse_s(chain_dict):
        mid = chain_dict.get("mid")
        if not mid:
            return None
        mx, _, mz = mid["coords"]
        return ((mx - p1[0]) * dx + (mz - p1[2]) * dz) / len2

    # Keep only chains whose midpoint falls strictly between the two exterior beams.
    # Rejects cantilever/overhang members (s ≤ 0 or s ≥ 1) regardless of
    # length or direction; works for curved girders too.
    interior = []
    for chain_dict in longitudinal_chains:
        s = transverse_s(chain_dict)
        if s is not None and 0.0 < s < 1.0:
            interior.append((s, chain_dict))

    interior.sort(key=lambda x: x[0])

    # G1 = exterior beam 1, G2…G(n-1) = interior (sorted beam1→beam2), Gn = exterior beam 2
    girders = {}
    girders["G1"] = {**merge_chains(beam1_chains, members_dict, node_coords), "type": "exterior", "index": 1}

    for idx, (_, chain_dict) in enumerate(interior, start=2):
        girders[f"G{idx}"] = {
            **chain_dict,
            "nodes": _girder_nodes(chain_dict["members"], members_dict),
            "type":  "interior",
            "index": idx,
        }

    n = len(interior) + 2
    girders[f"G{n}"] = {**merge_chains(beam2_chains, members_dict, node_coords), "type": "exterior", "index": n}

    return girders


def attach_girders(data):
    data["girders"] = build_girders(data)


# ---------------- CROSSBRACINGS ---------------- #

def build_crossbracings(member_ids, members_dict, node_coords, girders):
    # Build node set per girder for fast lookup (uses pre-built girder["nodes"])
    girder_node_sets: dict = {
        g_name: set(g_data.get("nodes", []))
        for g_name, g_data in girders.items()
    }

    def _find_girder(node) -> str | None:
        for g_name, node_set in girder_node_sets.items():
            if node in node_set:
                return g_name
        return None

    # Each transverse member is a single cross-bracing element between two
    # adjacent longitudinal lines. Do NOT chain them — the full cross-section
    # chain runs edge→G1→…→Gn→edge, so chaining would make the endpoints
    # land on edge-beam nodes that are not in any girder set.
    enriched = []
    for m in [str(m) for m in member_ids]:
        if m not in members_dict:
            continue

        n1, n2 = members_dict[m]

        girder_1 = _find_girder(n1)
        girder_2 = _find_girder(n2)

        # Silently skip members whose endpoints touch edge beams or other
        # non-girder elements — these are slab overhangs, not cross-bracings.
        if girder_1 is None or girder_2 is None:
            continue

        # Assign left/right by girder index (lower index = left)
        idx_1 = girders[girder_1].get("index", 0)
        idx_2 = girders[girder_2].get("index", 0)
        if idx_1 <= idx_2:
            left_girder, right_girder = girder_1, girder_2
            n_left, n_right = n1, n2
        else:
            left_girder, right_girder = girder_2, girder_1
            n_left, n_right = n2, n1

        start = {
            "node":   n_left,
            "coords": list(node_coords[str(n_left)])  if str(n_left)  in node_coords else None,
        }
        end = {
            "node":   n_right,
            "coords": list(node_coords[str(n_right)]) if str(n_right) in node_coords else None,
        }
        mid = compute_mid_coords([m], members_dict, node_coords)

        enriched.append({
            "members":      [m],
            "start":        start,
            "end":          end,
            "mid":          mid,
            "left_girder":  left_girder,
            "right_girder": right_girder,
        })

    return enriched


def attach_crossbracings(data, member_ids, members_dict, node_coords):
    data["crossbracings"] = build_crossbracings(
        member_ids, members_dict, node_coords, data.get("girders", {})
    )


# ---------------- END DIAPHRAGMS & INTERMEDIATE CROSS BRACINGS ---------------- #

def build_end_diaphragms(start_edge_ids, end_edge_ids, members_dict, node_coords, girders=None):
    """
    Build ordered polyline structures for Start and End Diaphragms.
    Each diaphragm chains its constituent elements across the bridge width
    sorted by transverse coordinate Z (ascending).
    """
    diaphragms = {}

    for name, raw_ids in [
        ("Start Diaphragm", start_edge_ids),
        ("End Diaphragm", end_edge_ids),
    ]:
        elem_info = []
        for m in [str(x) for x in (raw_ids or [])]:
            if m not in members_dict:
                continue
            n1, n2 = members_dict[m]
            c1 = node_coords.get(str(n1))
            c2 = node_coords.get(str(n2))
            if not c1 or not c2:
                continue
            mz = (c1[2] + c2[2]) / 2.0
            mx = (c1[0] + c2[0]) / 2.0
            n_left = n1 if c1[2] <= c2[2] else n2
            n_right = n2 if c1[2] <= c2[2] else n1
            elem_info.append((mz, mx, int(m), n_left, n_right))

        if not elem_info:
            continue

        elem_info.sort(key=lambda it: it[0])

        members_ordered = [it[2] for it in elem_info]
        station_x = round(sum(it[1] for it in elem_info) / len(elem_info), 3)

        nodes_ordered = []
        for _, _, _, nl, nr in elem_info:
            if not nodes_ordered:
                nodes_ordered.append(nl)
            nodes_ordered.append(nr)

        diaphragms[name] = {
            "name": name,
            "station_x": station_x,
            "members": members_ordered,
            "nodes": nodes_ordered,
            "type": "end_diaphragm",
        }

    return diaphragms


def build_intermediate_cross_bracings(cb_raw_ids, members_dict, node_coords, girders=None):
    """
    Build ordered polyline structures for Intermediate Cross Bracings.
    Groups transverse elements by longitudinal station X and orders constituent
    elements across the bridge width (ascending Z) connecting the girders across bays.
    """
    girder_node_sets = {}
    if girders:
        girder_node_sets = {
            g_name: set(g_data.get("nodes", []))
            for g_name, g_data in girders.items()
        }

    def _find_girder(node):
        for g_name, node_set in girder_node_sets.items():
            if node in node_set:
                return g_name
        return None

    elems_by_station = defaultdict(list)

    for m in [str(x) for x in (cb_raw_ids or [])]:
        if m not in members_dict:
            continue
        n1, n2 = members_dict[m]

        if girder_node_sets:
            g1 = _find_girder(n1)
            g2 = _find_girder(n2)
            if g1 is None or g2 is None:
                continue  # skip slab overhangs

        c1 = node_coords.get(str(n1))
        c2 = node_coords.get(str(n2))
        if not c1 or not c2:
            continue

        mx = round((c1[0] + c2[0]) / 2.0, 3)
        mz = (c1[2] + c2[2]) / 2.0
        n_left = n1 if c1[2] <= c2[2] else n2
        n_right = n2 if c1[2] <= c2[2] else n1

        elems_by_station[mx].append((mz, int(m), n_left, n_right))

    stations_sorted = sorted(elems_by_station.keys())
    icb = {}

    for idx, st_x in enumerate(stations_sorted, start=1):
        items = elems_by_station[st_x]
        items.sort(key=lambda it: it[0])

        members_ordered = [it[1] for it in items]
        nodes_ordered = []
        for _, _, nl, nr in items:
            if not nodes_ordered:
                nodes_ordered.append(nl)
            nodes_ordered.append(nr)

        key = f"CB{idx}"
        icb[key] = {
            "name": f"Cross Bracing {idx} (x={st_x:.2f}m)",
            "station_x": st_x,
            "members": members_ordered,
            "nodes": nodes_ordered,
            "type": "cross_bracing",
            "index": idx,
        }

    return icb


# ---------------- POST PROCESS ---------------- #

OUTPUT_KEYS = [
    "nodes",
    "members",
    "loadcases",
    "transverse_slab",
    "longitudinal_members",
    "transverse_members",
    "girders",
    "crossbracings",
    "end_diaphragms",
    "intermediate_cross_bracings",
    "longitudinal_element_tags",
    "transverse_element_tags",
    "forces",
    "displacements",
    "force_components",
    "disp_components",
]


def post_process(data: dict) -> dict:

    members_dict = {str(k): v for k, v in data["members"].items()}
    node_coords = {str(k): v for k, v in data["nodes"].items()}

    # Capture raw group IDs before the loop pops them
    groups = data.get("groups", {})
    cb_raw_ids = (
        groups.get("transverse_slab")
        or data.get("transverse_slab")
        or []
    )
    start_edge_ids = (
        groups.get("start_edge")
        or data.get("start_edge")
        or []
    )
    end_edge_ids = (
        groups.get("end_edge")
        or data.get("end_edge")
        or []
    )

    # Classify element tags strictly geometrically
    longitudinal_tags = set()
    transverse_tags = set()
    for m_id, (n1, n2) in members_dict.items():
        c1 = node_coords.get(str(n1))
        c2 = node_coords.get(str(n2))
        if not c1 or not c2:
            continue
        if abs(c1[2] - c2[2]) < 1e-3 and abs(c1[1] - c2[1]) < 1e-3:
            longitudinal_tags.add(int(m_id))
        elif abs(c1[0] - c2[0]) < 1e-3:
            transverse_tags.add(int(m_id))
        else:
            dx = abs(c1[0] - c2[0])
            dz = abs(c1[2] - c2[2])
            if dz < dx:
                longitudinal_tags.add(int(m_id))
            else:
                transverse_tags.add(int(m_id))

    data["longitudinal_element_tags"] = sorted(longitudinal_tags)
    data["transverse_element_tags"] = sorted(transverse_tags)

    # If start/end edge IDs weren't captured via groups, derive them from transverse elements
    if not start_edge_ids or not end_edge_ids:
        tv_by_station = defaultdict(list)
        for tid in transverse_tags:
            n1, n2 = members_dict[str(tid)]
            c1, c2 = node_coords[str(n1)], node_coords[str(n2)]
            mx = round((c1[0] + c2[0]) / 2.0, 3)
            tv_by_station[mx].append(tid)
        st_sorted = sorted(tv_by_station.keys())
        if st_sorted:
            if not start_edge_ids:
                start_edge_ids = tv_by_station[st_sorted[0]]
            if not end_edge_ids and len(st_sorted) > 1:
                end_edge_ids = tv_by_station[st_sorted[-1]]
            if not cb_raw_ids and len(st_sorted) > 2:
                for st in st_sorted[1:-1]:
                    cb_raw_ids.extend(tv_by_station[st])

    for group in GROUP_KEYS:

        member_ids = None

        if group in data:
            member_ids = data.pop(group)

        elif "groups" in data and group in data["groups"]:
            member_ids = data["groups"].pop(group)

        if not member_ids:
            continue

        chains = build_chains(member_ids, members_dict)

        enriched = []

        for ch in chains:

            start = compute_mid_coords([ch[0]], members_dict, node_coords)
            end = compute_mid_coords([ch[-1]], members_dict, node_coords)
            mid = compute_mid_coords(ch, members_dict, node_coords)

            enriched.append({
                "members": ch,
                "start": start,
                "end": end,
                "mid": mid
            })

        data[group] = enriched

    if "forces" in data:
        clean_forces(data["forces"])

    if "displacements" in data:
        clean_displacements(data["displacements"])

    rebuild_components(data)
    attach_girders(data)
    attach_crossbracings(data, cb_raw_ids, members_dict, node_coords)

    # Attach enhanced transverse structures
    data["end_diaphragms"] = build_end_diaphragms(
        start_edge_ids, end_edge_ids, members_dict, node_coords, data.get("girders")
    )
    data["intermediate_cross_bracings"] = build_intermediate_cross_bracings(
        cb_raw_ids, members_dict, node_coords, data.get("girders")
    )

    return {k: data[k] for k in OUTPUT_KEYS if k in data}