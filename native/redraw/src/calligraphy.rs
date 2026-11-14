//! Antialiased, swept-circle coverage for the current calligraphy profile.

use crate::model::{Point, Stroke};
use crate::raster::{extent, ink_from_mask, Bounds, Filter, Image, Mask};

pub fn draw(layer: &mut Image, points: &[Point], stroke: &Stroke, sx: f64, sy: f64) {
    let visible_length: f64 = points
        .windows(2)
        .map(|p| (p[1].x - p[0].x).hypot(p[1].y - p[0].y))
        .sum();
    if visible_length <= 0.0 || stroke.points.is_empty() {
        return;
    }
    let radii: Vec<_> = stroke
        .points
        .iter()
        .map(|p| {
            p.width
                .map_or(stroke.thickness_scale / 2.0, |w| w / 8.0)
                .max(0.0)
        })
        .collect();
    let radius = radii.iter().copied().fold(0.0, f64::max);
    if radius <= 0.0 {
        return;
    }
    let visible: Vec<_> = points.iter().map(|p| (p.x, p.y)).collect();
    let (left, top, right, bottom) = extent(&visible);
    let Some(bounds) = Bounds::clipped(
        layer,
        ((left - radius) * sx).floor() - 3.0,
        ((top - radius) * sy).floor() - 3.0,
        ((right + radius) * sx).ceil() + 3.0,
        ((bottom + radius) * sy).ceil() + 3.0,
    ) else {
        return;
    };
    const SS: usize = 4;
    let mut mask = Mask::new(bounds.width * SS, bounds.height * SS);
    let mut remaining = visible_length;
    for (index, segment) in stroke.points.windows(2).enumerate() {
        let (a, b) = (&segment[0], &segment[1]);
        let (dx, dy) = (b.x - a.x, b.y - a.y);
        let length = dx.hypot(dy);
        if length <= 0.0 {
            continue;
        }
        if remaining <= 0.0 {
            break;
        }
        let fraction = (remaining / length).min(1.0);
        remaining -= length;
        let r0 = radii[index];
        let dr = radii[index + 1] - r0;
        let end_radius = r0 + dr * fraction;
        let max_radius = r0.max(end_radius);
        if max_radius <= 0.0 {
            continue;
        }
        let end_x = a.x + dx * fraction;
        let end_y = a.y + dy * fraction;
        let x0 = bounds
            .left
            .max(((a.x.min(end_x) - max_radius) * sx).floor() as usize);
        let x1 =
            (bounds.left + bounds.width).min(((a.x.max(end_x) + max_radius) * sx).ceil() as usize);
        let y0 = bounds
            .top
            .max(((a.y.min(end_y) - max_radius) * sy).floor() as usize);
        let y1 =
            (bounds.top + bounds.height).min(((a.y.max(end_y) + max_radius) * sy).ceil() as usize);
        let denominator = dx * dx + dy * dy - dr * dr;
        for y in y0 * SS..y1 * SS {
            let py = (y as f64 + 0.5) / (SS as f64 * sy) - a.y;
            for x in x0 * SS..x1 * SS {
                let px = (x as f64 + 0.5) / (SS as f64 * sx) - a.x;
                let covered = if denominator > 0.0 {
                    let t = ((px * dx + py * dy + r0 * dr) / denominator).clamp(0.0, fraction);
                    square(px - dx * t) + square(py - dy * t) <= square(r0 + dr * t)
                } else {
                    square(px) + square(py) <= square(r0)
                        || square(px - dx * fraction) + square(py - dy * fraction)
                            <= square(end_radius)
                };
                if covered {
                    mask.data[(y - bounds.top * SS) * mask.width + x - bounds.left * SS] = 255;
                }
            }
        }
    }
    let coverage = mask.resized(bounds.width, bounds.height, Filter::Box);
    let ink = ink_from_mask(&coverage, bounds.width, bounds.height, stroke.rgba);
    layer.alpha_composite(&ink, bounds.left, bounds.top);
}

fn square(value: f64) -> f64 {
    value * value
}
