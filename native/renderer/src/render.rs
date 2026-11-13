use crate::{
    geometry,
    model::{Request, Stroke},
    raster::{Filter, Image},
    texture,
};
use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
};

pub fn render(request: &Request) -> Result<Image, String> {
    let viewport = crate::validation::validate(request)?;
    let page = &request.page;
    let visible: HashSet<&str> = page
        .groups
        .iter()
        .filter(|g| g.visible)
        .map(|g| g.group_id.as_str())
        .collect();
    let size = crate::validation::composition_size(request, viewport);
    let (width, height) = (size.width, size.height);
    let mut image = Image::new(width, height, request.options.background);
    let mut by_group: HashMap<&str, Vec<&Stroke>> = HashMap::new();
    for stroke in &page.strokes {
        by_group.entry(&stroke.group_id).or_default().push(stroke);
    }
    let completed: HashSet<&str> = match &request.visibility {
        Some(v) => v.completed_stroke_ids.iter().map(String::as_str).collect(),
        None => page.strokes.iter().map(|s| s.stroke_id.as_str()).collect(),
    };
    for group in &page.compositing_order {
        if !visible.contains(group.as_str()) {
            continue;
        }
        let pending: Vec<_> = by_group
            .get(group.as_str())
            .into_iter()
            .flatten()
            .filter_map(|stroke| {
                let points: Cow<'_, [crate::model::Point]> =
                    if completed.contains(stroke.stroke_id.as_str()) {
                        Cow::Borrowed(stroke.points.as_slice())
                    } else if let Some(v) = &request.visibility {
                        if v.active_stroke_id.as_ref() == Some(&stroke.stroke_id) {
                            Cow::Owned(geometry::prefix_points(stroke, v.active_progress))
                        } else {
                            Cow::Borrowed(&[])
                        }
                    } else {
                        Cow::Borrowed(&[])
                    };
                if points.is_empty() {
                    None
                } else {
                    Some((*stroke, points))
                }
            })
            .collect();
        if pending.is_empty() {
            continue;
        }
        let mut layer = Image::new(width, height, [0; 4]);
        for (stroke, points) in pending {
            let [paper_w, paper_h] = page
                .paper_size
                .ok_or("page without paper_size requires an explicit transform")?;
            let (sx, sy) = (width as f64 / paper_w, height as f64 / paper_h);
            check_scratch(stroke, width, height, sx, sy)?;
            if stroke.tool_code == Some(21) || stroke.tool_name.as_deref() == Some("CALIGRAPHY") {
                crate::calligraphy::draw(&mut layer, &points, stroke, sx, sy);
            } else if matches!(stroke.tool_code, Some(16 | 17 | 18))
                || matches!(
                    stroke.tool_name.as_deref(),
                    Some("MARKER_2" | "FINELINER_2" | "HIGHLIGHTER_2")
                )
            {
                crate::simple::draw(&mut layer, &points, stroke, sx, sy);
            } else if texture::is_textured(stroke) {
                texture::draw(
                    &mut layer,
                    stroke,
                    geometry::length(&points),
                    sx,
                    sy,
                    request.options.pencil_boundary,
                );
            } else {
                crate::generic::draw(&mut layer, &points, stroke, sx, sy);
            }
        }
        image.alpha_composite(&layer, 0, 0);
    }
    if (width, height) != (viewport.width, viewport.height) {
        image = image.resized(viewport.width, viewport.height, Filter::Box);
    }
    Ok(image)
}

fn check_scratch(
    stroke: &Stroke,
    width: usize,
    height: usize,
    sx: f64,
    sy: f64,
) -> Result<(), String> {
    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;
    let mut extent = stroke.thickness_scale.abs().max(1.0);
    for p in &stroke.points {
        min_x = min_x.min(p.x * sx);
        max_x = max_x.max(p.x * sx);
        min_y = min_y.min(p.y * sy);
        max_y = max_y.max(p.y * sy);
        extent = extent.max(p.width.unwrap_or(stroke.thickness_scale * 4.0).abs() / 4.0);
    }
    let margin = extent * sx.max(sy) * 2.0 + 20.0;
    let left = (min_x - margin).floor().clamp(0.0, width as f64) as usize;
    let right = (max_x + margin).ceil().clamp(0.0, width as f64) as usize;
    let top = (min_y - margin).floor().clamp(0.0, height as f64) as usize;
    let bottom = (max_y + margin).ceil().clamp(0.0, height as f64) as usize;
    if right.saturating_sub(left) * bottom.saturating_sub(top) > 4 * 1024 * 1024 {
        Err("stroke scratch buffer exceeds the 64-million-sample limit; reduce canvas size".into())
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Visibility;
    fn sample() -> Request {
        serde_json::from_str(r#"{"page":{"page_id":"x","paper_size":[128,96],"groups":[{"group_id":"g","visible":true}],"compositing_order":["g"],"strokes":[{"stroke_id":"s","group_id":"g","rgba":[0,0,0,255],"thickness_scale":1,"tool_code":14,"points":[{"x":20,"y":20,"width":40,"pressure":255},{"x":100,"y":70,"width":40,"pressure":255}]}]},"options":{"viewport":{"width":64,"height":48}}}"#).unwrap()
    }
    #[test]
    fn visible_ink_hidden_layers_and_final_static_equivalence() {
        let mut request = sample();
        let static_image = render(&request).unwrap();
        assert!(static_image.data != Image::new(64, 48, [255; 4]).data);
        request.visibility = Some(Visibility {
            completed_stroke_ids: vec!["s".into()],
            ..Default::default()
        });
        assert_eq!(render(&request).unwrap().data, static_image.data);
        request.visibility = Some(Visibility {
            active_stroke_id: Some("s".into()),
            active_progress: 0.25,
            ..Default::default()
        });
        assert_ne!(render(&request).unwrap().data, static_image.data);
        request.page.groups[0].visible = false;
        assert_eq!(
            render(&request).unwrap().data,
            Image::new(64, 48, [255; 4]).data
        );
    }
}
