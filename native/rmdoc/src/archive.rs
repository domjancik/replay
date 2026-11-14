//! Bounded, read-only notebook ZIP inspection. No filesystem extraction or acquisition.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::io::{Cursor, Read};
use zip::ZipArchive;

pub const MAX_BYTES: usize = 128 * 1024 * 1024;
const MAX_EXPANDED: u64 = 512 * 1024 * 1024;
const MAX_MEMBERS: usize = 20_000;

fn zip_error(error: impl std::fmt::Display) -> String {
    format!("Not a valid .rmdoc ZIP archive: {error}")
}

// Inspect every central-directory record before zip's name-indexed map can
// collapse duplicates. ZIP64/multidisk envelopes fail explicitly under our
// bounded notebook profile; small files using ZIP64 local size extras still work.
fn validate_central_directory(raw: &[u8]) -> Result<(), String> {
    fn u16_at(raw: &[u8], at: usize) -> Result<usize, String> {
        Ok(u16::from_le_bytes(
            raw.get(at..at + 2)
                .ok_or("Truncated ZIP directory")?
                .try_into()
                .unwrap(),
        ) as usize)
    }
    fn u32_at(raw: &[u8], at: usize) -> Result<usize, String> {
        Ok(u32::from_le_bytes(
            raw.get(at..at + 4)
                .ok_or("Truncated ZIP directory")?
                .try_into()
                .unwrap(),
        ) as usize)
    }
    let start = raw.len().saturating_sub(65_557);
    let end = (start..raw.len().saturating_sub(21))
        .rev()
        .find(|&i| {
            raw.get(i..i + 4) == Some(b"PK\x05\x06")
                && u16_at(raw, i + 20).is_ok_and(|n| i + 22 + n == raw.len())
        })
        .ok_or("Not a valid .rmdoc ZIP archive: missing end directory")?;
    if u16_at(raw, end + 4)? != 0 || u16_at(raw, end + 6)? != 0 {
        return Err("Multidisk notebook ZIP archives are unsupported".into());
    }
    let count = u16_at(raw, end + 10)?;
    let on_disk = u16_at(raw, end + 8)?;
    let size = u32_at(raw, end + 12)?;
    let offset = u32_at(raw, end + 16)?;
    if count == 0xffff
        || on_disk == 0xffff
        || size == 0xffffffff
        || offset == 0xffffffff
        || end >= 20 && raw.get(end - 20..end - 16) == Some(b"PK\x06\x07")
    {
        return Err("ZIP64 notebook directory is unsupported".into());
    }
    if count != on_disk || offset.checked_add(size) != Some(end) {
        return Err("Inconsistent notebook ZIP directory".into());
    }
    if count > MAX_MEMBERS {
        return Err("Expanded notebook exceeds the local utility limit".into());
    }
    let mut at = offset;
    let mut names = HashSet::new();
    for _ in 0..count {
        if raw.get(at..at + 4) != Some(b"PK\x01\x02") || at.checked_add(46).is_none_or(|n| n > end)
        {
            return Err("Truncated notebook ZIP directory entry".into());
        }
        let name_len = u16_at(raw, at + 28)?;
        let extra = u16_at(raw, at + 30)?;
        let comment = u16_at(raw, at + 32)?;
        if u32_at(raw, at + 20)? == 0xffffffff
            || u32_at(raw, at + 24)? == 0xffffffff
            || u32_at(raw, at + 42)? == 0xffffffff
            || u16_at(raw, at + 34)? != 0
        {
            return Err("ZIP64 or multidisk notebook member is unsupported".into());
        }
        let next = at + 46 + name_len + extra + comment;
        if next > end {
            return Err("Truncated notebook ZIP directory fields".into());
        }
        if !names.insert(&raw[at + 46..at + 46 + name_len]) {
            return Err("Notebook has duplicate archive members".into());
        }
        at = next;
    }
    if at != end {
        return Err("Notebook ZIP directory entry count mismatch".into());
    }
    Ok(())
}

fn checked_archive(raw: &[u8]) -> Result<ZipArchive<Cursor<&[u8]>>, String> {
    if raw.len() > MAX_BYTES {
        return Err("Notebook exceeds the 128 MiB limit".into());
    }
    validate_central_directory(raw)?;
    let mut archive = ZipArchive::new(Cursor::new(raw)).map_err(zip_error)?;
    if archive.len() > MAX_MEMBERS {
        return Err("Expanded notebook exceeds the local utility limit".into());
    }
    let mut expanded = 0u64;
    let mut names = HashSet::new();
    for index in 0..archive.len() {
        let file = archive.by_index_raw(index).map_err(zip_error)?;
        let name = file.name();
        if !names.insert(name.to_string()) {
            return Err("Notebook has duplicate archive members".into());
        }
        if name.starts_with('/')
            || name.split('/').any(|p| p == "..")
            || name.contains(['\\', ':', '\0'])
        {
            return Err("Notebook contains an unsafe archive member".into());
        }
        if file.encrypted() {
            return Err("Encrypted notebook archive members are unsupported".into());
        }
        expanded = expanded
            .checked_add(file.size())
            .ok_or("Expanded notebook size overflow")?;
        if expanded > MAX_EXPANDED {
            return Err("Expanded notebook exceeds the local utility limit".into());
        }
    }
    Ok(archive)
}

fn read_member(archive: &mut ZipArchive<Cursor<&[u8]>>, index: usize) -> Result<Vec<u8>, String> {
    let mut file = archive.by_index(index).map_err(zip_error)?;
    let expected = file.size();
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(expected as usize)
        .map_err(|_| "Notebook member exceeds memory budget")?;
    (&mut file)
        .take(expected + 1)
        .read_to_end(&mut bytes)
        .map_err(zip_error)?;
    if bytes.len() as u64 != expected {
        return Err("Notebook member expanded length mismatch".into());
    }
    Ok(bytes)
}

fn object(bytes: &[u8]) -> Result<Value, String> {
    let value: Value = serde_json::from_slice(bytes)
        .map_err(|_| "Invalid notebook metadata: expected a JSON object")?;
    if !value.is_object() {
        return Err("Invalid notebook metadata: expected a JSON object".into());
    }
    Ok(value)
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
fn python_string(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Null => "None".into(),
        _ => value.to_string(),
    }
}

fn page_ids(content: &Value) -> Result<Vec<String>, String> {
    let mut entries = match content.get("pages") {
        Some(Value::Array(a)) => a.clone(),
        None | Some(Value::Null) => vec![],
        _ => return Err("Invalid notebook metadata: pages must be a list".into()),
    };
    if entries.is_empty() {
        let empty = json!({});
        let current = content.get("cPages").unwrap_or(&empty);
        if !current.is_object() {
            return Err("Invalid notebook metadata: cPages must be an object".into());
        }
        entries = match current.get("pages") {
            None => vec![],
            Some(Value::Array(a)) if a.iter().all(Value::is_object) => a.clone(),
            _ => {
                return Err(
                    "Invalid notebook metadata: cPages.pages must contain page objects".into(),
                )
            }
        };
        if entries.iter().any(|e| {
            ["idx", "deleted"]
                .iter()
                .any(|key| e.get(key).is_some_and(|v| !v.is_object()))
        }) {
            return Err(
                "Invalid notebook metadata: invalid page ordering or deletion marker".into(),
            );
        }
        entries.retain(|e| !truthy(&e["deleted"]["value"]));
        if entries.iter().all(|e| e["idx"]["value"].is_string()) {
            entries.sort_by(|a, b| a["idx"]["value"].as_str().cmp(&b["idx"]["value"].as_str()));
        }
    }
    if entries.is_empty() {
        return Err("Notebook has no recorded page order".into());
    }
    let mut ids = Vec::with_capacity(entries.len());
    let mut seen = HashSet::new();
    for entry in entries {
        let id = match &entry {
            Value::String(s) => Some(s.as_str()),
            Value::Object(o) => o.get("id").and_then(Value::as_str),
            _ => {
                return Err(
                    "Invalid notebook metadata: page entries must contain identifiers".into(),
                )
            }
        }
        .ok_or("Invalid notebook metadata: invalid page identifier")?;
        if id.is_empty() || id.chars().count() > 128 {
            return Err("Invalid notebook metadata: invalid page identifier".into());
        }
        if !seen.insert(id.to_string()) {
            return Err("Duplicate ordered page identifiers".into());
        }
        ids.push(id.to_string());
    }
    Ok(ids)
}

/// Inspect an archive with the browser library's schema. Every member is read to
/// verify its CRC, including files that are not rendered. Unknown metadata remains
/// available through [`metadata`] and the immutable source bytes.
pub fn inspect(raw: &[u8]) -> Result<Value, String> {
    let mut archive = checked_archive(raw)?;
    let mut content_records = Vec::new();
    let mut metadata_records = HashMap::new();
    let mut members = HashMap::new();
    for index in 0..archive.len() {
        let file = archive.by_index_raw(index).map_err(zip_error)?;
        let name = file.name().to_owned();
        if file.is_dir() {
            continue;
        }
        drop(file);
        if name.ends_with(".content") || name.ends_with(".metadata") {
            let bytes = read_member(&mut archive, index)?;
            if name.ends_with(".content") {
                content_records.push((name, bytes));
            } else {
                metadata_records.insert(name, bytes);
            }
        } else {
            let mut file = archive.by_index(index).map_err(zip_error)?;
            let expected = file.size();
            let copied = std::io::copy(&mut (&mut file).take(expected + 1), &mut std::io::sink())
                .map_err(zip_error)?;
            if copied != expected {
                return Err("Notebook member expanded length mismatch".into());
            }
        }
        if let Some(stem) = name_for_page(&mut archive, index)? {
            let name = archive
                .by_index_raw(index)
                .map_err(zip_error)?
                .name()
                .to_owned();
            if members.insert(stem, name).is_some() {
                return Err("Duplicate .rm page identifier".into());
            }
        }
    }
    if content_records.len() != 1 {
        return Err("Expected one notebook .content record".into());
    }
    let (content_name, content_bytes) = content_records.pop().unwrap();
    let content = object(&content_bytes)?;
    let metadata_name = format!(
        "{}.metadata",
        content_name.strip_suffix(".content").unwrap()
    );
    let metadata = metadata_records
        .get(&metadata_name)
        .map(|b| object(b))
        .transpose()?
        .unwrap_or(json!({}));
    let ids = page_ids(&content)?;
    let name = metadata
        .get("visibleName")
        .filter(|v| truthy(v))
        .map(python_string)
        .unwrap_or_else(|| "Imported notebook".into())
        .chars()
        .take(240)
        .collect::<String>();
    let pages=ids.iter().enumerate().map(|(i,id)|json!({"id":id,"number":i+1,"available":members.contains_key(id),"member":members.get(id)})).collect::<Vec<_>>();
    Ok(
        json!({"name":name,"pages":pages,"sha256":format!("{:x}",Sha256::digest(raw)),"has_pdf":false}),
    )
}

fn name_for_page(
    archive: &mut ZipArchive<Cursor<&[u8]>>,
    index: usize,
) -> Result<Option<String>, String> {
    let file = archive.by_index_raw(index).map_err(zip_error)?;
    let name = file.name();
    Ok(name
        .strip_suffix(".rm")
        .map(|n| n.rsplit('/').next().unwrap_or(n).to_string()))
}

/// Read an exact member after checking all names and declared archive limits.
/// The selected member is CRC-checked and returned; nothing is written to disk.
pub fn page_bytes(raw: &[u8], member: &str) -> Result<Vec<u8>, String> {
    let mut archive = checked_archive(raw)?;
    let index = (0..archive.len())
        .find(|&i| archive.name_for_index(i).is_some_and(|n| n == member))
        .ok_or("Notebook member not found")?;
    read_member(&mut archive, index)
}

/// Preserve complete JSON content and metadata records, including future fields.
pub fn metadata(raw: &[u8]) -> Result<Value, String> {
    let mut archive = checked_archive(raw)?;
    let mut records = serde_json::Map::new();
    for index in 0..archive.len() {
        let file = archive.by_index_raw(index).map_err(zip_error)?;
        let name = file.name().to_owned();
        let is_dir = file.is_dir();
        drop(file);
        if !is_dir && (name.ends_with(".content") || name.ends_with(".metadata")) {
            records.insert(name, object(&read_member(&mut archive, index)?)?);
        }
    }
    Ok(Value::Object(records))
}
