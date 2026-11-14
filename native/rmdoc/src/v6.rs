//! Bounded v6 tagged-block decoder, ported from rmscene 0.8.0 (MIT).
//! Unknown blocks and fields retain source bytes; no renderer dependency.
use serde_json::{json, Map, Value};
use std::cell::RefCell;
use std::rc::Rc;
const HEADER: &[u8] = b"reMarkable .lines file, version=6          ";
const MAX_PAGE: usize = 128 * 1024 * 1024;
type Result<T> = std::result::Result<T, String>;

struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
    offset: usize,
    extras: Rc<RefCell<Vec<Value>>>,
    point_count: Rc<RefCell<usize>>,
}
impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self {
            bytes,
            pos: 0,
            offset: 0,
            extras: Rc::default(),
            point_count: Rc::default(),
        }
    }
    fn left(&self) -> usize {
        self.bytes.len() - self.pos
    }
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.pos.checked_add(n).ok_or("Size overflow")?;
        if end > self.bytes.len() {
            return Err(format!(
                "Truncated block at byte {}",
                self.offset + self.pos
            ));
        }
        let data = &self.bytes[self.pos..end];
        self.pos = end;
        Ok(data)
    }
    fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    fn u16(&mut self) -> Result<u16> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }
    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn f32(&mut self) -> Result<f64> {
        let n = f32::from_le_bytes(self.take(4)?.try_into().unwrap()) as f64;
        finite(n)
    }
    fn f64(&mut self) -> Result<f64> {
        let n = f64::from_le_bytes(self.take(8)?.try_into().unwrap());
        finite(n)
    }
    fn var(&mut self) -> Result<u64> {
        let mut v = 0u64;
        for shift in (0..70).step_by(7) {
            let b = self.u8()?;
            if shift == 63 && b > 1 {
                return Err("Varuint overflow".into());
            }
            v |= ((b & 127) as u64) << shift;
            if b & 128 == 0 {
                return Ok(v);
            }
        }
        Err("Varuint overflow".into())
    }
    fn count(&mut self) -> Result<usize> {
        let count = self.var()?;
        if count > self.left() as u64 {
            return Err("Declared count exceeds remaining block bytes".into());
        }
        Ok(count as usize)
    }
    fn tag(&mut self, index: u64, kind: u64) -> Result<()> {
        let p = self.pos;
        let n = self.var()?;
        if n != (index << 4) | kind {
            self.pos = p;
            return Err(format!(
                "Unexpected tag {n:x}, expected {:x}",
                (index << 4) | kind
            ));
        }
        Ok(())
    }
    fn has(&self, index: u64, kind: u64) -> bool {
        let mut p = Reader::new(&self.bytes[self.pos..]);
        p.var().ok() == Some((index << 4) | kind)
    }
    fn id_raw(&mut self) -> Result<Value> {
        let a = self.u8()?;
        let b = self.var()?;
        Ok(json!({"part1":a,"part2":b,"text":format!("{a}:{b}")}))
    }
    fn id(&mut self, index: u64) -> Result<Value> {
        self.tag(index, 15)?;
        self.id_raw()
    }
    fn int(&mut self, index: u64) -> Result<u32> {
        self.tag(index, 4)?;
        self.u32()
    }
    fn byte(&mut self, index: u64) -> Result<u8> {
        self.tag(index, 1)?;
        self.u8()
    }
    fn boolean(&mut self, index: u64) -> Result<bool> {
        Ok(self.byte(index)? != 0)
    }
    fn float(&mut self, index: u64) -> Result<f64> {
        self.tag(index, 4)?;
        self.f32()
    }
    fn double(&mut self, index: u64) -> Result<f64> {
        self.tag(index, 8)?;
        self.f64()
    }
    fn sub<T>(&mut self, index: u64, f: impl FnOnce(&mut Reader) -> Result<T>) -> Result<T> {
        self.tag(index, 12)?;
        let n = self.u32()? as usize;
        let offset = self.offset + self.pos;
        let data = self.take(n)?;
        let mut r = Reader {
            bytes: data,
            pos: 0,
            offset,
            extras: self.extras.clone(),
            point_count: self.point_count.clone(),
        };
        let result = f(&mut r)?;
        if r.left() > 0 {
            self.extras
                .borrow_mut()
                .push(json!({"offset":r.offset+r.pos,"hex":hex(&r.bytes[r.pos..])}));
        }
        Ok(result)
    }
    fn string_format(&mut self, index: u64) -> Result<(String, Option<u32>)> {
        self.sub(index, |r| {
            let n = r.count()?;
            if r.u8()? != 1 {
                return Err("Invalid UTF-8 marker".into());
            }
            let s = std::str::from_utf8(r.take(n)?)
                .map_err(|_| "Invalid UTF-8")?
                .to_owned();
            let fmt = if r.has(2, 4) { Some(r.int(2)?) } else { None };
            Ok((s, fmt))
        })
    }
    fn string(&mut self, index: u64) -> Result<String> {
        Ok(self.string_format(index)?.0)
    }
    fn lww(&mut self, index: u64, kind: &str) -> Result<Value> {
        self.sub(index, |r| {
            let timestamp = r.id(1)?;
            let value = match kind {
                "id" => r.id(2)?,
                "bool" => json!(r.boolean(2)?),
                "byte" => json!(r.byte(2)?),
                "float" => json!(r.float(2)?),
                "string" => json!(r.string(2)?),
                _ => unreachable!(),
            };
            Ok(json!({"timestamp":timestamp,"value":value}))
        })
    }
    fn color(&mut self, index: u64) -> Result<Value> {
        if !self.has(index, 4) {
            return Ok(Value::Null);
        }
        let n = self.int(index)?;
        Ok(json!([
            (n >> 16) & 255,
            (n >> 8) & 255,
            n & 255,
            (n >> 24) & 255
        ]))
    }
}
fn finite(n: f64) -> Result<f64> {
    if n.is_finite() {
        Ok(n)
    } else {
        Err("Nonfinite channel".into())
    }
}
fn reserve_points(current: &mut usize, count: usize) -> Result<()> {
    let total = current.checked_add(count).ok_or("Point budget overflow")?;
    if total > 1_000_000 {
        return Err("Page exceeds one million decoded points".into());
    }
    *current = total;
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    const H: &[u8] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(H[(b >> 4) as usize] as char);
        s.push(H[(b & 15) as usize] as char);
    }
    s
}
fn enumeration(code: u32, kind: &str) -> Value {
    let name = match kind {
        "pen" => match code {
            0 => Some("PAINTBRUSH_1"),
            1 => Some("PENCIL_1"),
            2 => Some("BALLPOINT_1"),
            3 => Some("MARKER_1"),
            4 => Some("FINELINER_1"),
            5 => Some("HIGHLIGHTER_1"),
            6 => Some("ERASER"),
            7 => Some("MECHANICAL_PENCIL_1"),
            8 => Some("ERASER_AREA"),
            12 => Some("PAINTBRUSH_2"),
            13 => Some("MECHANICAL_PENCIL_2"),
            14 => Some("PENCIL_2"),
            15 => Some("BALLPOINT_2"),
            16 => Some("MARKER_2"),
            17 => Some("FINELINER_2"),
            18 => Some("HIGHLIGHTER_2"),
            21 => Some("CALIGRAPHY"),
            23 => Some("SHADER"),
            _ => None,
        },
        "color" => [
            "BLACK",
            "GRAY",
            "WHITE",
            "YELLOW",
            "GREEN",
            "PINK",
            "BLUE",
            "RED",
            "GRAY_OVERLAP",
            "HIGHLIGHT",
            "GREEN_2",
            "CYAN",
            "MAGENTA",
            "YELLOW_2",
        ]
        .get(code as usize)
        .copied(),
        _ => [
            "BASIC",
            "PLAIN",
            "HEADING",
            "BOLD",
            "BULLET",
            "BULLET2",
            "CHECKBOX",
            "CHECKBOX_CHECKED",
        ]
        .get(code as usize)
        .copied(),
    };
    json!({"code":code,"name":name})
}
fn line(r: &mut Reader, version: u8) -> Result<Value> {
    if !matches!(version, 1 | 2) {
        return Err(format!("Unsupported line version {version}"));
    }
    let tool = enumeration(r.int(1)?, "pen");
    let color = enumeration(r.int(2)?, "color");
    let thickness_scale = r.double(3)?;
    let starting_length = r.float(4)?;
    let points = r.sub(5, |p| {
        let size = if version == 1 { 24 } else { 14 };
        if p.left() % size != 0 {
            return Err("Point data size mismatch".into());
        }
        let count = p.left() / size;
        reserve_points(&mut p.point_count.borrow_mut(), count)?;
        let mut points = Vec::with_capacity(count);
        while p.left() > 0 {
            let x = p.f32()?;
            let y = p.f32()?;
            let (speed, width, direction, pressure) = if version == 1 {
                let speed = p.f32()? * 4.;
                let direction = 255. * p.f32()? / (std::f64::consts::PI * 2.);
                let width = (p.f32()? * 4.).round_ties_even();
                let pressure = p.f32()? * 255.;
                (speed, width, direction, pressure)
            } else {
                (
                    p.u16()? as f64,
                    p.u16()? as f64,
                    p.u8()? as f64,
                    p.u8()? as f64,
                )
            };
            if width.abs() >= i64::MAX as f64 {
                return Err("Point width exceeds integer range".into());
            }
            let mut point = json!({
                "x": x, "y": y, "speed": speed, "width": width as i64,
                "direction": direction, "pressure": pressure
            });
            if version == 2 {
                point["speed"] = json!(speed as u16);
                point["direction"] = json!(direction as u8);
                point["pressure"] = json!(pressure as u8);
            }
            points.push(point);
        }
        Ok(points)
    })?;
    let _timestamp = r.id(6)?;
    let move_id = if r.has(7, 15) { r.id(7)? } else { Value::Null };
    let color_rgba = r.color(8)?;
    Ok(
        json!({"color":color,"tool":tool,"points":points,"thickness_scale":thickness_scale,"starting_length":starting_length,"move_id":move_id,"color_rgba":color_rgba}),
    )
}
fn glyph(r: &mut Reader) -> Result<Value> {
    let start = if r.has(2, 4) {
        json!(r.int(2)?)
    } else {
        Value::Null
    };
    let len = if r.has(3, 4) { Some(r.int(3)?) } else { None };
    let color = enumeration(r.int(4)?, "color");
    let text = r.string(5)?;
    let length = len.map(u64::from).unwrap_or(text.chars().count() as u64);
    let rectangles = r.sub(6, |r| {
        let count = r.count()?;
        if count > r.left() / 32 {
            return Err("Invalid rectangle count".into());
        }
        let mut out = Vec::with_capacity(count);
        for _ in 0..count {
            out.push(json!({"x":r.f64()?,"y":r.f64()?,"w":r.f64()?,"h":r.f64()?}));
        }
        Ok(out)
    })?;
    let color_rgba = r.color(10)?;
    Ok(
        json!({"start":start,"length":length,"text":text,"color":color,"rectangles":rectangles,"color_rgba":color_rgba}),
    )
}
fn scene_item(r: &mut Reader, kind: u8, version: u8) -> Result<(Value, Value)> {
    let parent_id = r.id(1)?;
    let item_id = r.id(2)?;
    let left_id = r.id(3)?;
    let right_id = r.id(4)?;
    let deleted_length = r.int(5)?;
    let mut extra = Value::Null;
    let value = if r.has(6, 12) {
        r.sub(6, |s| {
            let item_type = s.u8()?;
            let expected = match kind {
                3 => 1,
                4 => 2,
                5 => 3,
                6 => 5,
                8 => 0,
                _ => unreachable!(),
            };
            if item_type != expected {
                return Err("Unexpected scene item type".into());
            }
            let value = match kind {
                3 => glyph(s)?,
                4 => s.id(2)?,
                5 => line(s, version)?,
                _ => Value::Null,
            };
            if s.left() > 0 {
                extra = json!(hex(&s.bytes[s.pos..]));
                s.pos = s.bytes.len();
            }
            Ok(value)
        })?
    } else {
        Value::Null
    };
    Ok((
        json!({"parent_id":parent_id,"item":{"item_id":item_id,"left_id":left_id,"right_id":right_id,"deleted_length":deleted_length,"value":value}}),
        extra,
    ))
}
fn text_item(r: &mut Reader) -> Result<Value> {
    r.sub(0,|r|{let item_id=r.id(2)?;let left_id=r.id(3)?;let right_id=r.id(4)?;let deleted_length=r.int(5)?;let value=if r.has(6,12){let (s,fmt)=r.string_format(6)?;fmt.map_or(json!(s),|n|json!(n))}else{json!("")};Ok(json!({"item_id":item_id,"left_id":left_id,"right_id":right_id,"deleted_length":deleted_length,"value":value}))})
}
fn root_text(r: &mut Reader) -> Result<Value> {
    let block_id = r.id(1)?;
    if block_id["part1"] != 0 || block_id["part2"] != 0 {
        return Err("Unexpected root text ID".into());
    }
    let (items, styles) = r.sub(2, |r| {
        let items = r.sub(1, |r| {
            r.sub(1, |r| {
                let n = r.count()?;
                if n > r.left() / 5 {
                    return Err("Invalid text item count".into());
                }
                let mut out = Vec::with_capacity(n);
                for _ in 0..n {
                    out.push(text_item(r)?);
                }
                Ok(out)
            })
        })?;
        let styles = r.sub(2, |r| {
            r.sub(1, |r| {
                let n = r.count()?;
                if n > r.left() / 6 {
                    return Err("Invalid text style count".into());
                }
                let mut out = Map::new();
                for _ in 0..n {
                    let id = r.id_raw()?;
                    let timestamp = r.id(1)?;
                    let value = r.sub(2, |r| {
                        if r.u8()? != 17 {
                            return Err("Invalid paragraph format marker".into());
                        }
                        Ok(enumeration(r.u8()? as u32, "style"))
                    })?;
                    out.insert(
                        format!("CrdtId({}, {})", id["part1"], id["part2"]),
                        json!({"timestamp":timestamp,"value":value}),
                    );
                }
                Ok(out)
            })
        })?;
        Ok((items, styles))
    })?;
    let (pos_x, pos_y) = r.sub(3, |r| Ok((r.f64()?, r.f64()?)))?;
    let width = r.float(4)?;
    Ok(
        json!({"block_id":block_id,"value":{"items":items,"styles":styles,"pos_x":pos_x,"pos_y":pos_y,"width":width}}),
    )
}
fn fields(r: &mut Reader, kind: u8, version: u8) -> Result<(Value, Value)> {
    if matches!(kind, 3 | 4 | 5 | 6 | 8) {
        return scene_item(r, kind, version);
    }
    let fields = match kind {
        0 => {
            let migration_id = r.id(1)?;
            let is_device = r.boolean(2)?;
            let unknown = if r.left() > 0 { r.boolean(3)? } else { false };
            json!({"migration_id":migration_id,"is_device":is_device,"_unknown":unknown})
        }
        1 => {
            let tree_id = r.id(1)?;
            let node_id = r.id(2)?;
            let is_update = r.boolean(3)?;
            let parent_id = r.sub(4, |r| r.id(1))?;
            json!({"tree_id":tree_id,"node_id":node_id,"is_update":is_update,"parent_id":parent_id})
        }
        2 => {
            let node_id = r.id(1)?;
            let label = r.lww(2, "string")?;
            let visible = r.lww(3, "bool")?;
            let mut group = json!({"node_id":node_id,"children":[],"label":label,"visible":visible,"anchor_id":null,"anchor_type":null,"anchor_threshold":null,"anchor_origin_x":null});
            if r.left() > 0 {
                group["anchor_id"] = r.lww(7, "id")?;
                group["anchor_type"] = r.lww(8, "byte")?;
                group["anchor_threshold"] = r.lww(9, "float")?;
                group["anchor_origin_x"] = r.lww(10, "float")?;
            }
            json!({"group":group})
        }
        7 => root_text(r)?,
        9 => {
            let n = r.count()?;
            if n > r.left() / 23 {
                return Err("Invalid author count".into());
            }
            let mut authors = Map::new();
            for _ in 0..n {
                let (id, uuid) = r.sub(0, |r| {
                    if r.var()? != 16 {
                        return Err("Invalid UUID length".into());
                    }
                    let b = r.take(16)?;
                    let uuid = format!(
                        "{:08x}-{:04x}-{:04x}-{}-{}",
                        u32::from_le_bytes(b[0..4].try_into().unwrap()),
                        u16::from_le_bytes(b[4..6].try_into().unwrap()),
                        u16::from_le_bytes(b[6..8].try_into().unwrap()),
                        hex(&b[8..10]),
                        hex(&b[10..16])
                    );
                    Ok((r.u16()?, uuid))
                })?;
                authors.insert(id.to_string(), json!(uuid));
            }
            json!({"author_uuids":authors})
        }
        10 => {
            let loads_count = r.int(1)?;
            let merges_count = r.int(2)?;
            let text_chars_count = r.int(3)?;
            let text_lines_count = r.int(4)?;
            let type_folio_use_count = if r.left() > 0 { r.int(5)? } else { 0 };
            json!({"loads_count":loads_count,"merges_count":merges_count,"text_chars_count":text_chars_count,"text_lines_count":text_lines_count,"type_folio_use_count":type_folio_use_count})
        }
        13 => {
            let current_layer = r.lww(1, "id")?;
            let background_visible = if r.left() > 0 {
                r.lww(2, "bool")?
            } else {
                Value::Null
            };
            let root_document_visible = if r.left() > 0 {
                r.lww(3, "bool")?
            } else {
                Value::Null
            };
            let paper_size = if r.left() > 0 {
                r.sub(5, |r| Ok(json!([r.u32()?, r.u32()?])))?
            } else {
                Value::Null
            };
            json!({"current_layer":current_layer,"background_visible":background_visible,"root_document_visible":root_document_visible,"paper_size":paper_size})
        }
        _ => return Err(format!("Unknown block type {kind}")),
    };
    Ok((fields, Value::Null))
}
fn block_name(kind: u8) -> &'static str {
    match kind {
        0 => "MigrationInfoBlock",
        1 => "SceneTreeBlock",
        2 => "TreeNodeBlock",
        3 => "SceneGlyphItemBlock",
        4 => "SceneGroupItemBlock",
        5 => "SceneLineItemBlock",
        6 => "SceneTextItemBlock",
        7 => "RootTextBlock",
        8 => "SceneTombstoneItemBlock",
        9 => "AuthorIdsBlock",
        10 => "PageInfoBlock",
        13 => "SceneInfo",
        _ => "UnreadableBlock",
    }
}
/// Decode supported v6 blocks, preserving unknown payloads in diagnostics.
/// Bad outer framing is an error; a malformed individual block is retained as unreadable.
pub fn decode(bytes: &[u8]) -> Result<Value> {
    if bytes.len() > MAX_PAGE {
        return Err("Page exceeds 128 MiB".into());
    }
    if !bytes.starts_with(HEADER) {
        return Err("Unsupported page header; expected version 6".into());
    }
    // Check outer framing and block count without allocating diagnostic objects.
    let mut framing = Reader::new(&bytes[HEADER.len()..]);
    let mut count = 0;
    while framing.left() > 0 {
        let size = framing.u32()? as usize;
        framing.take(4)?;
        framing.take(size)?;
        count += 1;
        if count > 100_000 {
            return Err("Page exceeds 100000 blocks".into());
        }
    }
    let mut reader = Reader::new(&bytes[HEADER.len()..]);
    let mut out = Vec::new();
    while reader.left() > 0 {
        if out.len() >= 100_000 {
            return Err("Too many blocks".into());
        }
        let size = reader.u32()? as usize;
        let unknown = reader.u8()?;
        let min_version = reader.u8()?;
        let version = reader.u8()?;
        let kind = reader.u8()?;
        if unknown != 0 || min_version > version {
            return Err("Invalid block header".into());
        }
        let payload = reader.take(size)?;
        let mut r = Reader::new(payload);
        r.point_count = reader.point_count.clone();
        let supported = if matches!(kind, 2 | 5) { 2 } else { 1 };
        let result = if min_version > supported {
            Err(format!("Unsupported required block version {min_version}"))
        } else {
            fields(&mut r, kind, version)
        };
        let mut block = json!({"type":kind,"index":out.len(),"version":version,"min_version":min_version,"block_name":block_name(kind),"unreadable":false,"error":null,"raw_hex":null,"extra_data_hex":null,"extra_value_data_hex":null,"nested_extra":[]});
        match result {
            Ok((fields, extra)) => {
                block["fields"] = fields;
                block["extra_value_data_hex"] = extra;
                if r.left() > 0 {
                    block["extra_data_hex"] = json!(hex(&payload[r.pos..]));
                }
                block["nested_extra"] = json!(*r.extras.borrow());
            }
            Err(error) => {
                block["block_name"] = json!("UnreadableBlock");
                block["unreadable"] = json!(true);
                block["error"] = json!(error);
                block["raw_hex"] = json!(hex(payload));
                block["fields"] = json!({});
            }
        }
        out.push(block);
    }
    Ok(json!(out))
}

#[cfg(test)]
mod budget_tests {
    #[test]
    fn aggregate_point_budget_checks_before_allocation() {
        let mut count = 0;
        super::reserve_points(&mut count, 600_000).unwrap();
        assert!(super::reserve_points(&mut count, 600_000).is_err());
        assert_eq!(count, 600_000);
    }
}
