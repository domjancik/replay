use rm_rmdoc::v6::decode;
const HEADER: &[u8] = b"reMarkable .lines file, version=6          ";
fn block(kind: u8, version: u8, body: &[u8]) -> Vec<u8> {
    let mut b = HEADER.to_vec();
    b.extend((body.len() as u32).to_le_bytes());
    b.extend([0, 1, version, kind]);
    b.extend(body);
    b
}
#[test]
fn migration_and_unknown_payload_are_preserved() {
    let known = decode(&block(0, 1, &[0x1f, 1, 25, 0x21, 1, 0x31, 0, 0xaa])).unwrap();
    assert_eq!(known[0]["fields"]["migration_id"]["text"], "1:25");
    assert_eq!(known[0]["fields"]["is_device"], true);
    assert_eq!(known[0]["extra_data_hex"], "aa");
    let unknown = decode(&block(99, 1, &[0xde, 0xad])).unwrap();
    assert_eq!(unknown[0]["unreadable"], true);
    assert_eq!(unknown[0]["raw_hex"], "dead");
}
#[test]
fn truncated_and_future_headers_fail_without_panicking() {
    assert!(decode(b"not a page").is_err());
    let mut bytes = block(0, 1, &[0x1f, 1, 25, 0x21, 1]);
    bytes.pop();
    assert!(decode(&bytes).is_err());
    let mut bytes = HEADER.to_vec();
    bytes.extend([1, 2]);
    assert!(decode(&bytes).is_err());
}
#[test]
fn malformed_nested_data_is_retained_as_unreadable() {
    let b = decode(&block(2, 2, &[0x1f, 1, 2, 0x2c, 255, 255, 255, 255])).unwrap();
    assert_eq!(b[0]["unreadable"], true);
    assert!(!b[0]["raw_hex"].as_str().unwrap().is_empty());
}

#[test]
fn newer_required_block_version_is_retained_not_interpreted() {
    let mut bytes = block(0, 9, &[0x1f, 1, 25, 0x21, 1]);
    bytes[43 + 5] = 9;
    let value = decode(&bytes).unwrap();
    assert_eq!(value[0]["unreadable"], true);
    assert!(value[0]["error"].as_str().unwrap().contains("version"));
}

#[test]
fn adversarial_lengths_varints_and_block_counts_are_bounded() {
    let mut bytes = HEADER.to_vec();
    bytes.extend(u32::MAX.to_le_bytes());
    bytes.extend([0, 1, 1, 0]);
    assert!(decode(&bytes).is_err());
    let mut overflow_id = vec![0x1f, 1];
    overflow_id.extend([0xff; 10]);
    let v = decode(&block(0, 1, &overflow_id)).unwrap();
    assert_eq!(v[0]["unreadable"], true);
    assert!(v[0]["error"].as_str().unwrap().contains("overflow"));
    let mut many = HEADER.to_vec();
    for _ in 0..100_001 {
        many.extend([0, 0, 0, 0, 0, 1, 1, 99]);
    }
    assert!(decode(&many).unwrap_err().contains("100000"));
}

#[test]
fn all_truncated_prefixes_are_safe_and_nested_extras_survive() {
    // Parent reference is followed by unknown data inside a valid subblock.
    let body = [
        0x1f, 1, 2, 0x2f, 1, 3, 0x31, 0, 0x4c, 4, 0, 0, 0, 0x1f, 0, 1, 0xab,
    ];
    let bytes = block(1, 1, &body);
    let value = decode(&bytes).unwrap();
    assert_eq!(value[0]["nested_extra"][0]["hex"], "ab");
    for size in 0..bytes.len() {
        let _ = decode(&bytes[..size]);
    }
}

fn line_page(version: u8, points: &[u8], thickness: f64) -> Vec<u8> {
    let mut line = vec![3, 0x14];
    line.extend(14u32.to_le_bytes());
    line.push(0x24);
    line.extend(0u32.to_le_bytes());
    line.push(0x38);
    line.extend(thickness.to_le_bytes());
    line.push(0x44);
    line.extend(0f32.to_le_bytes());
    line.push(0x5c);
    line.extend((points.len() as u32).to_le_bytes());
    line.extend(points);
    line.extend([0x6f, 0, 1]);
    let mut scene = vec![
        0x1f, 0, 11, 0x2f, 1, 1, 0x3f, 0, 0, 0x4f, 0, 0, 0x54, 0, 0, 0, 0, 0x6c,
    ];
    scene.extend((line.len() as u32).to_le_bytes());
    scene.extend(line);
    block(5, version, &scene)
}

#[test]
fn nonfinite_points_and_unknown_line_layouts_do_not_render_as_partial_ink() {
    let mut point = vec![0u8; 14];
    let valid = decode(&line_page(2, &point, 1.)).unwrap();
    assert_eq!(valid[0]["unreadable"], false);
    point[..4].copy_from_slice(&f32::NAN.to_le_bytes());
    let bad = decode(&line_page(2, &point, 1.)).unwrap();
    assert_eq!(bad[0]["unreadable"], true);
    assert!(bad[0]["error"].as_str().unwrap().contains("Nonfinite"));
    assert_eq!(
        decode(&line_page(2, &[], f64::INFINITY)).unwrap()[0]["unreadable"],
        true
    );
    assert_eq!(
        decode(&line_page(2, &[0], 1.)).unwrap()[0]["unreadable"],
        true
    );
    assert_eq!(
        decode(&line_page(3, &[], 1.)).unwrap()[0]["unreadable"],
        true
    );
}

#[test]
#[ignore = "requires generated Python reference cases via RMDOC_V6_DIFFERENTIAL"]
fn python_differential_cases() {
    let path = std::env::var("RMDOC_V6_DIFFERENTIAL").unwrap();
    let data: serde_json::Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    for case in data.as_array().unwrap() {
        let bytes: Vec<u8> = case["raw"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n.as_u64().unwrap() as u8)
            .collect();
        let got = decode(&bytes).unwrap();
        let expected = case["expected"].as_array().unwrap();
        assert_eq!(got.as_array().unwrap().len(), expected.len());
        for (actual, want) in got.as_array().unwrap().iter().zip(expected) {
            assert_eq!(
                actual["unreadable"], want["unreadable"],
                "{} block {}",
                case["name"], actual["index"]
            );
            if want["unreadable"] == false {
                assert_eq!(
                    actual["fields"], want["fields"],
                    "{} block {}",
                    case["name"], actual["index"]
                );
                assert_eq!(actual["extra_data_hex"], want["extra_data_hex"]);
                assert_eq!(actual["extra_value_data_hex"], want["extra_value_data_hex"]);
            } else {
                assert_eq!(actual["raw_hex"], want["raw_hex"]);
            }
        }
    }
}
