//! Scene normalization ported from the Python adapter and rmscene CRDT ordering.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
type Id = (u64, u64);
const ROOT: Id = (0, 1);
const ZERO: Id = (0, 0);
const IDENTITY: [f64; 6] = [1., 0., 0., 1., 0., 0.];
const HEURISTIC:&str="root text anchor positions calibrated against the five-page paired native PDF fixture (initial natural anchor study; heuristic, not a general text layout)";
fn id(v: &Value) -> Id {
    (
        v["part1"].as_u64().unwrap_or(0),
        v["part2"].as_u64().unwrap_or(0),
    )
}
fn ij(i: Id) -> Value {
    json!({"part1":i.0,"part2":i.1})
}
fn istr(i: Id) -> String {
    format!("{}:{}", i.0, i.1)
}
fn pyid(i: Id) -> String {
    format!("CrdtId({}, {})", i.0, i.1)
}
fn strip(v: &Value) -> Value {
    if v.get("part1").is_some() && v.get("part2").is_some() {
        ij(id(v))
    } else {
        match v {
            Value::Array(a) => Value::Array(a.iter().map(strip).collect()),
            Value::Object(o) => {
                Value::Object(o.iter().map(|(k, v)| (k.clone(), strip(v))).collect())
            }
            _ => v.clone(),
        }
    }
}
fn num(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.)
}
fn transform(x: f64, y: f64, resolved: bool, evidence: String, anchors: Vec<Value>) -> Value {
    json!({"matrix":[1.,0.,0.,1.,x,y],"resolved":resolved,"evidence":evidence,"anchor_ids":anchors})
}
fn identity(evidence: &str) -> Value {
    transform(0., 0., true, evidence.into(), vec![])
}
fn scene_order(item: &Value, index: usize) -> Value {
    json!({"item_id":strip(&item["item_id"]),"left_id":strip(&item["left_id"]),"right_id":strip(&item["right_id"]),"deleted_length":item["deleted_length"],"block_index":index})
}
fn valid_id(v: &Value) -> bool {
    v["part1"].as_u64().is_some() && v["part2"].as_u64().is_some()
}
fn finite(v: &Value) -> bool {
    v.as_f64().is_some_and(f64::is_finite)
}
fn valid_item(v: &Value) -> bool {
    ["item_id", "left_id", "right_id"]
        .iter()
        .all(|k| valid_id(&v[*k]))
        && v["deleted_length"].as_u64().is_some()
}
fn validate_blocks(blocks: &[Value]) -> Result<(), String> {
    if blocks.len() > 100_000 {
        return Err("Block count exceeds normalization limit".into());
    }
    let mut total_points = 0;
    for block in blocks {
        let kind = block["type"].as_u64().ok_or("Invalid block type")?;
        if block["unreadable"] == true {
            continue;
        }
        let f = &block["fields"];
        let valid = match kind {
            1 => ["tree_id", "node_id", "parent_id"]
                .iter()
                .all(|k| valid_id(&f[*k])),
            2 => {
                let g = &f["group"];
                valid_id(&g["node_id"])
                    && g["visible"]["value"].is_boolean()
                    && g["label"]["value"].is_string()
                    && (g["anchor_id"].is_null() || valid_id(&g["anchor_id"]["value"]))
                    && ["anchor_origin_x", "anchor_threshold"]
                        .iter()
                        .all(|k| g[*k].is_null() || finite(&g[*k]["value"]))
                    && (g["anchor_type"].is_null() || g["anchor_type"]["value"].as_u64().is_some())
            }
            3..=6 | 8 => valid_id(&f["parent_id"]) && valid_item(&f["item"]),
            7 => {
                let t = &f["value"];
                finite(&t["pos_y"])
                    && t["items"]
                        .as_array()
                        .is_some_and(|a| a.iter().all(valid_item))
                    && t["styles"].is_object()
            }
            13 => {
                f["paper_size"].is_null()
                    || f["paper_size"].as_array().is_some_and(|a| {
                        a.len() == 2 && a.iter().all(|v| v.as_u64().is_some_and(|n| n > 0))
                    })
            }
            _ => true,
        };
        if !valid {
            return Err(format!("Invalid decoded geometry in block {kind}"));
        }
        let value = &f["item"]["value"];
        if kind == 4 && !value.is_null() && !valid_id(value) {
            return Err("Invalid scene group identifier".into());
        }
        if kind == 5 && !value.is_null() {
            if value["tool"]["code"].as_u64().is_none()
                || value["color"]["code"].as_u64().is_none()
                || !finite(&value["thickness_scale"])
                || !finite(&value["starting_length"])
            {
                return Err("Invalid decoded line metadata".into());
            }
            let points = value["points"]
                .as_array()
                .ok_or("Invalid decoded line points")?;
            total_points += points.len();
            if total_points > 1_000_000 {
                return Err("Point count exceeds normalization limit".into());
            }
            if points.iter().any(|p| {
                ["x", "y", "pressure", "speed", "direction", "width"]
                    .iter()
                    .any(|k| !finite(&p[*k]))
            }) {
                return Err("Invalid decoded point channel".into());
            }
        }
    }
    Ok(())
}
/// Deterministic Kahn sort, matching rmscene's higher-author-first concurrent inserts.
fn ordered(items: &[Value]) -> Result<Vec<Id>, String> {
    let mut map = BTreeMap::new();
    for item in items {
        map.insert(id(&item["item_id"]), item);
    }
    if map.is_empty() {
        return Ok(vec![]);
    }
    // Synthetic start/end nodes cannot collide with CRDT identifiers.
    let start = (0i8, 0u64, 0u64);
    let end = (2, 0, 0);
    let key = |i: Id| (1, u64::MAX - i.0, i.1);
    let mut degree: BTreeMap<(i8, u64, u64), usize> = BTreeMap::new();
    let mut edges: BTreeMap<_, Vec<_>> = BTreeMap::new();
    degree.insert(start, 0);
    degree.insert(end, 0);
    for (&i, item) in &map {
        let k = key(i);
        let l = id(&item["left_id"]);
        let r = id(&item["right_id"]);
        let l = if l == ZERO || !map.contains_key(&l) {
            start
        } else {
            key(l)
        };
        let r = if r == ZERO || !map.contains_key(&r) {
            end
        } else {
            key(r)
        };
        *degree.entry(k).or_default() += 1;
        *degree.entry(r).or_default() += 1;
        edges.entry(l).or_default().push(k);
        edges.entry(k).or_default().push(r);
    }
    let mut ready: BTreeSet<_> = degree
        .iter()
        .filter(|(_, n)| **n == 0)
        .map(|(k, _)| *k)
        .collect();
    let mut result = vec![];
    while let Some(k) = ready.pop_first() {
        if k.0 == 1 {
            result.push((u64::MAX - k.1, k.2));
        }
        if k == end {
            break;
        }
        for d in edges.get(&k).into_iter().flatten() {
            let n = degree.get_mut(d).unwrap();
            *n -= 1;
            if *n == 0 {
                ready.insert(*d);
            }
        }
    }
    if degree.iter().any(|(k, n)| *k != end && *n > 0) {
        return Err("cyclic dependency".into());
    }
    Ok(result)
}
fn layer(mut parent: Id, parents: &HashMap<Id, Id>) -> Id {
    let original = parent;
    let mut seen = HashSet::new();
    while parent != ROOT && seen.insert(parent) {
        let ancestor = parents.get(&parent).copied().unwrap_or(ROOT);
        if ancestor == ROOT {
            return parent;
        }
        parent = ancestor;
    }
    original
}
fn anchor_positions(
    text: Option<&Value>,
    paper: &Value,
) -> Result<HashMap<Id, (f64, bool)>, String> {
    let mut positions = HashMap::new();
    let Some(text) = text else {
        positions.insert((0, 281474976710654), (0., true));
        if let Some(h) = paper.get(1).and_then(Value::as_f64) {
            positions.insert((0, 281474976710655), (h, true));
        }
        return Ok(positions);
    };
    let mut chars = Vec::new();
    for item in text["items"].as_array().ok_or("Invalid root text items")? {
        let deleted = item["deleted_length"].as_u64().unwrap_or(0);
        let value = &item["value"];
        if value.is_number() {
            chars.push(item.clone());
            continue;
        }
        let values: Vec<String> = if deleted > 0 {
            if deleted > 1_000_000 {
                return Err("Text deletion limit exceeded".into());
            }
            vec![String::new(); deleted as usize]
        } else {
            value
                .as_str()
                .unwrap_or("")
                .chars()
                .map(|c| c.to_string())
                .collect()
        };
        if chars.len() + values.len() > 1_000_000 {
            return Err("Expanded text exceeds limit".into());
        }
        let mut i = id(&item["item_id"]);
        let mut left = id(&item["left_id"]);
        let count = values.len();
        for (n, value) in values.into_iter().enumerate() {
            let next = (i.0, i.1.checked_add(1).ok_or("Text identifier overflow")?);
            let right = if n + 1 == count {
                id(&item["right_id"])
            } else {
                next
            };
            chars.push(
                json!({"item_id":ij(i),"left_id":ij(left),"right_id":ij(right),"value":value}),
            );
            left = i;
            i = next;
        }
    }
    let order = ordered(&chars)?;
    let lookup: HashMap<_, _> = chars
        .iter()
        .map(|i| (id(&i["item_id"]), &i["value"]))
        .collect();
    let mut y = num(&text["pos_y"]) + 63.;
    let top = y;
    let mut at = 0;
    while at < order.len() {
        let mut start = ZERO;
        if lookup[&order[at]].as_str() == Some("\n") {
            start = order[at];
            at += 1;
        }
        positions.insert(start, (y, false));
        while at < order.len() {
            let c = lookup[&order[at]];
            if c.as_str() == Some("\n") {
                break;
            }
            if c.is_string() {
                positions.insert(order[at], (y, false));
            }
            at += 1;
        }
        let style = &text["styles"][pyid(start)]["value"];
        let code = style["code"]
            .as_u64()
            .or_else(|| style.as_u64())
            .unwrap_or(1);
        y += match code {
            1 => 69.5,
            2 => 150.,
            4..=7 => 35.,
            _ => 70.,
        };
    }
    positions.insert((0, 281474976710654), (top, false));
    positions.insert((0, 281474976710655), (y, false));
    Ok(positions)
}
fn local(
    group: &Value,
    positions: &HashMap<Id, (f64, bool)>,
    root_y: Option<f64>,
    layout: &Value,
) -> Value {
    if group["anchor_id"].is_null() {
        return identity("Group has no anchor; identity translation.");
    }
    let anchor = id(&group["anchor_id"]["value"]);
    let x = num(&group["anchor_origin_x"]["value"]);
    let kind = group["anchor_type"]["value"].as_u64();
    let supplied = layout["offsets"][istr(anchor)]
        .as_f64()
        .filter(|_| root_y.is_some());
    if let (Some(offset), Some(2)) = (supplied, kind) {
        return transform(
            x,
            root_y.unwrap() + offset,
            true,
            format!(
                "Resolved text anchor {} from caller-supplied text anchor layout: {}.",
                pyid(anchor),
                layout["evidence"].as_str().unwrap_or("")
            ),
            vec![ij(anchor)],
        );
    }
    let Some(&(y, resolved)) = positions.get(&anchor) else {
        return transform(
            x,
            0.,
            false,
            format!(
                "Unresolved text anchor {}; retained X origin and used zero Y.",
                pyid(anchor)
            ),
            vec![ij(anchor)],
        );
    };
    let evidence = if supplied.is_some() {
        format!("Unverified anchor type {} for text anchor {}; caller-supplied type-2 layout evidence was not applied.",kind.map(|v|v.to_string()).unwrap_or("None".into()),pyid(anchor))
    } else if resolved {
        format!(
            "Resolved text anchor {} from special page anchors without root text.",
            pyid(anchor)
        )
    } else {
        format!("Unverified heuristic text anchor {} from {HEURISTIC}; retained calibrated matrix for diagnostics, but full text layout semantics are unresolved.",pyid(anchor))
    };
    transform(x, y, resolved, evidence, vec![ij(anchor)])
}
fn effective(
    node: Id,
    parents: &HashMap<Id, Id>,
    locals: &HashMap<Id, Value>,
    cache: &mut HashMap<Id, Value>,
    active: &mut HashSet<Id>,
) -> Result<Value, String> {
    if let Some(v) = cache.get(&node) {
        return Ok(v.clone());
    }
    if active.len() > 256 {
        return Err("Group hierarchy exceeds 256 levels".into());
    }
    if !active.insert(node) {
        let v = transform(
            0.,
            0.,
            false,
            format!(
                "Cycle detected while resolving group {}; used identity translation.",
                pyid(node)
            ),
            vec![],
        );
        cache.insert(node, v.clone());
        return Ok(v);
    }
    let Some(local) = locals.get(&node) else {
        return Ok(transform(
            0.,
            0.,
            false,
            format!(
                "Missing metadata for group {}; used identity translation.",
                pyid(node)
            ),
            vec![],
        ));
    };
    let parent = effective(
        parents.get(&node).copied().unwrap_or(ROOT),
        parents,
        locals,
        cache,
        active,
    )?;
    active.remove(&node);
    let result = if parent["matrix"] == json!(IDENTITY) && parent["resolved"] == true {
        local.clone()
    } else {
        let mut anchors = parent["anchor_ids"].as_array().unwrap().clone();
        anchors.extend(local["anchor_ids"].as_array().unwrap().clone());
        transform(
            num(&parent["matrix"][4]) + num(&local["matrix"][4]),
            num(&parent["matrix"][5]) + num(&local["matrix"][5]),
            parent["resolved"] == true && local["resolved"] == true,
            format!(
                "Cumulative group transform: {} {}",
                parent["evidence"].as_str().unwrap(),
                local["evidence"].as_str().unwrap()
            ),
            anchors,
        )
    };
    cache.insert(node, result.clone());
    Ok(result)
}
fn walk(
    parent: Id,
    by_parent: &HashMap<Id, Vec<Value>>,
    groups: &mut Vec<Id>,
    strokes: &mut Vec<Id>,
    seen: &mut HashSet<Id>,
    stroke_seen: &mut HashSet<Id>,
    depth: usize,
) -> Result<(), String> {
    if depth > 256 {
        return Err("Scene hierarchy exceeds 256 levels".into());
    }
    if !seen.insert(parent) {
        return Ok(());
    }
    let Some(blocks) = by_parent.get(&parent) else {
        return Ok(());
    };
    let items: Vec<_> = blocks.iter().map(|b| b["fields"]["item"].clone()).collect();
    let order = ordered(&items)?;
    let map: HashMap<_, _> = blocks
        .iter()
        .map(|b| (id(&b["fields"]["item"]["item_id"]), b))
        .collect();
    for item_id in order {
        let b = map[&item_id];
        let v = &b["fields"]["item"]["value"];
        if v.is_null() {
            continue;
        }
        match b["type"].as_u64() {
            Some(4) => {
                let group = id(v);
                if !seen.contains(&group) {
                    groups.push(group);
                    walk(
                        group,
                        by_parent,
                        groups,
                        strokes,
                        seen,
                        stroke_seen,
                        depth + 1,
                    )?;
                }
            }
            Some(5) => {
                if stroke_seen.insert(item_id) {
                    strokes.push(item_id);
                }
            }
            _ => {}
        }
    }
    Ok(())
}
/// Decode .rm v5/v6 and retain source records separately from render projection.
pub fn parse(raw: &[u8], page_id: &str, layout: &Value) -> Result<Value, String> {
    if raw.starts_with(crate::legacy::HEADER) {
        return crate::legacy::parse(raw, page_id);
    }
    normalize_blocks(&crate::v6::decode(raw)?, page_id, layout)
}
/// Select an inferred sequence explicitly; neither strategy claims timestamps.
pub fn parse_with_strategy(
    raw: &[u8],
    page_id: &str,
    layout: &Value,
    strategy: &str,
) -> Result<Value, String> {
    if !matches!(strategy, "crdt-order" | "scene-order") {
        return Err(format!("unknown replay strategy: {strategy}"));
    }
    let mut page = parse(raw, page_id, layout)?;
    if strategy == "scene-order" && !raw.starts_with(crate::legacy::HEADER) {
        page["replay_order"] = json!({"strategy":"scene-order","stroke_ids":page["compositing_order"],"evidence":"Deterministic scene compositing order fallback; drawing time is unverified."});
    }
    Ok(page)
}
pub fn normalize_blocks(decoded: &Value, page_id: &str, layout: &Value) -> Result<Value, String> {
    if !layout.is_null() {
        if layout["evidence"]
            .as_str()
            .is_none_or(|s| s.trim().is_empty())
        {
            return Err("text anchor layout evidence must be nonblank".into());
        }
        for value in layout["offsets"]
            .as_object()
            .ok_or("text anchor layout offsets must be an object")?
            .values()
        {
            if !value.as_f64().is_some_and(f64::is_finite) {
                return Err("text anchor offsets must be finite".into());
            }
        }
    }
    let blocks = decoded.as_array().ok_or("Expected decoded block array")?;
    validate_blocks(blocks)?;
    let valid: Vec<_> = blocks.iter().filter(|b| b["unreadable"] != true).collect();
    let scene = valid.iter().find(|b| b["type"] == 13).map(|b| &b["fields"]);
    let paper = scene
        .map(|s| s["paper_size"].clone())
        .unwrap_or(Value::Null);
    let text = valid
        .iter()
        .rev()
        .find(|b| b["type"] == 7)
        .map(|b| &b["fields"]["value"]);
    let positions = anchor_positions(text, &paper)?;
    let root_y = text.map(|t| num(&t["pos_y"]));
    let mut trees = Vec::<(Id, Value)>::new();
    let mut details = HashMap::new();
    let mut positioned = HashMap::new();
    let mut by_parent: HashMap<Id, Vec<Value>> = HashMap::new();
    for (index, b) in blocks.iter().enumerate() {
        if b["unreadable"] == true {
            continue;
        }
        let f = &b["fields"];
        match b["type"].as_u64() {
            Some(1) => {
                let i = id(&f["tree_id"]);
                if let Some(old) = trees.iter_mut().find(|(key, _)| *key == i) {
                    old.1 = f.clone()
                } else {
                    trees.push((i, f.clone()));
                }
            }
            Some(2) => {
                details.insert(id(&f["group"]["node_id"]), f["group"].clone());
            }
            _ => {}
        }
        if (3..=6).contains(&b["type"].as_u64().unwrap_or(99)) || b["type"] == 8 {
            by_parent
                .entry(id(&f["parent_id"]))
                .or_default()
                .push(b.clone());
            if b["type"] == 4 && !f["item"]["value"].is_null() {
                positioned.insert(id(&f["item"]["value"]), (index, f.clone()));
            }
        }
    }
    let parents: HashMap<_, _> = trees
        .iter()
        .map(|(i, t)| (*i, id(&t["parent_id"])))
        .collect();
    let locals: HashMap<_, _> = details
        .iter()
        .map(|(i, g)| (*i, local(g, &positions, root_y, layout)))
        .collect();
    let mut cache = HashMap::from([(ROOT, identity("Scene root uses identity translation."))]);
    let mut groups = vec![];
    for (i, t) in &trees {
        let (Some(g), Some((index, item))) = (details.get(i), positioned.get(i)) else {
            continue;
        };
        let result = effective(*i, &parents, &locals, &mut cache, &mut HashSet::new())?;
        groups.push(json!({"node_id":ij(*i),"source_node_id":strip(&t["node_id"]),"parent_id":strip(&t["parent_id"]),"layer_id":ij(layer(*i,&parents)),"kind":if id(&t["parent_id"])==ROOT{"layer"}else{"group"},"label":strip(&g["label"]),"visible":strip(&g["visible"]),"scene_order":scene_order(&item["item"],*index),"local_transform":locals[i],"effective_transform":result,"extra":{"is_update":t["is_update"],"anchor_id":g["anchor_id"],"anchor_type":g["anchor_type"],"anchor_threshold":g["anchor_threshold"],"anchor_origin_x":g["anchor_origin_x"]}}));
    }
    let (mut group_order, mut composing) = (vec![], vec![]);
    walk(
        ROOT,
        &by_parent,
        &mut group_order,
        &mut composing,
        &mut HashSet::new(),
        &mut HashSet::new(),
        0,
    )?;
    let rank: HashMap<_, _> = group_order
        .iter()
        .enumerate()
        .map(|(n, i)| (*i, n))
        .collect();
    groups.sort_by_key(|g| {
        (
            rank.get(&id(&g["node_id"])).copied().unwrap_or(rank.len()),
            g["scene_order"]["block_index"].as_u64().unwrap_or(0),
        )
    });
    let mut strokes = vec![];
    let mut tombstones = vec![];
    let mut migrations = vec![];
    let mut authors = serde_json::Map::new();
    let mut page_info = Value::Null;
    for (index, b) in blocks.iter().enumerate() {
        if b["unreadable"] == true {
            continue;
        }
        let f = &b["fields"];
        let item = &f["item"];
        match b["type"].as_u64(){Some(5) if !item["value"].is_null()=>{let line=&item["value"];let mut points=line["points"].as_array().ok_or("Invalid line points")?.clone();for p in &mut points{p["extra"]=json!({});}strokes.push(json!({"stroke_id":strip(&item["item_id"]),"parent_id":strip(&f["parent_id"]),"layer_id":ij(layer(id(&f["parent_id"]),&parents)),"scene_order":scene_order(item,index),"move_id":strip(&line["move_id"]),"tool":line["tool"],"color":line["color"],"color_rgba":line["color_rgba"],"thickness_scale":line["thickness_scale"],"starting_length":line["starting_length"],"points":points,"effective_transform":effective(id(&f["parent_id"]),&parents,&locals,&mut cache,&mut HashSet::new())?,"extra":{}}));},Some(8)=>tombstones.push(json!({"tombstone_id":strip(&item["item_id"]),"parent_id":strip(&f["parent_id"]),"scene_order":scene_order(item,index)})),Some(0)=>migrations.push(json!({"migration_id":strip(&f["migration_id"]),"is_device":f["is_device"],"unknown":f["_unknown"]})),Some(9)=>{if let Some(a)=f["author_uuids"].as_object(){authors.extend(a.clone());}},Some(10)=>page_info=f.clone(),_=>{}}
    }
    let mut replay: Vec<_> = strokes.iter().map(|s| id(&s["stroke_id"])).collect();
    replay.sort_by_key(|i| (i.1, i.0));
    let diagnostics: Vec<_> = blocks
        .iter()
        .enumerate()
        .map(|(i, b)| {
            let mut value = b.clone();
            value["block_index"] = json!(i);
            value["block_type"] = b["type"].clone();
            value
        })
        .collect();
    let mut warnings: Vec<Value> = blocks
        .iter()
        .filter(|b| {
            b["unreadable"] == true
                || b["extra_data_hex"].as_str().is_some_and(|s| !s.is_empty())
                || b["extra_value_data_hex"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty())
        })
        .map(|b| {
            json!(format!(
                "Block {} contains unknown or unreadable data; retained in diagnostics",
                b["index"]
            ))
        })
        .collect();
    for g in &groups {
        if g["effective_transform"]["resolved"] != true {
            warnings.push(json!(format!(
                "Unresolved group {}; {}",
                istr(id(&g["node_id"])),
                g["effective_transform"]["evidence"]
            )));
        }
    }
    Ok(
        json!({"page_id":page_id,"paper_size":paper,"source_to_page_transform":null,"groups":groups,"strokes":strokes,"tombstones":tombstones,"compositing_order":composing.into_iter().map(ij).collect::<Vec<_>>(),"replay_order":{"strategy":"crdt-order","stroke_ids":replay.into_iter().map(ij).collect::<Vec<_>>(),"evidence":"Deterministic ordering by CRDT counter then author identifier; drawing time is unverified."},"metadata":{"current_layer":scene.map(|s|strip(&s["current_layer"])),"background_visible":scene.map(|s|strip(&s["background_visible"])),"root_document_visible":scene.map(|s|strip(&s["root_document_visible"])),"authors":authors,"migrations":migrations,"page_info":page_info},"diagnostics":{"blocks":diagnostics,"warnings":warnings}}),
    )
}
/// Pure normalized-page projection. No renderer dependency or filesystem access.
fn validate_projection(page: &Value) -> Result<(), String> {
    let valid_id = |v: &Value| v["part1"].as_u64().is_some() && v["part2"].as_u64().is_some();
    let finite = |v: &Value| v.as_f64().is_some_and(f64::is_finite);
    if !page["page_id"].is_string() {
        return Err("Invalid normalized page identifier".into());
    }
    for group in page["groups"]
        .as_array()
        .ok_or("Invalid normalized groups")?
    {
        if !valid_id(&group["node_id"])
            || !valid_id(&group["layer_id"])
            || !group["visible"]["value"].is_boolean()
            || !matches!(group["kind"].as_str(), Some("group" | "layer"))
        {
            return Err("Invalid normalized group".into());
        }
    }
    for stroke in page["strokes"]
        .as_array()
        .ok_or("Invalid normalized strokes")?
    {
        if !valid_id(&stroke["stroke_id"])
            || !valid_id(&stroke["layer_id"])
            || !finite(&stroke["thickness_scale"])
            || stroke["tool"]["code"].as_u64().is_none()
            || stroke["color"]["code"].as_u64().is_none()
        {
            return Err("Invalid normalized stroke metadata".into());
        }
        if !stroke["effective_transform"]["matrix"]
            .as_array()
            .is_some_and(|a| a.len() == 6 && a.iter().all(finite))
        {
            return Err("Invalid normalized stroke transform".into());
        }
        if !stroke["color_rgba"].is_null()
            && !stroke["color_rgba"].as_array().is_some_and(|a| {
                a.len() == 4 && a.iter().all(|v| v.as_u64().is_some_and(|v| v <= 255))
            })
        {
            return Err("Invalid explicit RGBA".into());
        }
        for point in stroke["points"]
            .as_array()
            .ok_or("Invalid normalized points")?
        {
            if ["x", "y", "pressure", "speed", "direction", "width"]
                .iter()
                .any(|k| !finite(&point[*k]))
                || !point["extra"].is_object()
            {
                return Err("Invalid or nonfinite normalized point channel".into());
            }
        }
    }
    for key in ["compositing_order"] {
        if !page[key].as_array().is_some_and(|a| a.iter().all(valid_id)) {
            return Err("Invalid normalized composing order".into());
        }
    }
    if !page["replay_order"]["stroke_ids"]
        .as_array()
        .is_some_and(|a| a.iter().all(valid_id))
    {
        return Err("Invalid normalized replay order".into());
    }
    Ok(())
}
pub fn project(page: &Value, paper: [f64; 2], affine: [f64; 6]) -> Result<Value, String> {
    validate_projection(page)?;
    if let Some(blocks) = page["diagnostics"]["blocks"].as_array() {
        for block in blocks {
            if block["unreadable"] == true
                && !matches!(block["block_type"].as_u64(), Some(0 | 9 | 10))
            {
                return Err(format!(
                    "Unsupported or unreadable geometry block {}; retained in parser diagnostics",
                    block["block_type"]
                ));
            }
        }
    }
    if paper
        .iter()
        .any(|n| !n.is_finite() || *n <= 0. || n.fract() != 0.)
        || affine.iter().any(|n| !n.is_finite())
    {
        return Err("Invalid page geometry".into());
    }
    let groups = page["groups"]
        .as_array()
        .ok_or("Invalid normalized groups")?;
    let mut layers = vec![];
    let mut visible = HashMap::new();
    for g in groups {
        let l = istr(id(&g["layer_id"]));
        if !visible.contains_key(&l) {
            layers.push(l.clone());
            visible.insert(l.clone(), true);
        }
        if g["kind"] == "layer" && id(&g["node_id"]) == id(&g["layer_id"]) {
            visible.insert(l, g["visible"]["value"].as_bool().unwrap_or(false));
        }
    }
    let rank: HashMap<_, _> = page["compositing_order"]
        .as_array()
        .ok_or("Invalid composing order")?
        .iter()
        .enumerate()
        .map(|(i, v)| (id(v), i))
        .collect();
    let mut ordered = page["strokes"]
        .as_array()
        .ok_or("Invalid normalized strokes")?
        .clone();
    ordered.sort_by_key(|s| {
        rank.get(&id(&s["stroke_id"]))
            .copied()
            .unwrap_or(rank.len() + s["scene_order"]["block_index"].as_u64().unwrap_or(0) as usize)
    });
    const PALETTE: [[u8; 4]; 14] = [
        [0, 0, 0, 255],
        [144, 144, 144, 255],
        [255, 255, 255, 255],
        [254, 253, 96, 255],
        [0, 128, 0, 255],
        [255, 105, 180, 255],
        [48, 74, 224, 255],
        [194, 49, 50, 255],
        [128, 128, 128, 255],
        [253, 227, 0, 128],
        [0, 170, 80, 255],
        [0, 180, 190, 255],
        [210, 0, 150, 255],
        [255, 200, 0, 255],
    ];
    let mut strokes = vec![];
    for s in ordered {
        let rgba = if !s["color_rgba"].is_null() {
            s["color_rgba"].clone()
        } else {
            json!(PALETTE
                .get(s["color"]["code"].as_u64().ok_or("Invalid color code")? as usize)
                .ok_or("Unknown color without explicit RGBA")?)
        };
        let matrix = s["effective_transform"]["matrix"]
            .as_array()
            .ok_or("Missing group transform")?;
        if matrix.len() != 6 {
            return Err("Invalid group transform".into());
        }
        let mut points = vec![];
        for p in s["points"].as_array().ok_or("Invalid points")? {
            let gx =
                num(&matrix[0]) * num(&p["x"]) + num(&matrix[2]) * num(&p["y"]) + num(&matrix[4]);
            let gy =
                num(&matrix[1]) * num(&p["x"]) + num(&matrix[3]) * num(&p["y"]) + num(&matrix[5]);
            let legacy = p["extra"]["file_format"] == 5;
            points.push(json!({"x":affine[0]*gx+affine[2]*gy+affine[4],"y":affine[1]*gx+affine[3]*gy+affine[5],"pressure":num(&p["pressure"])*if legacy{255.}else{1.},"speed":num(&p["speed"])*if legacy{4.}else{1.},"direction":num(&p["direction"])*if legacy{255./(2.*std::f64::consts::PI)}else{1.},"width":num(&p["width"])*if legacy{4.}else{1.},"extra":p["extra"]}));
        }
        strokes.push(json!({"stroke_id":istr(id(&s["stroke_id"])),"group_id":istr(id(&s["layer_id"])),"rgba":rgba,"thickness_scale":s["thickness_scale"],"points":points,"tool_code":s["tool"]["code"],"tool_name":s["tool"]["name"]}));
    }
    Ok(
        json!({"page_id":page["page_id"],"paper_size":paper,"groups":layers.iter().map(|l|json!({"group_id":l,"visible":visible[l]})).collect::<Vec<_>>(),"strokes":strokes,"compositing_order":layers,"replay_order":page["replay_order"]["stroke_ids"].as_array().ok_or("Invalid replay order")?.iter().map(|i|istr(id(i))).collect::<Vec<_>>(),"replay_strategy":page["replay_order"]["strategy"],"replay_evidence":page["replay_order"]["evidence"]}),
    )
}
