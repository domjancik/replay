use crate::{
    geometry,
    model::{Request, Viewport},
    texture,
};
use std::collections::HashSet;

pub const MAX_PIXELS: usize = 16 * 1024 * 1024;
const MAX_STROKES: usize = 100_000;
const MAX_LAYERS: usize = 10_000;
const MAX_POINTS: usize = 500_000;
const MAX_PATH_LENGTH: f64 = 2_000_000.0;
const MAX_RASTER_COORDINATE: f64 = 1e8;
const MAX_RASTER_WIDTH: f64 = 65_536.0;
// Missing eraser widths default to one source unit. Textures also have a
// minimum dab radius, so explicit zero width still requires bounded scaling.
const MAX_RASTER_SCALE: f64 = MAX_RASTER_WIDTH;

pub fn validate(request: &Request) -> Result<Viewport, String> {
    let paper = request.page.paper_size;
    if let Some(size) = paper {
        if size
            .iter()
            .any(|v| !v.is_finite() || *v <= 0.0 || *v > 16384.0)
        {
            return Err("paper_size must contain positive finite dimensions up to 16384".into());
        }
    }
    let viewport = match request.options.viewport {
        Some(v) => v,
        None => match paper {
            Some([w, h]) => Viewport {
                width: w.round_ties_even() as usize,
                height: h.round_ties_even() as usize,
            },
            None => return Err("page without paper_size requires an explicit viewport".into()),
        },
    };
    checked_size(viewport.width, viewport.height)?;
    if let Some(v) = &request.visibility {
        if !v.active_progress.is_finite() || !(0.0..=1.0).contains(&v.active_progress) {
            return Err("active_progress must be finite and between zero and one".into());
        }
    }
    if request.page.strokes.len() > MAX_STROKES
        || request.page.groups.len() > MAX_LAYERS
        || request.page.compositing_order.len() > MAX_LAYERS
    {
        return Err("page exceeds the stroke or layer limit".into());
    }
    let order: HashSet<_> = request.page.compositing_order.iter().collect();
    if order.len() != request.page.compositing_order.len() {
        return Err("compositing order contains a duplicate layer".into());
    }
    let canvas = composition_size(request, viewport);
    checked_size(canvas.width, canvas.height)?;
    let (sx, sy) = paper.map_or((1.0, 1.0), |[width, height]| {
        (canvas.width as f64 / width, canvas.height as f64 / height)
    });
    if [sx, sy]
        .into_iter()
        .any(|scale| !scale.is_finite() || scale > MAX_RASTER_SCALE)
    {
        return Err("paper size produces a raster scale above the supported limit".into());
    }
    let width_scale = sx.max(sy);
    let mut point_count = 0usize;
    let mut path_length = 0.0;
    for stroke in &request.page.strokes {
        if !stroke.thickness_scale.is_finite() || stroke.thickness_scale.abs() > 100_000.0 {
            return Err("stroke thickness is outside the supported range".into());
        }
        point_count = point_count.saturating_add(stroke.points.len());
        if point_count > MAX_POINTS {
            return Err("page exceeds 500000 points".into());
        }
        if stroke.thickness_scale.abs() * width_scale > MAX_RASTER_WIDTH {
            return Err("raster stroke width exceeds 65536 pixels".into());
        }
        let ballpoint = matches!(stroke.tool_code, Some(2 | 15))
            || matches!(
                stroke.tool_name.as_deref(),
                Some("BALLPOINT" | "BALLPOINT_2")
            );
        let mut max_width: f64 = 0.0;
        let mut max_pressure: f64 = 0.0;
        let mut max_speed_gain: f64 = 0.0;
        let mut has_width = false;
        let mut has_speed = false;
        for p in &stroke.points {
            if [p.x, p.y, p.pressure]
                .iter()
                .any(|v| !v.is_finite() || v.abs() > 1e7)
                || [p.width, p.speed, p.direction]
                    .iter()
                    .flatten()
                    .any(|v| !v.is_finite() || v.abs() > 100_000.0)
            {
                return Err("point channels are outside the finite supported range".into());
            }
            if (p.x * sx).abs() > MAX_RASTER_COORDINATE || (p.y * sy).abs() > MAX_RASTER_COORDINATE
            {
                return Err("raster coordinates exceed the supported range".into());
            }
            if let Some(width) = p.width {
                has_width = true;
                max_width = max_width.max(width.abs() / 4.0);
            }
            if ballpoint {
                max_pressure = max_pressure.max(p.pressure.clamp(0.0, 255.0) / 255.0);
                if let Some(speed) = p.speed {
                    has_speed = true;
                    max_speed_gain = max_speed_gain.max(-speed / 400.0);
                }
            }
        }
        // A reveal endpoint can inherit missing channels from different
        // neighbors, so each contributing term needs its own upper bound.
        if ballpoint && has_width && has_speed {
            max_width += 0.5 + max_pressure + max_speed_gain;
        }
        if max_width * width_scale > MAX_RASTER_WIDTH {
            return Err("raster stroke width exceeds 65536 pixels".into());
        }
        path_length += geometry::length(&stroke.points);
        if path_length > MAX_PATH_LENGTH {
            return Err("total path length exceeds 2000000 source units".into());
        }
    }
    Ok(viewport)
}

/// Resolve the canvas that holds source-resolution ink before the final BOX reduction.
pub fn composition_size(request: &Request, viewport: Viewport) -> Viewport {
    let page = &request.page;
    let Some([width, height]) = page.paper_size else {
        return viewport;
    };
    let ordered: HashSet<_> = page.compositing_order.iter().map(String::as_str).collect();
    let eligible: HashSet<_> = page
        .groups
        .iter()
        .filter(|group| group.visible && ordered.contains(group.group_id.as_str()))
        .map(|group| group.group_id.as_str())
        .collect();
    if page.strokes.iter().any(|stroke| {
        eligible.contains(stroke.group_id.as_str())
            && texture::needs_source_composition(stroke, request.options.pencil_boundary)
    }) {
        Viewport {
            width: viewport.width.max(width.round_ties_even() as usize),
            height: viewport.height.max(height.round_ties_even() as usize),
        }
    } else {
        viewport
    }
}

pub fn checked_size(width: usize, height: usize) -> Result<(), String> {
    if width == 0
        || height == 0
        || width > 16384
        || height > 16384
        || width.checked_mul(height).is_none_or(|p| p > MAX_PIXELS)
    {
        Err("canvas exceeds the 16-million-pixel or 16384-axis limit".into())
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request() -> Request {
        serde_json::from_str(r#"{"page":{"page_id":"x","paper_size":[31.5,20.5],"groups":[],"strokes":[],"compositing_order":[]}}"#).unwrap()
    }
    #[test]
    fn resolves_ties_even_and_rejects_unbounded_geometry() {
        let mut req = request();
        let vp = validate(&req).unwrap();
        assert_eq!((vp.width, vp.height), (32, 20));
        req.page.paper_size = Some([0.0, 20.0]);
        assert!(validate(&req).is_err());
        req.page.paper_size = Some([1e9, 20.0]);
        assert!(validate(&req).is_err());
        req = request();
        req.options.viewport = Some(Viewport {
            width: usize::MAX,
            height: 20,
        });
        assert!(validate(&req).is_err());
        req = request();
        req.visibility = Some(crate::model::Visibility {
            active_progress: f64::NAN,
            ..Default::default()
        });
        assert!(validate(&req).is_err());
    }

    #[test]
    fn limits_total_path_length_across_strokes_at_the_boundary() {
        let mut req = request();
        let stroke = |id: &str, end: f64| {
            serde_json::from_value(serde_json::json!({
                "stroke_id": id,
                "group_id": "ink",
                "rgba": [0, 0, 0, 255],
                "thickness_scale": 1.0,
                "tool_code": 14,
                "points": [{"x": 0.0, "y": 0.0}, {"x": end, "y": 0.0}]
            }))
            .unwrap()
        };
        req.page.strokes = vec![stroke("one", 1_000_000.0), stroke("two", 1_000_000.0)];
        assert!(validate(&req).is_ok());
        req.page.strokes[1].points[1].x += 0.5;
        assert!(validate(&req).unwrap_err().contains("path length"));
    }

    #[test]
    fn rejects_duplicate_compositing_groups() {
        let mut req = request();
        req.page.compositing_order = vec!["ink".into(), "ink".into()];
        assert!(validate(&req).unwrap_err().contains("duplicate"));
    }

    #[test]
    fn rejects_excessive_compositing_order_even_with_no_groups() {
        let mut req = request();
        req.page.compositing_order = (0..10_001).map(|index| index.to_string()).collect();
        assert!(validate(&req).unwrap_err().contains("layer limit"));
    }

    #[test]
    fn rejects_oversized_raster_space_coordinates_and_widths() {
        let mut req = request();
        req.page.paper_size = Some([0.001, 20.0]);
        req.options.viewport = Some(Viewport {
            width: 32,
            height: 20,
        });
        req.page.strokes = vec![serde_json::from_str(r#"{"stroke_id":"s","group_id":"ink","rgba":[0,0,0,255],"thickness_scale":1,"points":[{"x":4000,"y":0,"width":4}]}"#).unwrap()];
        assert!(validate(&req).unwrap_err().contains("raster coordinates"));
        req.page.strokes[0].points[0].x = 0.0;
        req.page.strokes[0].points[0].width = Some(100_000.0);
        assert!(validate(&req).unwrap_err().contains("raster stroke width"));
        req.page.strokes.clear();
        req.page.paper_size = Some([f64::MIN_POSITIVE, 20.0]);
        assert!(validate(&req).unwrap_err().contains("raster scale"));
    }

    #[test]
    fn rejects_large_finite_scales_even_with_implicit_tool_widths() {
        let mut req = request();
        req.page.paper_size = Some([1e-12, 1e-12]);
        req.options.viewport = Some(Viewport {
            width: 1,
            height: 1,
        });
        req.page.strokes = vec![serde_json::from_str(r#"{"stroke_id":"s","group_id":"ink","rgba":[0,0,0,255],"thickness_scale":0,"tool_code":6,"points":[{"x":0,"y":0},{"x":1e-12,"y":0}]}"#).unwrap()];
        assert!(validate(&req).unwrap_err().contains("raster scale"));
    }

    #[test]
    fn limits_ballpoint_width_added_by_speed_and_pressure() {
        let mut req = request();
        req.page.paper_size = Some([0.001, 0.001]);
        req.options.viewport = Some(Viewport {
            width: 1,
            height: 1,
        });
        req.page.strokes = vec![serde_json::from_str(r#"{"stroke_id":"s","group_id":"ink","rgba":[0,0,0,255],"thickness_scale":0,"tool_name":"BALLPOINT_2","points":[{"x":0,"y":0,"width":0,"speed":100000,"pressure":255}]}"#).unwrap()];
        assert!(validate(&req).is_ok());
        req.page.strokes[0].points[0].speed = Some(-100_000.0);
        assert!(validate(&req).unwrap_err().contains("raster stroke width"));
    }

    #[test]
    fn bounds_ballpoint_channels_combined_at_partial_endpoints() {
        let mut req = request();
        req.page.paper_size = Some([0.001, 0.001]);
        req.options.viewport = Some(Viewport {
            width: 1,
            height: 1,
        });
        req.page.strokes = vec![serde_json::from_str(r#"{"stroke_id":"s","group_id":"ink","rgba":[0,0,0,255],"thickness_scale":0,"tool_code":15,"points":[{"x":0,"y":0,"width":4,"speed":0},{"x":0.001,"y":0,"speed":-100000}]}"#).unwrap()];
        assert!(validate(&req).unwrap_err().contains("raster stroke width"));
    }
}
