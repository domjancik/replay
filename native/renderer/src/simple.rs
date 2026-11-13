//! Fineliner, marker and highlighter with the Python reference's pen profiles.

use crate::model::{Point, Stroke};
use crate::raster::{darken, ellipse, extent, ink_from_mask, polygon, Bounds, Filter, Image, Mask};

pub fn draw(layer: &mut Image, points: &[Point], stroke: &Stroke, sx: f64, sy: f64) {
    if points.len() < 2 {
        return;
    }
    let name = stroke.tool_name.as_deref();
    let highlighter = stroke.tool_code == Some(18) || name == Some("HIGHLIGHTER_2");
    let marker = stroke.tool_code == Some(16) || name == Some("MARKER_2");
    let fineliner = stroke.tool_code == Some(17) || name == Some("FINELINER_2");
    let positions: Vec<_> = points.iter().map(|p| (p.x * sx, p.y * sy)).collect();
    if (highlighter || marker) && positions.iter().all(|p| *p == positions[0]) {
        return;
    }
    let scale = (sx + sy) / 2.0;
    let mut widths: Vec<_> = points
        .iter()
        .map(|p| p.width.map_or(stroke.thickness_scale, |w| w / 4.0).max(0.0) * scale)
        .collect();
    if fineliner {
        let width = widths[0];
        widths.fill(width);
    }
    if marker {
        for (point, width) in points.iter().zip(&mut widths) {
            *width = if point.width.is_some_and(|w| w <= 4.0) {
                0.0
            } else {
                *width * 0.75
            };
        }
    }
    let max_width = widths.iter().copied().fold(0.0, f64::max);
    if max_width == 0.0 {
        return;
    }
    let margin = max_width / 2.0 + 3.0;
    let (left, top, right, bottom) = extent(&positions);
    let Some(bounds) = Bounds::clipped(
        layer,
        (left - margin).floor(),
        (top - margin).floor(),
        (right + margin).ceil(),
        (bottom + margin).ceil(),
    ) else {
        return;
    };
    const SS: usize = 4;
    let mut mask = Mask::new(bounds.width * SS, bounds.height * SS);
    let local: Vec<_> = positions.into_iter().map(|p| bounds.local(p, SS)).collect();
    let radii: Vec<_> = widths.into_iter().map(|w| w * SS as f64 / 2.0).collect();
    let mut previous_normal = None;
    for (i, segment) in local.windows(2).enumerate() {
        let (a, b) = (segment[0], segment[1]);
        let (dx, dy) = (b.0 - a.0, b.1 - a.1);
        let length = dx.hypot(dy);
        if length == 0.0 {
            continue;
        }
        let (nx, ny) = (-dy / length, dx / length);
        let (ra, rb) = (radii[i], radii[i + 1]);
        polygon(
            &mut mask,
            &[
                (a.0 + nx * ra, a.1 + ny * ra),
                (a.0 - nx * ra, a.1 - ny * ra),
                (b.0 - nx * rb, b.1 - ny * rb),
                (b.0 + nx * rb, b.1 + ny * rb),
            ],
            [255],
        );
        if highlighter {
            if let Some((px, py)) = previous_normal {
                polygon(
                    &mut mask,
                    &[
                        (a.0 + px * ra, a.1 + py * ra),
                        (a.0 + nx * ra, a.1 + ny * ra),
                        (a.0 - px * ra, a.1 - py * ra),
                        (a.0 - nx * ra, a.1 - ny * ra),
                    ],
                    [255],
                );
            }
        }
        previous_normal = Some((nx, ny));
    }
    if !highlighter {
        for ((x, y), radius) in local.into_iter().zip(radii) {
            ellipse(
                &mut mask,
                (x - radius, y - radius),
                (x + radius, y + radius),
                [255],
            );
        }
    }
    let coverage = mask.resized(bounds.width, bounds.height, Filter::Lanczos);
    let ink = ink_from_mask(&coverage, bounds.width, bounds.height, stroke.rgba);
    if highlighter {
        darken(layer, &ink, &bounds);
    } else {
        layer.alpha_composite(&ink, bounds.left, bounds.top);
    }
}
