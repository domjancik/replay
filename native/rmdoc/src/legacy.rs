//! Legacy version-five page adapter: layer-major file order, not chronology.
use serde_json::{json, Value};
pub const HEADER: &[u8] = b"reMarkable .lines file, version=5          ";
fn id(a: u64, b: u64) -> Value {
    json!({"part1":a,"part2":b})
}
fn enum_value(code: u32, color: bool) -> Value {
    let name = if color {
        [
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
        .copied()
    } else {
        match code {
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
        }
    };
    json!({"code":code,"name":name})
}
struct Reader<'a> {
    data: &'a [u8],
    at: usize,
}
impl Reader<'_> {
    fn u32(&mut self) -> Result<u32, String> {
        let bytes = self
            .data
            .get(self.at..self.at + 4)
            .ok_or("Truncated v5 page")?;
        self.at += 4;
        Ok(u32::from_le_bytes(bytes.try_into().unwrap()))
    }
    fn f32(&mut self) -> Result<f64, String> {
        let v = f32::from_bits(self.u32()?) as f64;
        if !v.is_finite() {
            return Err("Nonfinite v5 point channel".into());
        }
        Ok(v)
    }
}
pub fn parse(raw: &[u8], page_id: &str) -> Result<Value, String> {
    if raw.len() > 128 * 1024 * 1024 {
        return Err("v5 page exceeds 128 MiB".into());
    }
    if !raw.starts_with(HEADER) {
        return Err("Invalid v5 header".into());
    }
    let mut r = Reader {
        data: raw,
        at: HEADER.len(),
    };
    let layers = r.u32()?;
    if layers > 4096 || layers as usize * 4 > raw.len() - r.at {
        return Err("Invalid v5 layer count".into());
    }
    let transform = json!({"matrix":[1.,0.,0.,1.,0.,0.],"resolved":true,"evidence":"v5 top-left coordinates; no group transforms","anchor_ids":[]});
    let mut groups = vec![];
    let mut total_points = 0;
    let mut strokes = vec![];
    for layer_index in 0..layers {
        let layer = id(0, layer_index as u64 + 2);
        let count = r.u32()?;
        if count > 1_000_000 || count as usize * 24 > raw.len() - r.at {
            return Err("Invalid v5 stroke count".into());
        }
        groups.push(json!({"node_id":layer,"source_node_id":layer,"parent_id":id(0,1),"layer_id":layer,"kind":"layer","label":{"timestamp":id(0,0),"value":format!("Layer {}",layer_index+1)},"visible":{"timestamp":id(0,0),"value":true},"scene_order":{"item_id":layer,"left_id":id(0,0),"right_id":id(0,0),"deleted_length":0,"block_index":layer_index},"local_transform":transform,"effective_transform":transform,"extra":{"file_format":5,"synthetic_id":true,"visibility_not_recorded":true}}));
        for stroke_index in 0..count {
            let tool = r.u32()?;
            let color = r.u32()?;
            let unknown1 = r.u32()?;
            let thickness = r.f32()?;
            let unknown2 = r.u32()?;
            let points_count = r.u32()?;
            reserve_points(&mut total_points, points_count as usize)?;
            if thickness < 0. {
                return Err("Invalid v5 stroke thickness".into());
            }
            if points_count > 5_000_000 || points_count as usize * 24 > raw.len() - r.at {
                return Err("Invalid or truncated v5 point count".into());
            }
            let mut points = vec![];
            for _ in 0..points_count {
                let x = r.f32()?;
                let y = r.f32()?;
                let speed = r.f32()?;
                let direction = r.f32()?;
                let width = r.f32()?;
                let pressure = r.f32()?;
                points.push(json!({"x":x,"y":y,"speed":speed,"direction":direction,"width":width,"pressure":pressure,"extra":{"file_format":5}}));
            }
            let stroke = id(1, strokes.len() as u64 + 1);
            strokes.push(json!({"stroke_id":stroke,"parent_id":layer,"layer_id":layer,"scene_order":{"item_id":stroke,"left_id":id(0,0),"right_id":id(0,0),"deleted_length":0,"block_index":strokes.len()},"move_id":null,"tool":enum_value(tool,false),"color":enum_value(color,true),"color_rgba":null,"thickness_scale":thickness,"starting_length":0,"points":points,"effective_transform":transform,"extra":{"file_format":5,"synthetic_id":true,"layer_index":layer_index,"stroke_index":stroke_index,"legacy_unknown_fields":[unknown1,unknown2]}}));
        }
    }
    let order: Vec<_> = strokes.iter().map(|s| s["stroke_id"].clone()).collect();
    let tail = &raw[r.at..];
    let mut warnings=vec!["v5 file order is layer-major, not chronology; IDs are synthetic. Paper size and layer visibility are not encoded."];
    if !tail.is_empty() {
        warnings.push("Unparsed v5 trailing bytes retained in diagnostics.")
    }
    Ok(
        json!({"page_id":page_id,"paper_size":null,"source_to_page_transform":[1.,0.,0.,1.,0.,0.],"groups":groups,"strokes":strokes,"tombstones":[],"compositing_order":order,"replay_order":{"strategy":"scene-order","stroke_ids":order,"evidence":"v5 stored layer/stroke order, not chronology"},"metadata":{"current_layer":null,"background_visible":null,"root_document_visible":null,"authors":{},"migrations":[],"page_info":null},"diagnostics":{"blocks":[{"block_index":0,"block_type":5,"block_name":"LegacyV5","unreadable":false,"error":null,"raw_hex":null,"extra_data_hex":tail.iter().map(|b|format!("{b:02x}")).collect::<String>(),"fields":{"file_format":5,"layers":layers,"source_coordinate_origin":"top-left"}}],"warnings":warnings}}),
    )
}
fn reserve_points(total: &mut usize, count: usize) -> Result<(), String> {
    let next = total.checked_add(count).ok_or("Point count overflow")?;
    if next > 1_000_000 {
        return Err("v5 page exceeds one million points".into());
    }
    *total = next;
    Ok(())
}
#[cfg(test)]
mod budget_tests {
    #[test]
    fn accumulated_points_are_bounded() {
        let mut count = 999_999;
        assert!(super::reserve_points(&mut count, 1).is_ok());
        assert!(super::reserve_points(&mut count, 1).is_err());
    }
}
