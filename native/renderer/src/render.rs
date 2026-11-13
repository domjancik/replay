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
            draw_stroke(&mut layer, &points, stroke, request)?;
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

#[cfg(test)]
mod cache_tests {
    use super::*;
    #[test]
    fn invalid_request_discards_cached_state() {
        let mut request: Request = serde_json::from_str(r#"{"page":{"page_id":"x","paper_size":[2,2],"groups":[],"strokes":[],"compositing_order":[]}}"#).unwrap();
        let mut cache = CachedRenderer::default();
        cache.render(&request).unwrap();
        assert!(cache.identity.is_some());
        request.page.paper_size = Some([0.0, 2.0]);
        assert!(cache.render(&request).is_err());
        assert!(cache.identity.is_none());
    }
    #[test]
    fn cached_reveal_and_holds_equal_stateless() {
        let mut request: Request = serde_json::from_str(r#"{"page":{"page_id":"x","paper_size":[64,64],"groups":[{"group_id":"a","visible":true},{"group_id":"b","visible":true}],"compositing_order":["a","b"],"strokes":[{"stroke_id":"one","group_id":"a","rgba":[0,0,0,180],"thickness_scale":2,"tool_code":14,"points":[{"x":4,"y":4,"width":12,"pressure":180},{"x":50,"y":40,"width":20,"pressure":230}]},{"stroke_id":"two","group_id":"b","rgba":[255,255,0,180],"thickness_scale":2,"tool_code":18,"points":[{"x":5,"y":25,"width":20},{"x":50,"y":25,"width":20}]}]}}"#).unwrap();
        let mut cache = CachedRenderer::default();
        for progress in [0.2, 0.5, 0.8, 0.5, 1.0] {
            request.visibility = Some(crate::model::Visibility {
                completed_stroke_ids: vec!["two".into()],
                active_stroke_id: Some("one".into()),
                active_progress: progress,
            });
            assert_eq!(cache.render(&request).unwrap(), render(&request).unwrap());
            assert_eq!(cache.render(&request).unwrap(), render(&request).unwrap());
        }
        request.visibility = None;
        assert_eq!(cache.render(&request).unwrap(), render(&request).unwrap());
        assert!(cache.hits > 0);
    }
}

fn draw_stroke(
    layer: &mut Image,
    points: &[crate::model::Point],
    stroke: &Stroke,
    request: &Request,
) -> Result<(), String> {
    let (width, height) = (layer.width, layer.height);
    let page = &request.page;
    let [paper_w, paper_h] = page
        .paper_size
        .ok_or("page without paper_size requires an explicit transform")?;
    let (sx, sy) = (width as f64 / paper_w, height as f64 / paper_h);
    check_scratch(stroke, width, height, sx, sy)?;
    if stroke.tool_code == Some(21) || stroke.tool_name.as_deref() == Some("CALIGRAPHY") {
        crate::calligraphy::draw(layer, points, stroke, sx, sy);
    } else if matches!(stroke.tool_code, Some(16 | 17 | 18))
        || matches!(
            stroke.tool_name.as_deref(),
            Some("MARKER_2" | "FINELINER_2" | "HIGHLIGHTER_2")
        )
    {
        crate::simple::draw(layer, points, stroke, sx, sy);
    } else if texture::is_textured(stroke) {
        texture::draw(
            layer,
            stroke,
            geometry::length(points),
            sx,
            sy,
            request.options.pencil_boundary,
        );
    } else {
        crate::generic::draw(layer, points, stroke, sx, sy);
    }
    Ok(())
}

struct LayerPrefix {
    indices: Vec<usize>,
    completed: usize,
    image: Image,
}
#[derive(Default)]
pub struct CachedRenderer {
    identity: Option<(crate::model::Page, crate::model::Options)>,
    layers: Vec<LayerPrefix>,
    last_visibility: Option<Option<crate::model::Visibility>>,
    last_image: Option<Image>,
    pub hits: usize,
}
impl CachedRenderer {
    pub fn clear(&mut self) {
        *self = Self::default();
    }
    pub fn render(&mut self, request: &Request) -> Result<Image, String> {
        let result = self.render_inner(request);
        if result.is_err() {
            self.clear();
        }
        result
    }
    fn render_inner(&mut self, request: &Request) -> Result<Image, String> {
        let viewport = crate::validation::validate(request)?;
        let size = crate::validation::composition_size(request, viewport);
        let page = &request.page;
        let groups: Vec<_> = page
            .compositing_order
            .iter()
            .filter(|id| page.groups.iter().any(|g| g.visible && &g.group_id == *id))
            .collect();
        let budget = size
            .width
            .saturating_mul(size.height)
            .saturating_mul(4)
            .saturating_mul(groups.len())
            .saturating_add(
                viewport
                    .width
                    .saturating_mul(viewport.height)
                    .saturating_mul(4),
            );
        if budget > 64 * 1024 * 1024 {
            self.clear();
            return render(request);
        }
        let same = self
            .identity
            .as_ref()
            .is_some_and(|(p, o)| p == page && o == &request.options);
        if !same {
            self.clear();
            self.identity = Some((page.clone(), request.options.clone()));
            for group in groups {
                self.layers.push(LayerPrefix {
                    indices: page
                        .strokes
                        .iter()
                        .enumerate()
                        .filter_map(|(i, s)| (&s.group_id == group).then_some(i))
                        .collect(),
                    completed: 0,
                    image: Image::new(size.width, size.height, [0; 4]),
                });
            }
        }
        if self.last_visibility.as_ref() == Some(&request.visibility) {
            if let Some(image) = &self.last_image {
                self.hits += 1;
                return Ok(image.clone());
            }
        }
        let completed: HashSet<&str> = match &request.visibility {
            Some(v) => v.completed_stroke_ids.iter().map(String::as_str).collect(),
            None => page.strokes.iter().map(|s| s.stroke_id.as_str()).collect(),
        };
        let active = request
            .visibility
            .as_ref()
            .and_then(|v| v.active_stroke_id.as_deref())
            .filter(|id| !completed.contains(id));
        for layer in &self.layers {
            let count = layer
                .indices
                .iter()
                .take_while(|&&i| completed.contains(page.strokes[i].stroke_id.as_str()))
                .count();
            let total = layer
                .indices
                .iter()
                .filter(|&&i| completed.contains(page.strokes[i].stroke_id.as_str()))
                .count();
            let active_index = layer
                .indices
                .iter()
                .position(|&i| Some(page.strokes[i].stroke_id.as_str()) == active);
            if count != total || active_index.is_some_and(|i| i != count) {
                self.clear();
                return render(request);
            }
        }
        let mut result = Image::new(size.width, size.height, request.options.background);
        for layer in &mut self.layers {
            let count = layer
                .indices
                .iter()
                .take_while(|&&i| completed.contains(page.strokes[i].stroke_id.as_str()))
                .count();
            if count < layer.completed {
                layer.image = Image::new(size.width, size.height, [0; 4]);
                layer.completed = 0;
            }
            for &index in &layer.indices[layer.completed..count] {
                let stroke = &page.strokes[index];
                if !stroke.points.is_empty() {
                    draw_stroke(&mut layer.image, &stroke.points, stroke, request)?;
                }
            }
            layer.completed = count;
            if let Some(&index) = layer
                .indices
                .get(count)
                .filter(|&&i| Some(page.strokes[i].stroke_id.as_str()) == active)
            {
                let stroke = &page.strokes[index];
                let points = geometry::prefix_points(
                    stroke,
                    request.visibility.as_ref().unwrap().active_progress,
                );
                let mut partial = layer.image.clone();
                if !points.is_empty() {
                    draw_stroke(&mut partial, &points, stroke, request)?;
                }
                result.alpha_composite(&partial, 0, 0);
            } else {
                result.alpha_composite(&layer.image, 0, 0);
            }
        }
        if (size.width, size.height) != (viewport.width, viewport.height) {
            result = result.resized(viewport.width, viewport.height, Filter::Box);
        }
        self.last_visibility = Some(request.visibility.clone());
        self.last_image = Some(result.clone());
        Ok(result)
    }
}
