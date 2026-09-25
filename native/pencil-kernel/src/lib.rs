//! Fused current-pencil deposition. No fast-math, FMA, or native exp evaluation.
//! The host supplies occupancy and its NumPy-computed 65,536-entry gain table.
use std::panic::{catch_unwind, AssertUnwindSafe};

const TILE: usize = 64;
const MAX_TILES: usize = 64;
const NULL: i32 = 1;
const INVALID: i32 = 2;
const SAMPLE: i32 = 3;
const PANIC: i32 = 4;

#[derive(Clone, Copy)]
pub struct Canvas {
    pub width: usize,
    pub height: usize,
    pub origin_x: i64,
    pub origin_y: i64,
    pub scale_x: f64,
    pub scale_y: f64,
    pub opacity: u8,
}

#[derive(Clone, Copy)]
struct Paper {
    grain: f64,
    boundary: f64,
    gain: f64,
}

struct Tile {
    tx: usize,
    ty: usize,
    stamp: u64,
    width: usize,
    x: [f64; TILE],
    y: [f64; TILE],
    paper: Vec<Paper>,
}

fn hash_index(x: f64, y: f64, frequency: f64, seed: u32) -> usize {
    // NumPy converts floored signed coordinates modulo 2^64. Only their low
    // 32 bits survive the hash, so an i64-to-u32 wrapping cast is equivalent.
    let hx = (x * frequency).floor() as i64 as u32;
    let hy = (y * frequency).floor() as i64 as u32;
    let value = hx
        .wrapping_mul(374761393)
        .wrapping_add(hy.wrapping_mul(668265263))
        .wrapping_add(seed);
    let value = (value ^ (value >> 13)).wrapping_mul(1274126177);
    (value & 65535) as usize
}

impl Tile {
    fn new(tx: usize, ty: usize, canvas: Canvas, gains: &[f64], stamp: u64) -> Self {
        let width = TILE.min(canvas.width - tx * TILE);
        let height = TILE.min(canvas.height - ty * TILE);
        let mut x = [0.0; TILE];
        let mut y = [0.0; TILE];
        for (i, value) in x[..width].iter_mut().enumerate() {
            *value = ((canvas.origin_x + (tx * TILE + i) as i64) as f64 + 0.5) / canvas.scale_x;
        }
        for (i, value) in y[..height].iter_mut().enumerate() {
            *value = ((canvas.origin_y + (ty * TILE + i) as i64) as f64 + 0.5) / canvas.scale_y;
        }
        let mut paper = Vec::with_capacity(width * height);
        for &sy in &y[..height] {
            for &sx in &x[..width] {
                paper.push(Paper {
                    grain: hash_index(sx, sy, 1.0, 0) as f64 / 65535.0,
                    boundary: 2.0 * (hash_index(sx, sy, 1.0, 193) as f64 / 65535.0) - 1.0,
                    gain: gains[hash_index(sx, sy, 0.25, 917)],
                });
            }
        }
        Self {
            tx,
            ty,
            stamp,
            width,
            x,
            y,
            paper,
        }
    }
}

fn validate(canvas: Canvas, alpha_len: usize, samples: &[f64], gains: &[f64]) -> Result<(), i32> {
    if canvas.width == 0
        || canvas.height == 0
        || canvas.width.checked_mul(canvas.height) != Some(alpha_len)
        || canvas.width > i64::MAX as usize
        || canvas.height > i64::MAX as usize
        || canvas.origin_x.checked_add(canvas.width as i64).is_none()
        || canvas.origin_y.checked_add(canvas.height as i64).is_none()
        || !canvas.scale_x.is_finite()
        || canvas.scale_x <= 0.0
        || !canvas.scale_y.is_finite()
        || canvas.scale_y <= 0.0
        || samples.len() % 4 != 0
        || gains.len() != 65536
        || gains.iter().any(|v| !v.is_finite() || *v <= 0.0)
    {
        return Err(INVALID);
    }
    // Signed integer hashes and float coordinates are exact in this range.
    for value in [
        canvas.origin_x as f64 / canvas.scale_x,
        (canvas.origin_x + canvas.width as i64) as f64 / canvas.scale_x,
        canvas.origin_y as f64 / canvas.scale_y,
        (canvas.origin_y + canvas.height as i64) as f64 / canvas.scale_y,
    ] {
        if !value.is_finite() || value.abs() > (1u64 << 52) as f64 {
            return Err(INVALID);
        }
    }
    for s in samples.chunks_exact(4) {
        if s.iter().any(|v| !v.is_finite()) || s[2] < 0.0 || !(0.0..=1.0).contains(&s[3]) {
            return Err(SAMPLE);
        }
        let radius = s[2] * (0.77 / 0.70);
        let extent = radius + 0.9_f64.min(radius * 0.35);
        if !extent.is_finite()
            || !((s[0] - extent) * canvas.scale_x - 1.0).is_finite()
            || !((s[0] + extent) * canvas.scale_x + 1.0).is_finite()
            || !((s[1] - extent) * canvas.scale_y - 1.0).is_finite()
            || !((s[1] + extent) * canvas.scale_y + 1.0).is_finite()
        {
            return Err(SAMPLE);
        }
    }
    Ok(())
}

/// Safe slice-based entry point. All input validation precedes pixel mutation.
/// Retained paper tiles are bounded to 64 * 64 * 64 * 24 bytes (6 MiB).
pub fn render(alpha: &mut [u8], canvas: Canvas, samples: &[f64], gains: &[f64]) -> Result<(), i32> {
    validate(canvas, alpha.len(), samples, gains)?;
    let mut tiles: Vec<Tile> = Vec::with_capacity(MAX_TILES);
    let mut stamp = 0u64;
    let max_x = canvas.origin_x + canvas.width as i64;
    let max_y = canvas.origin_y + canvas.height as i64;
    for s in samples.chunks_exact(4) {
        let radius = s[2] * (0.77 / 0.70);
        let amplitude = 0.9_f64.min(radius * 0.35);
        let extent = radius + amplitude;
        let left = (((s[0] - extent) * canvas.scale_x - 1.0).floor() as i64).max(canvas.origin_x);
        let right = (((s[0] + extent) * canvas.scale_x + 1.0).ceil() as i64).min(max_x);
        let top = (((s[1] - extent) * canvas.scale_y - 1.0).floor() as i64).max(canvas.origin_y);
        let bottom = (((s[1] + extent) * canvas.scale_y + 1.0).ceil() as i64).min(max_y);
        if right <= left || bottom <= top {
            continue;
        }
        let (left, right, top, bottom) = (
            (left - canvas.origin_x) as usize,
            (right - canvas.origin_x) as usize,
            (top - canvas.origin_y) as usize,
            (bottom - canvas.origin_y) as usize,
        );
        for ty in top / TILE..=(bottom - 1) / TILE {
            for tx in left / TILE..=(right - 1) / TILE {
                stamp = stamp.wrapping_add(1);
                let index = if let Some(index) = tiles.iter().position(|t| t.tx == tx && t.ty == ty)
                {
                    index
                } else {
                    let tile = Tile::new(tx, ty, canvas, gains, stamp);
                    if tiles.len() == MAX_TILES {
                        let index = tiles
                            .iter()
                            .enumerate()
                            .min_by_key(|(_, t)| t.stamp)
                            .unwrap()
                            .0;
                        tiles[index] = tile;
                        index
                    } else {
                        tiles.push(tile);
                        tiles.len() - 1
                    }
                };
                let tile = &mut tiles[index];
                tile.stamp = stamp;
                for row in top.max(ty * TILE)..bottom.min((ty + 1) * TILE) {
                    let sy = tile.y[row - ty * TILE];
                    let dy = sy - s[1];
                    for col in left.max(tx * TILE)..right.min((tx + 1) * TILE) {
                        let sx = tile.x[col - tx * TILE];
                        let p = tile.paper[(row - ty * TILE) * tile.width + col - tx * TILE];
                        let distance = (sx - s[0]).hypot(dy);
                        let boundary = amplitude * p.boundary;
                        let edge = ((radius - distance + boundary)
                            * canvas.scale_x.min(canvas.scale_y)
                            + 0.5)
                            .clamp(0.0, 1.0);
                        let threshold = 0.97 * s[3] * p.gain / (1.0 - s[3] + s[3] * p.gain);
                        let coverage = (edge
                            * if p.grain < threshold { 1.0 } else { 0.0 }
                            * canvas.opacity as f64)
                            .round_ties_even() as u8;
                        let pixel = &mut alpha[row * canvas.width + col];
                        *pixel = (*pixel).max(coverage);
                    }
                }
            }
        }
    }
    Ok(())
}

#[no_mangle]
pub extern "C" fn rm_pencil_kernel_version() -> u32 {
    1
}
#[no_mangle]
pub extern "C" fn rm_pencil_abi_version() -> u32 {
    rm_pencil_kernel_version()
}

/// C ABI: samples contain sample_count consecutive [x,y,radius,occupancy] rows.
/// Status 0=success,1=null,2=invalid layout/scales/gains,3=invalid sample,4=panic.
///
/// # Safety
/// Non-null pointers must reference valid, correctly aligned arrays of the
/// declared lengths. Alpha must be exclusively writable and not alias inputs.
/// The host must retain all buffers until this synchronous call returns.
#[no_mangle]
pub unsafe extern "C" fn rm_pencil_draw(
    alpha: *mut u8,
    width: usize,
    height: usize,
    origin_x: i64,
    origin_y: i64,
    scale_x: f64,
    scale_y: f64,
    opacity: u8,
    samples: *const f64,
    sample_count: usize,
    gain_table: *const f64,
    gain_len: usize,
) -> i32 {
    if alpha.is_null() || gain_table.is_null() || (samples.is_null() && sample_count != 0) {
        return NULL;
    }
    let Some(len) = width
        .checked_mul(height)
        .filter(|v| *v <= isize::MAX as usize)
    else {
        return INVALID;
    };
    let Some(sample_len) = sample_count
        .checked_mul(4)
        .filter(|v| *v <= isize::MAX as usize / 8)
    else {
        return INVALID;
    };
    if gain_len != 65536
        || gain_table as usize % 8 != 0
        || (!samples.is_null() && samples as usize % 8 != 0)
    {
        return INVALID;
    }
    let result = catch_unwind(AssertUnwindSafe(|| {
        let output = unsafe { std::slice::from_raw_parts_mut(alpha, len) };
        let input = if sample_len == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(samples, sample_len) }
        };
        let gains = unsafe { std::slice::from_raw_parts(gain_table, gain_len) };
        render(
            output,
            Canvas {
                width,
                height,
                origin_x,
                origin_y,
                scale_x,
                scale_y,
                opacity,
            },
            input,
            gains,
        )
    }));
    match result {
        Ok(Ok(())) => 0,
        Ok(Err(code)) => code,
        Err(_) => PANIC,
    }
}

/// Alias with the same pointer safety contract as rm_pencil_draw.
/// # Safety
/// See rm_pencil_draw.
#[no_mangle]
pub unsafe extern "C" fn rm_pencil_render(
    alpha: *mut u8,
    width: usize,
    height: usize,
    origin_x: i64,
    origin_y: i64,
    scale_x: f64,
    scale_y: f64,
    opacity: u8,
    samples: *const f64,
    sample_count: usize,
    gain_table: *const f64,
    gain_len: usize,
) -> i32 {
    unsafe {
        rm_pencil_draw(
            alpha,
            width,
            height,
            origin_x,
            origin_y,
            scale_x,
            scale_y,
            opacity,
            samples,
            sample_count,
            gain_table,
            gain_len,
        )
    }
}
