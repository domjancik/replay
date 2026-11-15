//! Fixed source-distance texture deposition for legacy and current drawing tools.

use crate::model::{Point, Stroke};
use crate::raster::{resize_mask, Filter, Image};
use sha2::{Digest, Sha256};
use std::{f64::consts::PI, sync::OnceLock};

pub fn is_textured(stroke: &Stroke) -> bool {
    matches!(stroke.tool_code, Some(0 | 1 | 7 | 12 | 13 | 14))
        || matches!(
            stroke.tool_name.as_deref(),
            Some(
                "PAINTBRUSH_1"
                    | "PAINTBRUSH_2"
                    | "PENCIL_1"
                    | "PENCIL_2"
                    | "MECHANICAL_PENCIL_1"
                    | "MECHANICAL_PENCIL_2"
            )
        )
}

pub fn needs_source_composition(stroke: &Stroke, pencil_boundary: bool) -> bool {
    matches!(stroke.tool_code, Some(12))
        || stroke.tool_name.as_deref() == Some("PAINTBRUSH_2")
        || (!pencil_boundary
            && (matches!(stroke.tool_code, Some(13 | 14))
                || matches!(
                    stroke.tool_name.as_deref(),
                    Some("PENCIL_2" | "MECHANICAL_PENCIL_2")
                )))
}

#[derive(Clone, Copy)]
enum Profile {
    AppPencil,
    BoundaryPencil,
    CurrentBrush,
    LegacyBrush,
    LegacyPencil { mechanical: bool },
}

impl Profile {
    fn from_stroke(stroke: &Stroke, pencil_boundary: bool) -> Self {
        let name = stroke.tool_name.as_deref().unwrap_or("");
        let current = matches!(stroke.tool_code, Some(12..=14))
            || matches!(name, "PAINTBRUSH_2" | "PENCIL_2" | "MECHANICAL_PENCIL_2");
        let brush = matches!(stroke.tool_code, Some(0 | 12)) || name.starts_with("PAINTBRUSH");
        match (current, brush, pencil_boundary) {
            (true, true, _) => Self::CurrentBrush,
            (true, false, true) => Self::BoundaryPencil,
            (true, false, false) => Self::AppPencil,
            (false, true, _) => Self::LegacyBrush,
            (false, false, _) => Self::LegacyPencil {
                mechanical: stroke.tool_code == Some(7) || name.starts_with("MECHANICAL"),
            },
        }
    }

    fn supersample(self) -> usize {
        match self {
            Self::AppPencil => 4,
            Self::BoundaryPencil | Self::CurrentBrush => 2,
            Self::LegacyBrush | Self::LegacyPencil { .. } => 1,
        }
    }
}

#[derive(Clone, Copy)]
struct Bounds {
    left: usize,
    top: usize,
    right: usize,
    bottom: usize,
}

impl Bounds {
    fn scaled(self, factor: usize) -> Self {
        Self {
            left: self.left * factor,
            top: self.top * factor,
            right: self.right * factor,
            bottom: self.bottom * factor,
        }
    }

    fn width(self) -> usize {
        self.right.saturating_sub(self.left)
    }

    fn height(self) -> usize {
        self.bottom.saturating_sub(self.top)
    }
}

struct Dab {
    x: f64,
    y: f64,
    radius: f64,
    pressure: f64,
    angle: f64,
}

impl Dab {
    fn interpolate(profile: Profile, left: &Point, right: &Point, t: f64, thickness: f64) -> Self {
        let pressure = (lerp(left.pressure, right.pressure, t) / 255.0).clamp(0.0, 1.0);
        let left_width = left.width.map_or(thickness, |width| width / 4.0);
        let right_width = right.width.map_or(thickness, |width| width / 4.0);
        let mut radius = (lerp(left_width, right_width, t) / 2.0).max(0.25);
        let left_angle = left.direction.unwrap_or_default();
        let right_angle = right.direction.unwrap_or(left_angle);
        let delta = (right_angle - left_angle + 127.5).rem_euclid(255.0) - 127.5;
        let angle = (left_angle + delta * t).rem_euclid(255.0) * 2.0 * PI / 255.0;
        match profile {
            Profile::CurrentBrush => {
                let speed = lerp(
                    left.speed.unwrap_or_default(),
                    right.speed.unwrap_or_default(),
                    t,
                )
                .max(0.0);
                radius *= 0.75;
                radius *= (2.0 * pressure - 0.107).clamp(0.0, 1.0);
                radius *= (1.0 - speed / 300.0).max(0.0);
                radius *= 0.95 - 0.05 * (2.0 * angle).cos();
            }
            Profile::AppPencil | Profile::BoundaryPencil => radius *= 0.70,
            Profile::LegacyBrush => radius *= 0.35 + 0.65 * pressure,
            Profile::LegacyPencil { .. } => {}
        }
        Self {
            x: lerp(left.x, right.x, t),
            y: lerp(left.y, right.y, t),
            pressure,
            radius,
            angle,
        }
    }
}

fn lerp(left: f64, right: f64, t: f64) -> f64 {
    left + (right - left) * t
}

pub fn draw(
    layer: &mut Image,
    stroke: &Stroke,
    visible_length: f64,
    sx: f64,
    sy: f64,
    pencil_boundary: bool,
) {
    draw_with_grain(
        layer,
        stroke,
        visible_length,
        sx,
        sy,
        pencil_boundary,
        false,
    );
}

pub fn draw_with_grain(
    layer: &mut Image,
    stroke: &Stroke,
    visible_length: f64,
    sx: f64,
    sy: f64,
    pencil_boundary: bool,
    high_res_grain: bool,
) {
    let Some(first) = stroke.points.first() else {
        return;
    };
    let profile = Profile::from_stroke(stroke, pencil_boundary);
    let scale = profile.supersample();
    if scale > 1
        && stroke
            .points
            .iter()
            .all(|p| p.x == first.x && p.y == first.y)
    {
        return;
    }

    let scale_x = sx * scale as f64;
    let scale_y = sy * scale as f64;
    let mut min_x = first.x;
    let mut max_x = first.x;
    let mut min_y = first.y;
    let mut max_y = first.y;
    let mut max_width = first
        .width
        .map_or(stroke.thickness_scale, |width| width / 4.0);
    let mut reached = 0.0;
    for (left, right) in stroke.points.iter().zip(stroke.points.iter().skip(1)) {
        let length = (right.x - left.x).hypot(right.y - left.y);
        let fraction = if length == 0.0 {
            1.0
        } else {
            ((visible_length - reached + 1e-9) / length).clamp(0.0, 1.0)
        };
        let x = lerp(left.x, right.x, fraction);
        let y = lerp(left.y, right.y, fraction);
        min_x = min_x.min(x);
        max_x = max_x.max(x);
        min_y = min_y.min(y);
        max_y = max_y.max(y);
        let w0 = left
            .width
            .map_or(stroke.thickness_scale, |width| width / 4.0);
        let w1 = right
            .width
            .map_or(stroke.thickness_scale, |width| width / 4.0);
        max_width = max_width.max(w0).max(lerp(w0, w1, fraction));
        reached += length;
        if reached > visible_length {
            break;
        }
    }
    let max_radius = (max_width / 2.0).max(0.25);
    let extent = max_radius * 2.0 + 2.0 + 1.0 / scale_x.min(scale_y);
    let bounds = Bounds {
        left: ((min_x - extent) * scale_x / scale as f64).floor() as usize,
        top: ((min_y - extent) * scale_y / scale as f64).floor() as usize,
        right: layer
            .width
            .min(((max_x + extent) * scale_x / scale as f64).ceil() as usize),
        bottom: layer
            .height
            .min(((max_y + extent) * scale_y / scale as f64).ceil() as usize),
    };
    if bounds.width() == 0 || bounds.height() == 0 {
        return;
    }

    let supersampled = bounds.scaled(scale);
    let mut plane = AlphaPlane {
        bounds: supersampled,
        pixels: vec![0; supersampled.width() * supersampled.height()],
        scale_x,
        scale_y,
        opacity: f64::from(stroke.rgba[3]),
        high_res_grain: high_res_grain && sx.min(sy) >= 2.0,
        supersample: scale,
        grain_cache: if high_res_grain && sx.min(sy) >= 2.0 && matches!(profile, Profile::AppPencil)
        {
            vec![u32::MAX; bounds.width() * bounds.height()]
        } else {
            Vec::new()
        },
    };
    let seed = if scale == 1 {
        let hash = Sha256::digest(stroke.stroke_id.as_bytes());
        u32::from_le_bytes(hash[..4].try_into().expect("SHA-256 has 32 bytes"))
    } else {
        0
    };

    // Prefixes use the original path and the same sample lattice as a complete stroke.
    let mut traversed = 0.0;
    let mut next_sample = 0.0;
    let pairs = stroke.points.iter().zip(stroke.points.iter().skip(1));
    let tap = (stroke.points.len() == 1).then_some((first, first));
    for (left, right) in pairs.chain(tap) {
        let length = (right.x - left.x).hypot(right.y - left.y);
        let end = (traversed + length).min(visible_length);
        while next_sample <= end + 1e-9 {
            let fraction = if length == 0.0 {
                0.0
            } else {
                (next_sample - traversed) / length
            };
            let dab = Dab::interpolate(profile, left, right, fraction, stroke.thickness_scale);
            if !matches!(profile, Profile::CurrentBrush) || dab.radius >= 0.3 {
                plane.deposit(profile, dab, seed);
            }
            next_sample += 0.5;
        }
        traversed += length;
        if traversed > visible_length {
            break;
        }
    }

    let mask = if scale == 1 {
        plane.pixels
    } else {
        resize_mask(
            &plane.pixels,
            supersampled.width(),
            supersampled.height(),
            bounds.width(),
            bounds.height(),
            Filter::Box,
        )
    };
    let mut overlay = Image::new(bounds.width(), bounds.height(), stroke.rgba);
    for (pixel, alpha) in overlay.data.chunks_exact_mut(4).zip(mask) {
        pixel[3] = alpha;
    }
    layer.alpha_composite(&overlay, bounds.left, bounds.top);
}

struct AlphaPlane {
    grain_cache: Vec<u32>,
    supersample: usize,
    bounds: Bounds,
    pixels: Vec<u8>,
    scale_x: f64,
    scale_y: f64,
    opacity: f64,
    high_res_grain: bool,
}

impl AlphaPlane {
    fn deposit(&mut self, profile: Profile, dab: Dab, seed: u32) {
        let kernel = Coverage::new(profile, &dab, seed, self.high_res_grain);
        let extent = kernel.radius + kernel.amplitude;
        let left = self
            .bounds
            .left
            .max(((dab.x - extent) * self.scale_x - 1.0).floor() as usize);
        let right = self
            .bounds
            .right
            .min(((dab.x + extent) * self.scale_x + 1.0).ceil() as usize);
        let top = self
            .bounds
            .top
            .max(((dab.y - extent) * self.scale_y - 1.0).floor() as usize);
        let bottom = self
            .bounds
            .bottom
            .min(((dab.y + extent) * self.scale_y + 1.0).ceil() as usize);
        let pixel_scale = self.scale_x.min(self.scale_y);
        let width = self.bounds.width();
        for row in top..bottom {
            let source_y = (row as f64 + 0.5) / self.scale_y;
            let offset = (row - self.bounds.top) * width;
            for col in left..right {
                let source_x = (col as f64 + 0.5) / self.scale_x;
                // A shared output-pixel grain decision avoids repeated alpha buildup
                // in holes when many strokes overlap. Geometry remains supersampled.
                let (grain_x, grain_y, grain) = if self.grain_cache.is_empty() {
                    (source_x, source_y, None)
                } else {
                    let grain_x = ((col / self.supersample) as f64 + 0.5) * self.supersample as f64
                        / self.scale_x;
                    let grain_y = ((row / self.supersample) as f64 + 0.5) * self.supersample as f64
                        / self.scale_y;
                    let index = (row / self.supersample - self.bounds.top / self.supersample)
                        * (self.bounds.width() / self.supersample)
                        + col / self.supersample
                        - self.bounds.left / self.supersample;
                    let value = &mut self.grain_cache[index];
                    if *value == u32::MAX {
                        *value = curved_grain(grain_x, grain_y) as u32;
                    }
                    (grain_x, grain_y, Some(*value as f64 / 65535.0))
                };
                let opacity = kernel.at(source_x, source_y, pixel_scale, grain_x, grain_y, grain)
                    * self.opacity;
                let pixel = &mut self.pixels[offset + col - self.bounds.left];
                *pixel = (*pixel).max(opacity.round_ties_even() as u8);
            }
        }
    }
}

struct Coverage<'a> {
    profile: Profile,
    dab: &'a Dab,
    radius: f64,
    amplitude: f64,
    occupancy: f64,
    edge_extent: f64,
    cosine: f64,
    sine: f64,
    seed: u32,
    high_res_grain: bool,
}

impl<'a> Coverage<'a> {
    fn new(profile: Profile, dab: &'a Dab, seed: u32, high_res_grain: bool) -> Self {
        let mut radius = dab.radius;
        let (amplitude, occupancy) = match profile {
            Profile::AppPencil => {
                radius *= 0.77 / 0.70;
                (
                    (radius * 0.35).min(0.9),
                    interpolate_pressure(
                        dab.pressure,
                        &[
                            (0, 0.0),
                            (16, 0.0173),
                            (32, 0.0302),
                            (64, 0.1222),
                            (96, 0.2441),
                            (128, 0.4060),
                            (160, 0.5693),
                            (192, 0.7619),
                            (224, 0.8822),
                            (255, 0.970),
                        ],
                    ) / 0.97,
                )
            }
            Profile::BoundaryPencil => (
                (radius * 0.3).min(0.75),
                interpolate_pressure(
                    dab.pressure,
                    &[
                        (0, 0.0),
                        (16, 0.047),
                        (64, 0.152),
                        (128, 0.450),
                        (192, 0.797),
                        (255, 1.0),
                    ],
                ),
            ),
            Profile::CurrentBrush => (
                0.7,
                interpolate_pressure(
                    dab.pressure,
                    &[(0, 0.0), (16, 0.0), (64, 0.335), (128, 1.0), (255, 1.0)],
                ),
            ),
            _ => (0.0, 0.0),
        };
        Self {
            profile,
            dab,
            radius,
            amplitude,
            occupancy,
            edge_extent: if matches!(profile, Profile::CurrentBrush) {
                interpolate_pressure(
                    dab.pressure,
                    &[(0, 0.7), (128, 0.7), (192, 0.34), (255, 0.34)],
                )
            } else {
                0.0
            },
            cosine: dab.angle.cos(),
            sine: dab.angle.sin(),
            seed,
            high_res_grain,
        }
    }

    fn at(
        &self,
        x: f64,
        y: f64,
        pixel_scale: f64,
        grain_x: f64,
        grain_y: f64,
        grain: Option<f64>,
    ) -> f64 {
        let dx = x - self.dab.x;
        let dy = y - self.dab.y;
        if matches!(self.profile, Profile::AppPencil) {
            let grain = grain.unwrap_or_else(|| field(x, y, 1.0, 0));
            let gain = if self.high_res_grain {
                pencil_gain(grain_x, grain_y)
            } else {
                pencil_gain(x, y)
            };
            let threshold =
                0.97 * self.occupancy * gain / (1.0 - self.occupancy + self.occupancy * gain);
            if grain >= threshold {
                return 0.0;
            }
            let boundary = self.amplitude * (2.0 * field(x, y, 1.0, 193) - 1.0);
            return edge(self.radius - dx.hypot(dy) + boundary, pixel_scale);
        }

        let along = dx * self.cosine + dy * self.sine;
        let across = -dx * self.sine + dy * self.cosine;
        let aspect = if matches!(self.profile, Profile::LegacyBrush) {
            0.45
        } else {
            1.0
        };
        let distance =
            ((along / self.radius).powi(2) + (across / (self.radius * aspect)).powi(2)).sqrt();
        let signed_distance = (1.0 - distance) * self.radius;
        let pressure = self.dab.pressure;
        match self.profile {
            Profile::AppPencil => unreachable!(),
            Profile::BoundaryPencil => {
                if field(x, y, 0.75, 0) >= self.occupancy {
                    return 0.0;
                }
                let noise = field(x, y, 1.25, 193);
                let boundary =
                    self.amplitude * (i32::from(noise > 0.94) - i32::from(noise < 0.06)) as f64;
                edge(signed_distance + boundary, pixel_scale)
            }
            Profile::CurrentBrush => {
                if brush_grain(x, y) >= self.occupancy {
                    return 0.0;
                }
                edge(
                    signed_distance + self.edge_extent * field(x, y, 1.25, 193),
                    pixel_scale,
                )
            }
            Profile::LegacyBrush => {
                let grain = field(x, y, 1.5, self.seed);
                edge(signed_distance, pixel_scale) * (0.65 + 0.35 * grain) * (0.2 + 0.8 * pressure)
            }
            Profile::LegacyPencil { mechanical } => {
                let grain = field(x, y, 1.5, self.seed);
                let texture = ((grain - (0.55 - 0.45 * pressure)) * 2.0).clamp(0.0, 1.0);
                let density = if mechanical {
                    0.3 + 0.7 * pressure
                } else {
                    0.15 + 0.85 * pressure
                };
                edge(signed_distance, pixel_scale) * texture * density
            }
        }
    }
}

fn edge(signed_distance: f64, pixel_scale: f64) -> f64 {
    (signed_distance * pixel_scale + 0.5).clamp(0.0, 1.0)
}

fn interpolate_pressure(pressure: f64, knots: &[(u8, f64)]) -> f64 {
    for pair in knots.windows(2) {
        let [(left, low), (right, high)] = pair else {
            unreachable!()
        };
        let right = f64::from(*right) / 255.0;
        if pressure <= right {
            let left = f64::from(*left) / 255.0;
            return (high - low) / (right - left) * (pressure - left) + low;
        }
    }
    knots.last().expect("pressure knots are nonempty").1
}

fn field(x: f64, y: f64, frequency: f64, seed: u32) -> f64 {
    f64::from(field_bits(x, y, frequency, seed)) / 65535.0
}

fn field_bits(x: f64, y: f64, frequency: f64, seed: u32) -> u16 {
    let hx = (x * frequency).floor() as i64 as u32;
    let hy = (y * frequency).floor() as i64 as u32;
    let noise = hx
        .wrapping_mul(374_761_393)
        .wrapping_add(hy.wrapping_mul(668_265_263))
        .wrapping_add(seed);
    let noise = (noise ^ (noise >> 13)).wrapping_mul(1_274_126_177);
    noise as u16
}

fn pencil_gain(x: f64, y: f64) -> f64 {
    static GAIN: OnceLock<Vec<f64>> = OnceLock::new();
    let values = GAIN.get_or_init(|| {
        (0..=u16::MAX)
            .map(|noise| (0.5 * (2.0 * (f64::from(noise) / 65535.0) - 1.0)).exp())
            .collect()
    });
    values[usize::from(field_bits(x, y, 0.25, 917))]
}

fn brush_grain(source_x: f64, source_y: f64) -> f64 {
    let gx = source_x / 1.5;
    let gy = source_y / 1.5;
    let ix = gx.floor();
    let iy = gy.floor();
    let fx = gx - ix;
    let fy = gy - iy;
    let fx = fx * fx * (3.0 - 2.0 * fx);
    let fy = fy * fy * (3.0 - 2.0 * fy);
    let coarse = field(ix, iy, 1.0, 0) * (1.0 - fx) * (1.0 - fy)
        + field(ix + 1.0, iy, 1.0, 0) * fx * (1.0 - fy)
        + field(ix, iy + 1.0, 1.0, 0) * (1.0 - fx) * fy
        + field(ix + 1.0, iy + 1.0, 1.0, 0) * fx * fy;
    0.94 * coarse + 0.06 * field(source_x, source_y, 1.5, 0)
}

// Two smooth shears preserve area (Jacobian determinant 1): the same uniform
// grain values and pressure thresholds survive, without axis-aligned square cells.
// Fine ripples break up the cell edges; the coarse calibrated gain stays untouched.
fn curved_grain(x: f64, y: f64) -> u16 {
    let x = x + 0.30 * (y * 2.0 * PI / 3.17).sin() + 0.08 * (y * 2.0 * PI / 0.73).sin();
    let y = y + 0.30 * (x * 2.0 * PI / 2.89).sin() + 0.08 * (x * 2.0 * PI / 0.67).sin();
    field_bits(x, y, 1.0, 0)
}
