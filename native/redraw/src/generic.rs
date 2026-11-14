//! Ballpoint, eraser, and the baseline fallback for uncalibrated tools.

use crate::model::{Point, Stroke};
use crate::raster::{
    ellipse, extent, line, polygon, rectangle, Bounds, Filter, Image, Mask, Position,
};

pub fn draw(layer: &mut Image, points: &[Point], stroke: &Stroke, sx: f64, sy: f64) {
    if points.is_empty() {
        return;
    }
    let positions: Vec<_> = points.iter().map(|p| (p.x * sx, p.y * sy)).collect();
    let scale = (sx + sy) / 2.0;
    let name = stroke.tool_name.as_deref();
    if stroke.tool_code == Some(6) || name == Some("ERASER") {
        let widths: Vec<_> = points
            .iter()
            .map(|p| p.width.map_or(1.0, |w| (w / 4.0).max(0.0)) * scale)
            .collect();
        erase(layer, &positions, &widths);
    } else if matches!(stroke.tool_code, Some(2 | 15))
        || matches!(name, Some("BALLPOINT" | "BALLPOINT_2"))
    {
        ballpoint(layer, &positions, points, stroke, scale);
    } else {
        let width = raster_width(stroke.thickness_scale * scale);
        if positions.len() == 1 {
            let (x, y) = positions[0];
            let radius = f64::from(width) / 2.0;
            ellipse(
                layer,
                (x - radius, y - radius),
                (x + radius, y + radius),
                stroke.rgba,
            );
        } else {
            line(layer, &positions, width, true, stroke.rgba);
        }
    }
}

fn raster_width(width: f64) -> i32 {
    (width.round_ties_even() as i32).max(1)
}

fn erase(layer: &mut Image, positions: &[Position], widths: &[f64]) {
    if positions.iter().all(|point| *point == positions[0]) {
        return;
    }
    let radius = widths.iter().copied().fold(0.0, f64::max) / 2.0;
    if radius <= 0.0 {
        return;
    }
    let margin = std::f64::consts::SQRT_2 * radius + 2.0;
    let (left, top, right, bottom) = extent(positions);
    let Some(bounds) = Bounds::clipped(
        layer,
        (left - margin).floor(),
        (top - margin).floor(),
        (right + margin).ceil() + 1.0,
        (bottom + margin).ceil() + 1.0,
    ) else {
        return;
    };
    const SS: usize = 4;
    let mut mask = Mask::new(bounds.width * SS, bounds.height * SS);
    let local: Vec<_> = positions.iter().map(|&p| bounds.local(p, SS)).collect();
    if widths.iter().all(|&width| width == widths[0]) {
        let mut unique = local;
        unique.dedup();
        let width = raster_width(widths[0] * SS as f64);
        let radius = f64::from(width) / 2.0;
        line(&mut mask, &unique, width, true, [255]);
        square_cap(&mut mask, unique[0], unique[1], radius);
        let last = unique.len() - 1;
        square_cap(&mut mask, unique[last], unique[last - 1], radius);
    } else {
        let segments: Vec<_> = local
            .windows(2)
            .enumerate()
            .filter(|(_, pair)| pair[0] != pair[1])
            .collect();
        for (number, (index, pair)) in segments.iter().enumerate() {
            let (a, b) = (pair[0], pair[1]);
            let (dx, dy) = (b.0 - a.0, b.1 - a.1);
            let length = dx.hypot(dy);
            let (ux, uy) = (dx / length, dy / length);
            let (r0, r1) = (
                widths[*index] * SS as f64 / 2.0,
                widths[*index + 1] * SS as f64 / 2.0,
            );
            polygon(
                &mut mask,
                &[
                    (a.0 - uy * r0, a.1 + ux * r0),
                    (a.0 + uy * r0, a.1 - ux * r0),
                    (b.0 + uy * r1, b.1 - ux * r1),
                    (b.0 - uy * r1, b.1 + ux * r1),
                ],
                [255],
            );
            if number == 0 {
                square_cap(&mut mask, a, b, r0);
            }
            if number + 1 == segments.len() {
                square_cap(&mut mask, b, a, r1);
            } else {
                ellipse(&mut mask, (b.0 - r1, b.1 - r1), (b.0 + r1, b.1 + r1), [255]);
            }
        }
    }
    let coverage = mask.resized(bounds.width, bounds.height, Filter::Lanczos);
    for (row, coverage) in coverage.chunks_exact(bounds.width).enumerate() {
        let start = ((bounds.top + row) * layer.width + bounds.left) * 4;
        for (pixel, &alpha) in layer.data[start..start + bounds.width * 4]
            .chunks_exact_mut(4)
            .zip(coverage)
        {
            pixel[3] = (u16::from(pixel[3]) * (255 - u16::from(alpha)) / 255) as u8;
        }
    }
}

fn square_cap(mask: &mut Mask, (x, y): Position, neighbour: Position, radius: f64) {
    let (dx, dy) = (x - neighbour.0, y - neighbour.1);
    let length = dx.hypot(dy);
    if length == 0.0 {
        rectangle(
            mask,
            (x - radius, y - radius),
            (x + radius, y + radius),
            [255],
        );
        return;
    }
    let (ax, ay) = (dx / length * radius, dy / length * radius);
    let (nx, ny) = (-dy / length * radius, dx / length * radius);
    polygon(
        mask,
        &[
            (x - nx, y - ny),
            (x + nx, y + ny),
            (x + ax + nx, y + ay + ny),
            (x + ax - nx, y + ay - ny),
        ],
        [255],
    );
}

fn ballpoint(
    layer: &mut Image,
    positions: &[Position],
    points: &[Point],
    stroke: &Stroke,
    scale: f64,
) {
    if points
        .iter()
        .any(|p| p.width.is_none() || p.speed.is_none())
    {
        round_polyline(
            layer,
            positions,
            raster_width(stroke.thickness_scale * scale),
            stroke.rgba,
        );
        return;
    }
    let profile_widths: Vec<_> = points
        .iter()
        .step_by(5)
        .map(|point| ballpoint_width(point) * scale * 0.75)
        .collect();
    let margin = profile_widths.iter().copied().fold(0.0, f64::max) + 2.0;
    let (left, top, right, bottom) = extent(positions);
    let Some(bounds) = Bounds::clipped(
        layer,
        (left - margin).trunc(),
        (top - margin).trunc(),
        (right + margin).trunc() + 1.0,
        (bottom + margin).trunc() + 1.0,
    ) else {
        return;
    };
    const SS: usize = 2;
    let mut sampled = Image::new(bounds.width * SS, bounds.height * SS, [0; 4]);
    let local: Vec<_> = positions.iter().map(|&p| bounds.local(p, SS)).collect();
    for (block, width) in profile_widths.into_iter().enumerate() {
        let first = block * 5;
        let end = (first + 5).min(points.len());
        round_polyline(
            &mut sampled,
            &local[first.saturating_sub(1)..end],
            raster_width(width * SS as f64),
            ballpoint_color(&points[first], stroke.rgba),
        );
    }
    let ink = sampled.resized(bounds.width, bounds.height, Filter::Lanczos);
    layer.alpha_composite(&ink, bounds.left, bounds.top);
}

fn ballpoint_width(point: &Point) -> f64 {
    let pressure = point.pressure.clamp(0.0, 255.0);
    let width = point.width.expect("ballpoint sample width");
    let speed = point.speed.expect("ballpoint sample speed");
    (0.5 + pressure / 255.0 + width / 4.0 - 0.5 * (speed / 4.0 / 50.0)).max(0.25)
}

fn ballpoint_color(point: &Point, mut color: [u8; 4]) -> [u8; 4] {
    let speed = point.speed.expect("ballpoint sample speed");
    let pressure = point.pressure.clamp(0.0, 255.0);
    let intensity = (0.1 * -(speed / 4.0 / 35.0) + 1.2 * (pressure / 255.0) + 0.5).clamp(0.0, 1.0);
    let fade = (intensity - 1.0).abs().min(60.0 / 255.0);
    for channel in &mut color[..3] {
        let value = f64::from(*channel);
        *channel = (value + (255.0 - value) * fade).round_ties_even() as u8;
    }
    color
}

fn round_polyline(layer: &mut Image, positions: &[Position], width: i32, color: [u8; 4]) {
    if positions.len() > 1 {
        line(layer, positions, width, true, color);
    }
    let radius = f64::from(width) / 2.0;
    for (x, y) in [positions[0], positions[positions.len() - 1]] {
        ellipse(
            layer,
            (x - radius, y - radius),
            (x + radius, y + radius),
            color,
        );
    }
}
