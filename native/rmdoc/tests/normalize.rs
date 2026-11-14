use rm_rmdoc::normalize::{normalize_blocks, project};
use serde_json::{json, Value};
fn id(a: u64, b: u64) -> Value {
    json!({"part1":a,"part2":b,"text":format!("{a}:{b}")})
}
fn block(t: u64, fields: Value) -> Value {
    json!({"type":t,"index":0,"fields":fields,"unreadable":false})
}
fn fixture() -> Value {
    json!([
        block(
            1,
            json!({"tree_id":id(1,10),"node_id":id(1,10),"parent_id":id(0,1),"is_update":false})
        ),
        block(
            2,
            json!({"group":{"node_id":id(1,10),"label":{"timestamp":id(0,0),"value":"Ink"},"visible":{"timestamp":id(0,0),"value":true}}})
        ),
        block(
            4,
            json!({"parent_id":id(0,1),"item":{"item_id":id(1,11),"left_id":id(0,0),"right_id":id(0,0),"deleted_length":0,"value":id(1,10)}})
        ),
        block(
            5,
            json!({"parent_id":id(1,10),"item":{"item_id":id(1,20),"left_id":id(0,0),"right_id":id(0,0),"deleted_length":0,"value":{"tool":{"code":15,"name":"BALLPOINT_2"},"color":{"code":0,"name":"BLACK"},"thickness_scale":1.,"starting_length":0.,"points":[{"x":3.,"y":4.,"pressure":50,"speed":2,"direction":0,"width":8}]}}})
        )
    ])
}
#[test]
fn normalizes_and_projects_without_changing_raw_points() {
    let p = normalize_blocks(&fixture(), "page", &Value::Null).unwrap();
    assert_eq!(p["strokes"][0]["points"][0]["x"], 3.);
    let r = project(&p, [100., 200.], [1., 0., 0., 1., 50., 0.]).unwrap();
    assert_eq!(r["strokes"][0]["points"][0]["x"], 53.);
    assert_eq!(r["strokes"][0]["stroke_id"], "1:20");
    assert_eq!(r["compositing_order"], json!(["1:10"]));
}
#[test]
fn rejects_unknown_full_version() {
    assert!(rm_rmdoc::normalize::parse(
        b"reMarkable .lines file, version=7          ",
        "page",
        &Value::Null
    )
    .is_err());
}
#[test]
fn crdt_cycle_is_rejected() {
    let mut blocks = fixture();
    blocks[3]["fields"]["item"]["left_id"] = id(1, 20);
    assert!(normalize_blocks(&blocks, "page", &Value::Null).is_err());
}
#[test]
fn v5_channels_are_preserved_and_projected() {
    let mut raw = b"reMarkable .lines file, version=5          ".to_vec();
    for n in [1u32, 1, 2, 0, 0] {
        raw.extend(n.to_le_bytes());
    }
    raw.extend(1.5f32.to_le_bytes());
    for n in [0u32, 1] {
        raw.extend(n.to_le_bytes());
    }
    for f in [3f32, 4., 2., 0.5, 1., 0.75] {
        raw.extend(f.to_le_bytes());
    }
    let p = rm_rmdoc::normalize::parse(&raw, "legacy", &Value::Null).unwrap();
    assert_eq!(p["strokes"][0]["points"][0]["pressure"], 0.75);
    let r = project(&p, [100., 100.], [1., 0., 0., 1., 0., 0.]).unwrap();
    assert_eq!(r["strokes"][0]["points"][0]["pressure"], 191.25);
    assert_eq!(r["replay_strategy"], "scene-order");
}
#[test]
fn unreadable_geometry_is_retained_but_not_silently_projected() {
    let mut blocks = fixture();
    blocks.as_array_mut().unwrap().push(json!({"type":5,"index":4,"block_name":"UnreadableBlock","unreadable":true,"raw_hex":"aabb","error":"future geometry","fields":{}}));
    let p = normalize_blocks(&blocks, "page", &Value::Null).unwrap();
    assert_eq!(p["diagnostics"]["blocks"][4]["raw_hex"], "aabb");
    assert!(project(&p, [100., 100.], [1., 0., 0., 1., 0., 0.]).is_err());
}
#[test]
fn unknown_metadata_does_not_lose_diagnostics() {
    let mut blocks = fixture();
    blocks
        .as_array_mut()
        .unwrap()
        .push(json!({"type":10,"index":4,"unreadable":true,"raw_hex":"dd","fields":{}}));
    let p = normalize_blocks(&blocks, "page", &Value::Null).unwrap();
    assert_eq!(p["diagnostics"]["blocks"][4]["raw_hex"], "dd");
    assert!(project(&p, [100., 100.], [1., 0., 0., 1., 0., 0.]).is_ok());
}
#[test]
fn projection_rejects_missing_or_non_numeric_channels() {
    let mut p = normalize_blocks(&fixture(), "page", &Value::Null).unwrap();
    p["strokes"][0]["points"][0]
        .as_object_mut()
        .unwrap()
        .remove("x");
    assert!(project(&p, [100., 100.], [1., 0., 0., 1., 0., 0.]).is_err());
}
#[test]
fn projection_rejects_fractional_paper_geometry() {
    let p = normalize_blocks(&fixture(), "page", &Value::Null).unwrap();
    assert!(project(&p, [100.5, 100.], [1., 0., 0., 1., 0., 0.]).is_err());
}
#[test]
fn rejects_invalid_replay_strategy() {
    let mut raw = b"reMarkable .lines file, version=5          ".to_vec();
    raw.extend(0u32.to_le_bytes());
    assert!(rm_rmdoc::normalize::parse_with_strategy(&raw, "p", &Value::Null, "invented").is_err());
}
#[test]
fn explicit_scene_order_is_labeled() {
    let raw = b"reMarkable .lines file, version=6          ";
    let p =
        rm_rmdoc::normalize::parse_with_strategy(raw, "p", &Value::Null, "scene-order").unwrap();
    assert_eq!(p["replay_order"]["strategy"], "scene-order");
    assert_eq!(p["replay_order"]["stroke_ids"], p["compositing_order"]);
}
#[test]
fn decoded_normalization_rejects_invalid_geometry_fields() {
    let mut b = fixture();
    b[3]["fields"]["item"]["value"]["points"][0]["x"] = json!("not a number");
    assert!(normalize_blocks(&b, "p", &Value::Null).is_err());
    let mut b = fixture();
    b[0]["fields"]["tree_id"] = json!({"part1":1});
    assert!(normalize_blocks(&b, "p", &Value::Null).is_err());
}
