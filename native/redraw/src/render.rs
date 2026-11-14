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
    fn sparse_layers_keep_cache_under_budget_and_match_reverse_and_erase() {
        let mut request:Request=serde_json::from_value(serde_json::json!({"page":{"page_id":"sparse","paper_size":[128,128],"groups":[],"compositing_order":[],"strokes":[]}})).unwrap();
        for i in 0..1100 {
            let id = i.to_string();
            request.page.groups.push(crate::model::Group {
                group_id: id.clone(),
                visible: true,
            });
            request.page.compositing_order.push(id.clone());
            if i < 3 {
                request.page.strokes.push(serde_json::from_value(serde_json::json!({"stroke_id":id,"group_id":id,"rgba":[20,30,40,180],"thickness_scale":2,"tool_code":17,"points":[{"x":8,"y":10+i,"width":8},{"x":20,"y":12+i,"width":8}]})).unwrap());
            }
        }
        let mut cache = CachedRenderer::default();
        for ids in [
            vec!["0"],
            vec!["0", "1"],
            vec!["0", "1", "2"],
            vec!["0"],
            vec![],
        ] {
            request.visibility = Some(crate::model::Visibility {
                completed_stroke_ids: ids.into_iter().map(String::from).collect(),
                active_stroke_id: None,
                active_progress: 0.0,
            });
            assert_eq!(cache.render(&request).unwrap(), render(&request).unwrap());
            assert!(
                cache.identity.is_some(),
                "empty layers must not disable the entire cache"
            );
        }
    }
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

const TILE: usize = 64;
const CACHE_BYTES: usize = 64 * 1024 * 1024;
#[derive(Default)]
struct SparseImage {
    tiles: std::collections::BTreeMap<(usize, usize), Image>,
}
impl SparseImage {
    fn capture(image: &Image) -> Self {
        let mut result = Self::default();
        for y in (0..image.height).step_by(TILE) {
            for x in (0..image.width).step_by(TILE) {
                let w = TILE.min(image.width - x);
                let h = TILE.min(image.height - y);
                if !(y..y + h).any(|row| {
                    image.data[(row * image.width + x) * 4..(row * image.width + x + w) * 4]
                        .chunks_exact(4)
                        .any(|p| p[3] != 0)
                }) {
                    continue;
                }
                let mut tile = Image::new(w, h, [0; 4]);
                for row in 0..h {
                    tile.data[row * w * 4..(row + 1) * w * 4].copy_from_slice(
                        &image.data[((y + row) * image.width + x) * 4
                            ..((y + row) * image.width + x + w) * 4],
                    );
                }
                result.tiles.insert((x, y), tile);
            }
        }
        result
    }
    fn bytes(&self) -> usize {
        self.tiles.values().map(|t| t.data.len()).sum()
    }
    fn restore(&self, w: usize, h: usize) -> Image {
        let mut image = Image::new(w, h, [0; 4]);
        for (&(x, y), tile) in &self.tiles {
            for row in 0..tile.height {
                image.data[((y + row) * w + x) * 4..((y + row) * w + x + tile.width) * 4]
                    .copy_from_slice(&tile.data[row * tile.width * 4..(row + 1) * tile.width * 4]);
            }
        }
        image
    }
}
struct LayerPrefix {
    indices: Vec<usize>,
    completed: usize,
    image: SparseImage,
}
#[derive(Default)]
pub struct CachedRenderer {
    identity: Option<(crate::model::Page, crate::model::Options)>,
    layers: Vec<LayerPrefix>,
    last_visibility: Option<Option<crate::model::Visibility>>,
    last_image: Option<Image>,
    composition: Option<Image>,
    previous_partial: std::collections::BTreeSet<(usize, usize)>,
    pub hits: usize,
}
impl CachedRenderer {
    pub fn clear(&mut self) {
        *self = Self::default();
    }
    pub fn render(&mut self, request: &Request) -> Result<Image, String> {
        let result = crate::validation::validate(request)
            .and_then(|v| self.render_inner_validated(request, v, false));
        if result.is_err() {
            self.clear();
        }
        result
    }
    pub(crate) fn render_prevalidated(
        &mut self,
        request: &Request,
        viewport: crate::model::Viewport,
    ) -> Result<Image, String> {
        self.render_inner_validated(request, viewport, true)
    }
    fn render_inner_validated(
        &mut self,
        request: &Request,
        viewport: crate::model::Viewport,
        prepared: bool,
    ) -> Result<Image, String> {
        let size = crate::validation::composition_size(request, viewport);
        let page = &request.page;
        let same = self
            .identity
            .as_ref()
            .is_some_and(|(p, o)| prepared || (p == page && o == &request.options));
        if !same {
            self.clear();
            self.identity = Some((page.clone(), request.options.clone()));
            for group in &page.compositing_order {
                if !page
                    .groups
                    .iter()
                    .any(|g| g.visible && &g.group_id == group)
                {
                    continue;
                }
                self.layers.push(LayerPrefix {
                    indices: page
                        .strokes
                        .iter()
                        .enumerate()
                        .filter_map(|(i, s)| (&s.group_id == group).then_some(i))
                        .collect(),
                    completed: 0,
                    image: SparseImage::default(),
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
        let mut dirty = std::mem::take(&mut self.previous_partial);
        let mut partial = None;
        let mut prefix_bytes = self.layers.iter().map(|l| l.image.bytes()).sum::<usize>();
        for (layer_id, layer) in self.layers.iter_mut().enumerate() {
            let count = layer
                .indices
                .iter()
                .take_while(|&&i| completed.contains(page.strokes[i].stroke_id.as_str()))
                .count();
            if count != layer.completed {
                dirty.extend(layer.image.tiles.keys().copied());
                let mut image = if count < layer.completed {
                    layer.completed = 0;
                    Image::new(size.width, size.height, [0; 4])
                } else {
                    layer.image.restore(size.width, size.height)
                };
                for &i in &layer.indices[layer.completed..count] {
                    let stroke = &page.strokes[i];
                    if !stroke.points.is_empty() {
                        draw_stroke(&mut image, &stroke.points, stroke, request)?;
                    }
                }
                layer.completed = count;
                prefix_bytes -= layer.image.bytes();
                layer.image = SparseImage::capture(&image);
                prefix_bytes += layer.image.bytes();
                if prefix_bytes > CACHE_BYTES {
                    self.clear();
                    return render(request);
                }
                dirty.extend(layer.image.tiles.keys().copied());
            }
            if let Some(&i) = layer
                .indices
                .get(count)
                .filter(|&&i| Some(page.strokes[i].stroke_id.as_str()) == active)
            {
                let stroke = &page.strokes[i];
                let points = geometry::prefix_points(
                    stroke,
                    request.visibility.as_ref().unwrap().active_progress,
                );
                let mut image = layer.image.restore(size.width, size.height);
                if !points.is_empty() {
                    draw_stroke(&mut image, &points, stroke, request)?;
                }
                let image = SparseImage::capture(&image);
                self.previous_partial.extend(image.tiles.keys().copied());
                self.previous_partial
                    .extend(layer.image.tiles.keys().copied());
                dirty.extend(self.previous_partial.iter().copied());
                partial = Some((layer_id, image));
            }
        }
        let mut result = match self.composition.take() {
            Some(image) => image,
            None => {
                for layer in &self.layers {
                    dirty.extend(layer.image.tiles.keys().copied());
                }
                Image::new(size.width, size.height, request.options.background)
            }
        };
        // Only recomposite affected tiles, in the original layer order. Drawing
        // stays in global pixel coordinates, preserving texture phase and edges.
        for (x, y) in dirty {
            let w = TILE.min(size.width - x);
            let h = TILE.min(size.height - y);
            let mut tile = Image::new(w, h, request.options.background);
            for (i, layer) in self.layers.iter().enumerate() {
                let source = partial
                    .as_ref()
                    .filter(|(id, _)| *id == i)
                    .map_or(&layer.image, |(_, image)| image);
                if let Some(image) = source.tiles.get(&(x, y)) {
                    tile.alpha_composite(image, 0, 0);
                }
            }
            for row in 0..h {
                result.data[((y + row) * size.width + x) * 4..((y + row) * size.width + x + w) * 4]
                    .copy_from_slice(&tile.data[row * w * 4..(row + 1) * w * 4]);
            }
        }
        let mut retained = self.layers.iter().map(|l| l.image.bytes()).sum::<usize>();
        // Bound retained RGBA buffers; evict prefixes individually rather than
        // disabling caching for the entire page when layer count grows.
        let reserve =
            (size.width * size.height * 4).saturating_add(viewport.width * viewport.height * 4);
        let mut evicted = false;
        for layer in &mut self.layers {
            if retained.saturating_add(reserve) <= CACHE_BYTES {
                break;
            }
            retained = retained.saturating_sub(layer.image.bytes());
            layer.image = SparseImage::default();
            layer.completed = 0;
            evicted = true;
        }
        if !evicted && retained.saturating_add(reserve) <= CACHE_BYTES {
            self.composition = Some(result.clone());
        }
        if (size.width, size.height) != (viewport.width, viewport.height) {
            result = result.resized(viewport.width, viewport.height, Filter::Box);
        }
        self.last_visibility = Some(request.visibility.clone());
        if retained + result.data.len() + self.composition.as_ref().map_or(0, |i| i.data.len())
            <= CACHE_BYTES
        {
            self.last_image = Some(result.clone());
        } else {
            self.last_image = None;
        }
        Ok(result)
    }
}
