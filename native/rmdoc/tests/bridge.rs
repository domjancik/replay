use rm_rmdoc::bridge::{resolve_fits, settings};
use serde_json::json;
#[test]
fn settings_match_python_rounding_and_reject_bad_inputs() {
    let s = json!({"width":1024,"height":800,"offset_x":512,"offset_y":0,"seconds":2,"fps":6,"output_width":128,"backend":"rust"});
    assert_eq!(settings(&s).unwrap()["viewport"], json!([128, 100]));
    let mut bad = s.clone();
    bad["fps"] = json!(true);
    assert!(settings(&bad).is_err());
    bad = s.clone();
    bad["allow_clipping"] = json!(1);
    assert!(settings(&bad).is_err());
}
#[test]
fn shared_anchor_disagreement_rejects() {
    let plan = json!({"root_y":234,"page_y":0,"templates":[{"anchor_id":"1:17","parent_y":0},{"anchor_id":"1:17","parent_y":0}]});
    let fits = json!([{"accepted":true,"best_candidate":{"translation_y":500}},{"accepted":true,"best_candidate":{"translation_y":600}}]);
    assert!(resolve_fits(&plan, &fits)
        .unwrap_err()
        .contains("conflicting"));
}
