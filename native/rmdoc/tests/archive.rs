use rm_rmdoc::archive::{inspect, page_bytes};
use serde_json::json;
use std::io::{Cursor, Write};
use zip::{write::SimpleFileOptions, CompressionMethod, ZipWriter};

fn archive(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    for (name, data) in entries {
        writer
            .start_file(
                *name,
                SimpleFileOptions::default().compression_method(CompressionMethod::Deflated),
            )
            .unwrap();
        writer.write_all(data).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

#[test]
fn preserves_recorded_page_order_missing_pages_name_and_hash() {
    let raw = archive(&[
        (
            "doc.content",
            br#"{"pages":["b","a","missing"],"future":{"v":7}}"#,
        ),
        ("doc.metadata", br#"{"visibleName":"Example"}"#),
        ("doc/a.rm", b"alpha"),
        ("doc/b.rm", b"beta"),
    ]);
    let result = inspect(&raw).unwrap();
    assert_eq!(result["name"], "Example");
    assert_eq!(result["has_pdf"], false);
    assert_eq!(
        result["pages"],
        json!([
        {"id":"b","number":1,"available":true,"member":"doc/b.rm"},
        {"id":"a","number":2,"available":true,"member":"doc/a.rm"},
        {"id":"missing","number":3,"available":false,"member":null}])
    );
    assert_eq!(result["sha256"].as_str().unwrap().len(), 64);
    assert!(result.get("member_hashes").is_none());
    assert_eq!(page_bytes(&raw, "doc/b.rm").unwrap(), b"beta");
}

#[test]
fn current_pages_filter_deleted_and_sort_only_complete_string_indices() {
    let raw=archive(&[("doc.content",br#"{"cPages":{"pages":[{"id":"b","idx":{"value":"b"}},{"id":"gone","deleted":{"value":true}},{"id":"a","idx":{"value":"a"}}]}}"#)]);
    let result = inspect(&raw).unwrap();
    assert_eq!(result["pages"][0]["id"], "a");
    assert_eq!(result["pages"][1]["id"], "b");
    let raw = archive(&[(
        "doc.content",
        br#"{"cPages":{"pages":[{"id":"b"},{"id":"a","idx":{"value":"a"}}]}}"#,
    )]);
    assert_eq!(inspect(&raw).unwrap()["pages"][0]["id"], "b");
}

#[test]
fn rejects_unsafe_names_bad_metadata_and_duplicate_page_ids() {
    for name in ["../bad", "/bad", "x\\bad", "C:bad"] {
        let raw = archive(&[("doc.content", br#"{"pages":["a"]}"#), (name, b"")]);
        assert!(inspect(&raw).is_err(), "{name}");
        assert!(page_bytes(&raw, "doc.content").is_err());
    }
    for content in [
        r#"[]"#,
        r#"{"pages":"a"}"#,
        r#"{"pages":["a","a"]}"#,
        r#"{"pages":[1]}"#,
        r#"{"cPages":{"pages":[{"id":"a","deleted":true}]}}"#,
    ] {
        assert!(
            inspect(&archive(&[("doc.content", content.as_bytes())])).is_err(),
            "{content}"
        );
    }
    let raw = archive(&[
        ("doc.content", br#"{"pages":["a"]}"#),
        ("one/a.rm", b""),
        ("two/a.rm", b""),
    ]);
    assert!(inspect(&raw).unwrap_err().contains("Duplicate .rm"));
    assert!(inspect(b"not a ZIP").is_err());
}

#[test]
fn rejects_duplicate_member_names_and_corrupt_payload() {
    let mut raw = archive(&[
        ("doc.content", br#"{"pages":["a"]}"#),
        ("a.rm", b"alpha"),
        ("b.rm", b"beta"),
    ]);
    for i in 0..raw.len() - 4 {
        if &raw[i..i + 4] == b"b.rm" {
            raw[i] = b'a';
        }
    }
    assert!(inspect(&raw).is_err());
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .start_file(
            "doc.content",
            SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
        )
        .unwrap();
    writer.write_all(br#"{"pages":["a"]}"#).unwrap();
    let mut corrupt = writer.finish().unwrap().into_inner();
    let offset = corrupt.windows(5).position(|w| w == b"pages").unwrap();
    corrupt[offset] = b'P';
    assert!(inspect(&corrupt).is_err());
}

#[test]
fn metadata_is_retained_and_directory_envelope_is_bounded() {
    let raw = archive(&[("doc.content", br#"{"pages":["a"],"future":{"flag":7}}"#)]);
    assert_eq!(
        rm_rmdoc::archive::metadata(&raw).unwrap()["doc.content"]["future"]["flag"],
        7
    );
    let end = raw.len() - 22;
    let mut wrong_count = raw.clone();
    wrong_count[end + 8..end + 12].copy_from_slice(&[2, 0, 2, 0]);
    assert!(inspect(&wrong_count).is_err());
    let mut zip64 = raw.clone();
    zip64[end + 10..end + 12].copy_from_slice(&[255, 255]);
    assert!(inspect(&zip64).unwrap_err().contains("ZIP64"));
    let mut split = raw.clone();
    split[end + 4] = 1;
    assert!(inspect(&split).unwrap_err().contains("Multidisk"));
    let mut huge = raw.clone();
    let central = huge.windows(4).position(|b| b == b"PK\x01\x02").unwrap();
    huge[central + 24..central + 28].copy_from_slice(&(513u32 * 1024 * 1024).to_le_bytes());
    assert!(inspect(&huge).unwrap_err().contains("Expanded notebook"));
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .start_file(
            "doc.content",
            SimpleFileOptions::default()
                .large_file(true)
                .compression_method(CompressionMethod::Stored),
        )
        .unwrap();
    writer.write_all(br#"{"pages":["a"]}"#).unwrap();
    let mut large = writer.finish().unwrap().into_inner();
    assert!(inspect(&large).unwrap_err().contains("ZIP64"));
    let central = large.windows(4).position(|b| b == b"PK\x01\x02").unwrap();
    let size = br#"{"pages":["a"]}"#.len() as u32;
    large[central + 20..central + 24].copy_from_slice(&size.to_le_bytes());
    large[central + 24..central + 28].copy_from_slice(&size.to_le_bytes());
    assert!(inspect(&large).is_ok());
}
