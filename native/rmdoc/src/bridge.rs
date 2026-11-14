//! Browser host adapter. Parsing and projection do not depend on the renderer.
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
fn num(v: &Value) -> Result<f64, String> {
    v.as_f64()
        .filter(|n| n.is_finite())
        .ok_or("Expected finite number".into())
}
fn number(v: &Value, key: &str, lo: f64, hi: f64, integer: bool) -> Result<f64, String> {
    let n = num(&v[key])?;
    if n < lo || n > hi || (integer && n.fract() != 0.) {
        return Err(format!("Invalid {key}"));
    }
    Ok(n)
}
pub fn settings(v: &Value) -> Result<Value, String> {
    let w = number(v, "width", 64., 4096., true)?;
    let h = number(v, "height", 64., 8192., true)?;
    if w * h > 12_000_000. {
        return Err("Canvas exceeds 12 megapixels".into());
    }
    let o = number(v, "output_width", 128., 2808., true)?;
    let o = o + (o % 2.);
    let oh = (o * h / w / 2.).round_ties_even().max(1.) * 2.;
    if o * oh > 12_000_000. || oh > 8192. {
        return Err("Output exceeds browser dimensions; reduce output width".into());
    }
    let seconds = number(v, "seconds", 2., 60., false)?;
    let fps = number(v, "fps", 6., 30., true)?;
    let ordering = v.get("ordering").and_then(Value::as_str).unwrap_or("layer");
    if !matches!(ordering, "layer" | "entry") || v.get("ordering").is_some_and(|x| !x.is_string()) {
        return Err("Unknown replay ordering".into());
    }
    let backend = v["backend"].as_str().ok_or("Unknown pencil backend")?;
    if !matches!(backend, "rust" | "python") {
        return Err("Unknown pencil backend".into());
    }
    let clipping = match v.get("allow_clipping") {
        Some(x) => x.as_bool().ok_or("allow_clipping must be true or false")?,
        None => false,
    };
    Ok(
        json!({"paper_size":[w as usize,h as usize],"source_affine":[1,0,0,1,number(v,"offset_x",-8192.,8192.,false)?,number(v,"offset_y",-8192.,8192.,false)?],"viewport":[o as usize,oh as usize],"seconds":seconds,"fps":fps as usize,"backend":backend,"ordering":ordering,"allow_clipping":clipping}),
    )
}
pub fn resolve_fits(plan: &Value, fits: &Value) -> Result<Value, String> {
    let templates = plan["templates"]
        .as_array()
        .ok_or("Missing anchor templates")?;
    let fits = fits.as_array().ok_or("Invalid anchor fits")?;
    if fits.len() != templates.len() {
        return Err("Native anchor result count mismatch".into());
    }
    let mut offsets = serde_json::Map::new();
    for (template, fit) in templates.iter().zip(fits) {
        if fit["accepted"] != true {
            return Err(format!("Group {}: {}", template["group_id"], fit["reason"]));
        }
        let offset = num(&fit["best_candidate"]["translation_y"])?
            - num(&plan["page_y"])?
            - num(&template["parent_y"])?
            - num(&plan["root_y"])?;
        let id = template["anchor_id"]
            .as_str()
            .ok_or("Invalid anchor identifier")?;
        if offsets.get(id).is_some_and(|x| x != &json!(offset)) {
            return Err("conflicting-shared-anchor-offsets".into());
        }
        offsets.insert(id.into(), json!(offset));
    }
    Ok(Value::Object(offsets))
}
fn id(v: &Value) -> String {
    format!("{}:{}", v["part1"], v["part2"])
}
fn array<'a>(v: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    v[key].as_array().ok_or(format!("Missing {key}"))
}
pub fn info(raw: &[u8], page_id: &str) -> Result<Value, String> {
    let p = crate::normalize::parse(raw, page_id, &Value::Null)?;
    let strokes = array(&p, "strokes")?;
    Ok(
        json!({"strokes":strokes.len(),"paper_size":p["paper_size"],"source_to_page_transform":p["source_to_page_transform"],"unresolved_anchors":strokes.iter().filter(|s|s["effective_transform"]["resolved"]!=true).count()}),
    )
}
pub fn anchor_templates(raw: &[u8], page_id: &str, s: &Value) -> Result<Value, String> {
    let config = settings(s)?;
    let p = crate::normalize::parse(raw, page_id, &Value::Null)?;
    if !array(&p, "strokes")?
        .iter()
        .any(|s| s["effective_transform"]["resolved"] != true)
    {
        return Ok(Value::Null);
    }
    let root = array(&p["diagnostics"], "blocks")?
        .iter()
        .find(|b| b["block_name"] == "RootTextBlock" && b["unreadable"] != true)
        .ok_or("Missing root text geometry for native anchor matching")?;
    let root_y = num(&root["fields"]["value"]["pos_y"])?;
    let groups: HashMap<_, _> = array(&p, "groups")?
        .iter()
        .map(|g| (id(&g["node_id"]), g))
        .collect();
    let mut templates = vec![];
    for g in array(&p, "groups")? {
        let anchors = array(&g["local_transform"], "anchor_ids")?;
        if anchors.is_empty() {
            continue;
        }
        if g["extra"]["anchor_type"]["value"] != 2 {
            if g["effective_transform"]["resolved"] != true {
                return Err("Unsupported native text-anchor type".into());
            }
            continue;
        }
        let mut parent = id(&g["parent_id"]);
        let mut visited = HashSet::from([id(&g["node_id"])]);
        while let Some(a) = groups.get(&parent) {
            if !visited.insert(parent.clone()) || a["effective_transform"]["resolved"] != true {
                return Err("unsupported-unresolved-ancestor".into());
            }
            parent = id(&a["parent_id"]);
        }
        let local = array(&g["local_transform"], "matrix")?;
        let effective = array(&g["effective_transform"], "matrix")?;
        for (i, n) in [1., 0., 0., 1.].iter().enumerate() {
            if num(&local[i])? != *n || num(&effective[i])? != *n {
                return Err("unsupported-nontranslation-group-transform".into());
            }
        }
        let strokes: Vec<_> = array(&p, "strokes")?
            .iter()
            .filter(|st| {
                st["parent_id"] == g["node_id"]
                    && st["points"].as_array().is_some_and(|v| v.len() >= 2)
            })
            .map(|st| {
                st["points"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|pt| json!([pt["x"], pt["y"]]))
                    .collect::<Vec<_>>()
            })
            .collect();
        if strokes.is_empty() {
            return Err(format!(
                "Group {}: unsupported-no-direct-stroke-template",
                id(&g["node_id"])
            ));
        }
        templates.push(json!({"group_id":id(&g["node_id"]),"anchor_id":id(&anchors[0]),"parent_y":num(&effective[5])?-num(&local[5])?,"strokes":strokes,"expected_x":num(&config["source_affine"][4])?+num(&effective[4])?}));
    }
    if templates.is_empty() {
        return Err("Unresolved page has no supported native anchor templates".into());
    }
    Ok(json!({"root_y":root_y,"page_y":config["source_affine"][5],"templates":templates}))
}
pub fn prepare(
    raw: &[u8],
    page_id: &str,
    s: &Value,
    anchor_result: &Value,
) -> Result<Value, String> {
    let config = settings(s)?;
    let layout = if anchor_result.is_null() {
        Value::Null
    } else {
        let plan = anchor_templates(raw, page_id, s)?;
        json!({"offsets":resolve_fits(&plan,&anchor_result["fits"])? ,"evidence":anchor_result["evidence"]})
    };
    let parsed = crate::normalize::parse(raw, page_id, &layout)?;
    if array(&parsed, "strokes")?
        .iter()
        .any(|s| s["effective_transform"]["resolved"] != true)
    {
        return Err(
            "This page needs native PDF text-anchor matching. Attach the matching native PDF."
                .into(),
        );
    }
    let paper = [
        num(&config["paper_size"][0])?,
        num(&config["paper_size"][1])?,
    ];
    let mut affine = [0.; 6];
    for (i, n) in affine.iter_mut().enumerate() {
        *n = num(&config["source_affine"][i])?;
    }
    let page = crate::normalize::project(&parsed, paper, affine)?;
    let groups: HashSet<_> = array(&page, "groups")?
        .iter()
        .filter(|g| g["visible"] == true)
        .filter_map(|g| g["group_id"].as_str())
        .collect();
    let replay: HashSet<_> = array(&page, "replay_order")?
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let visible: Vec<_> = array(&page, "strokes")?
        .iter()
        .filter(|s| {
            groups.contains(s["group_id"].as_str().unwrap_or(""))
                && replay.contains(s["stroke_id"].as_str().unwrap_or(""))
        })
        .collect();
    if visible.is_empty() {
        return Err("Page has no visible strokes to replay".into());
    }
    if config["allow_clipping"] != true {
        for s in visible {
            for p in array(s, "points")? {
                let x = num(&p["x"])?;
                let y = num(&p["y"])?;
                if x < 0. || x > paper[0] || y < 0. || y > paper[1] {
                    return Err("Visible stroke points fall outside the selected canvas. Adjust the canvas dimensions or offsets, or allow clipping.".into());
                }
            }
        }
    }
    Ok(
        json!({"request":{"page":page,"options":{"viewport":{"width":config["viewport"][0],"height":config["viewport"][1]}}},"frames":[],"config":config,"parser":{"name":"rm-rmdoc","version":env!("CARGO_PKG_VERSION"),"schema_version":crate::NORMALIZATION_SCHEMA_VERSION,"file_format":if raw.starts_with(crate::legacy::HEADER){5}else{6}}}),
    )
}
/// Dispatch bounded host operations. Raw bytes are passed separately to avoid JSON inflation.
pub fn execute(raw: &[u8], args: &Value) -> Result<Value, String> {
    let op = args["op"].as_str().ok_or("Missing operation")?;
    if op == "inspect" {
        return crate::archive::inspect(raw);
    }
    let member = args.get("member").and_then(Value::as_str);
    let bytes;
    let raw = if let Some(member) = member {
        bytes = crate::archive::page_bytes(raw, member)?;
        &bytes[..]
    } else {
        raw
    };
    let page = args["page"].as_str().ok_or("Missing page identifier")?;
    if page.len() > 128 {
        return Err("Page identifier too long".into());
    }
    match op {
        "project" => {
            let parsed = crate::normalize::parse(raw, page, &args["layout"])?;
            let paper: [f64; 2] = serde_json::from_value(args["paper_size"].clone())
                .map_err(|_| "Invalid paper size")?;
            let affine: [f64; 6] = serde_json::from_value(args["source_affine"].clone())
                .map_err(|_| "Invalid source affine")?;
            crate::normalize::project(&parsed, paper, affine)
        }
        "info" => info(raw, page),
        "parse" => crate::normalize::parse_with_strategy(
            raw,
            page,
            &args["layout"],
            args.get("replay_strategy")
                .and_then(Value::as_str)
                .unwrap_or("crdt-order"),
        ),
        "anchors" => anchor_templates(raw, page, &args["settings"]),
        "prepare" => prepare(raw, page, &args["settings"], &args["anchor_result"]),
        _ => Err("Unknown reader operation".into()),
    }
}
