use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
#[derive(Clone, Debug, Serialize)]
pub struct Candidate {
    pub translation_x: f64,
    pub translation_y: f64,
    pub capped_mean_distance_px: f64,
    pub fraction_within_2px: f64,
    pub native_fraction_within_5px: Option<f64>,
}
#[derive(Debug, Serialize)]
pub struct Fit {
    pub accepted: bool,
    pub reason: String,
    pub best_candidate: Candidate,
    pub second_candidate: Option<Candidate>,
}
fn edt_line(f: &[f64]) -> Vec<f64> {
    let n = f.len();
    let mut v = vec![0; n];
    let mut z = vec![0.; n + 1];
    let mut k = 0;
    z[0] = f64::NEG_INFINITY;
    z[1] = f64::INFINITY;
    for q in 1..n {
        let mut s;
        loop {
            let p = v[k];
            s = ((f[q] + (q * q) as f64) - (f[p] + (p * p) as f64)) / (2. * (q - p) as f64);
            if s > z[k] || k == 0 {
                break;
            }
            k -= 1;
        }
        k += 1;
        v[k] = q;
        z[k] = s;
        z[k + 1] = f64::INFINITY;
    }
    k = 0;
    (0..n)
        .map(|q| {
            while z[k + 1] < (q as f64) {
                k += 1;
            }
            let d = q as f64 - v[k] as f64;
            d * d + f[v[k]]
        })
        .collect()
}
fn edt(mask: &[u8], w: usize, h: usize) -> Vec<f64> {
    let mut result = vec![0.; w * h];
    for x in 0..w {
        let f: Vec<_> = (0..h)
            .map(|y| if mask[y * w + x] != 0 { 0. } else { 1e16 })
            .collect();
        let d = edt_line(&f);
        for y in 0..h {
            result[y * w + x] = d[y];
        }
    }
    for y in 0..h {
        let d = edt_line(&result[y * w..(y + 1) * w]);
        for x in 0..w {
            result[y * w + x] = d[x].sqrt();
        }
    }
    result
}
fn compare(a: &Candidate, b: &Candidate, x: f64) -> Ordering {
    a.capped_mean_distance_px
        .total_cmp(&b.capped_mean_distance_px)
        .then_with(|| b.fraction_within_2px.total_cmp(&a.fraction_within_2px))
        .then_with(|| {
            (a.translation_x - x)
                .abs()
                .total_cmp(&(b.translation_x - x).abs())
        })
}
fn sample(d: &[f64], w: usize, h: usize, p: &[[f64; 2]], tx: f64, ty: f64) -> Candidate {
    let mut sum = 0.;
    let mut hits = 0;
    for point in p {
        let x = point[0] + tx;
        let y = point[1] + ty;
        let distance = if x < 0. || y < 0. || x > (w - 1) as f64 || y > (h - 1) as f64 {
            25.
        } else {
            let ix = x.floor() as usize;
            let iy = y.floor() as usize;
            let nx = (ix + 1).min(w - 1);
            let ny = (iy + 1).min(h - 1);
            let fx = x - ix as f64;
            let fy = y - iy as f64;
            (1. - fy) * ((1. - fx) * d[iy * w + ix] + fx * d[iy * w + nx])
                + fy * ((1. - fx) * d[ny * w + ix] + fx * d[ny * w + nx])
        };
        sum += distance.min(25.);
        hits += usize::from(distance <= 2.);
    }
    Candidate {
        translation_x: tx,
        translation_y: ty,
        capped_mean_distance_px: sum / p.len() as f64,
        fraction_within_2px: hits as f64 / p.len() as f64,
        native_fraction_within_5px: None,
    }
}
fn refine(
    d: &[f64],
    w: usize,
    h: usize,
    p: &[[f64; 2]],
    candidate: Candidate,
    x: f64,
) -> Candidate {
    let mut best = candidate.clone();
    for ix in 0..9 {
        for iy in 0..9 {
            let trial = sample(
                d,
                w,
                h,
                p,
                candidate.translation_x - 1. + ix as f64 / 4.,
                candidate.translation_y - 1. + iy as f64 / 4.,
            );
            if compare(&trial, &best, x) == Ordering::Less {
                best = trial;
            }
        }
    }
    best
}
fn shape(mask: &[u8], w: usize, h: usize, strokes: &[Vec<[f64; 2]>], c: &Candidate) -> f64 {
    let points: Vec<_> = strokes
        .iter()
        .flatten()
        .map(|p| [p[0] + c.translation_x, p[1] + c.translation_y])
        .collect();
    let left = (points
        .iter()
        .map(|p| p[0])
        .fold(f64::INFINITY, f64::min)
        .floor() as i64
        - 6)
    .max(0) as usize;
    let top = (points
        .iter()
        .map(|p| p[1])
        .fold(f64::INFINITY, f64::min)
        .floor() as i64
        - 6)
    .max(0) as usize;
    let right = (points
        .iter()
        .map(|p| p[0])
        .fold(f64::NEG_INFINITY, f64::max)
        .ceil() as i64
        + 7)
    .clamp(0, w as i64) as usize;
    let bottom = (points
        .iter()
        .map(|p| p[1])
        .fold(f64::NEG_INFINITY, f64::max)
        .ceil() as i64
        + 7)
    .clamp(0, h as i64) as usize;
    if right <= left || bottom <= top {
        return 0.;
    }
    let cw = right - left;
    let ch = bottom - top;
    let mut template = vec![0; cw * ch];
    for stroke in strokes {
        let pts: Vec<_> = stroke
            .iter()
            .map(|p| {
                [
                    (p[0] + c.translation_x - left as f64) as i64,
                    (p[1] + c.translation_y - top as f64) as i64,
                ]
            })
            .collect();
        for pair in pts.windows(2) {
            let a = pair[0];
            let b = pair[1];
            let dx = b[0] - a[0];
            let dy = b[1] - a[1];
            let steps = dx.abs().max(dy.abs());
            for step in 0..=steps {
                let (x, y) = if steps == 0 {
                    (a[0], a[1])
                } else if dx.abs() >= dy.abs() {
                    (
                        a[0] + step * dx.signum(),
                        a[1] + ((step * dy.abs() * 2 + steps) / (2 * steps)) * dy.signum(),
                    )
                } else {
                    (
                        a[0] + ((step * dx.abs() * 2 + steps) / (2 * steps)) * dx.signum(),
                        a[1] + step * dy.signum(),
                    )
                };
                if x >= 0 && y >= 0 && x < cw as i64 && y < ch as i64 {
                    template[y as usize * cw + x as usize] = 1;
                }
            }
        }
    }
    let distance = edt(&template, cw, ch);
    let mut all = 0;
    let mut hits = 0;
    for y in 0..ch {
        for x in 0..cw {
            if mask[(y + top) * w + x + left] != 0 {
                all += 1;
                hits += usize::from(distance[y * cw + x] <= 5.);
            }
        }
    }
    if all == 0 {
        0.
    } else {
        hits as f64 / all as f64
    }
}
fn fit_distance(
    mask: &[u8],
    d: &[f64],
    w: usize,
    h: usize,
    strokes: &[Vec<[f64; 2]>],
    x: f64,
) -> Result<Fit, String> {
    if !x.is_finite() || x.abs() > 1e6 || strokes.is_empty() {
        return Err("Invalid anchor coordinates".into());
    }
    let mut points = Vec::new();
    for stroke in strokes {
        if stroke.len() < 2
            || stroke
                .iter()
                .flatten()
                .any(|v| !v.is_finite() || v.abs() > 1e6)
        {
            return Err("Invalid anchor template".into());
        }
        points.push(stroke[0]);
        for pair in stroke.windows(2) {
            let dx = pair[1][0] - pair[0][0];
            let dy = pair[1][1] - pair[0][1];
            let n = dx.hypot(dy).ceil().max(1.) as usize;
            if points.len() + n > 1_000_000 {
                return Err("Anchor template exceeds point limit".into());
            }
            for i in 1..=n {
                points.push([
                    pair[0][0] + dx * i as f64 / n as f64,
                    pair[0][1] + dy * i as f64 / n as f64,
                ]);
            }
        }
    }
    let first = (-points.iter().map(|p| p[1]).fold(f64::INFINITY, f64::min)).ceil() as i64;
    let last = ((h - 1) as f64
        - points
            .iter()
            .map(|p| p[1])
            .fold(f64::NEG_INFINITY, f64::max))
    .floor() as i64;
    if first > last {
        return Err("Anchor template cannot fit inside native canvas".into());
    }
    if (last - first + 1) as usize * points.len() * 9 > 2_000_000_000 {
        return Err("Anchor search exceeds work limit".into());
    }
    let mut candidates = Vec::new();
    for tx in x.round_ties_even() as i64 - 4..=x.round_ties_even() as i64 + 4 {
        for ty in first..=last {
            candidates.push(sample(d, w, h, &points, tx as f64, ty as f64));
        }
    }
    candidates.sort_by(|a, b| compare(a, b, x));
    let best = candidates[0].clone();
    let second = candidates
        .iter()
        .skip(1)
        .find(|c| (c.translation_y - best.translation_y).abs() >= 16.)
        .cloned()
        .map(|c| refine(d, w, h, &points, c, x));
    let mut best = refine(d, w, h, &points, best, x);
    best.native_fraction_within_5px = Some(shape(mask, w, h, strokes, &best));
    let reason = if best.fraction_within_2px < 0.35 {
        "insufficient-native-overlap"
    } else if best.native_fraction_within_5px.unwrap() < 0.6 {
        "inconsistent-native-shape"
    } else if second.as_ref().is_some_and(|s| {
        (s.capped_mean_distance_px - best.capped_mean_distance_px)
            / s.capped_mean_distance_px.max(1e-9)
            < 0.1
    }) {
        "ambiguous-native-match"
    } else {
        "unique-native-match"
    };
    Ok(Fit {
        accepted: reason == "unique-native-match",
        reason: reason.into(),
        best_candidate: best,
        second_candidate: second,
    })
}
pub fn fit_template(
    mask: &[u8],
    w: usize,
    h: usize,
    strokes: &[Vec<[f64; 2]>],
    x: f64,
) -> Result<Fit, String> {
    validate_mask(mask, w, h)?;
    fit_distance(mask, &edt(mask, w, h), w, h, strokes, x)
}
fn validate_mask(mask: &[u8], w: usize, h: usize) -> Result<(), String> {
    if w == 0
        || h == 0
        || w > 8192
        || h > 8192
        || w * h > 12_000_000
        || mask.len() != w * h
        || !mask.iter().any(|v| *v != 0)
    {
        return Err("Invalid or blank native ink mask".into());
    }
    Ok(())
}
#[derive(Deserialize)]
struct Template {
    strokes: Vec<Vec<[f64; 2]>>,
    expected_x: f64,
}
#[derive(Deserialize)]
struct MatchRequest {
    width: usize,
    height: usize,
    mask: Vec<u8>,
    templates: Vec<Template>,
}
pub fn match_json(bytes: &[u8]) -> Result<Vec<u8>, String> {
    #[derive(Deserialize)]
    struct Operation {
        #[serde(default)]
        op: String,
    }
    let op: Operation = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if op.op == "schedule" {
        return schedule::schedule(bytes);
    }
    if !op.op.is_empty() && op.op != "anchors" {
        return Err("Unknown core operation".into());
    }
    let r: MatchRequest = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    validate_mask(&r.mask, r.width, r.height)?;
    if r.templates.len() > 4096 {
        return Err("Too many anchor groups".into());
    }
    let d = edt(&r.mask, r.width, r.height);
    let fits: Result<Vec<_>, _> = r
        .templates
        .iter()
        .map(|t| fit_distance(&r.mask, &d, r.width, r.height, &t.strokes, t.expected_x))
        .collect();
    serde_json::to_vec(&fits?).map_err(|e| e.to_string())
}
mod abi;
mod schedule;
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unique_translation_and_repeated_shape_rejection() {
        let mut mask = vec![0; 80 * 120];
        for x in 10..51 {
            mask[40 * 80 + x] = 1;
        }
        let strokes = vec![vec![[0., 0.], [40., 0.]]];
        let fit = fit_template(&mask, 80, 120, &strokes, 10.).unwrap();
        assert!(fit.accepted);
        assert!((fit.best_candidate.translation_y - 40.).abs() < 1.);
        for x in 10..51 {
            mask[80 * 80 + x] = 1;
        }
        let fit = fit_template(&mask, 80, 120, &strokes, 10.).unwrap();
        assert!(!fit.accepted);
        assert_eq!(fit.reason, "ambiguous-native-match");
    }
    #[test]
    fn empty_masks_and_invalid_points_are_rejected() {
        assert!(fit_template(&vec![0; 100], 10, 10, &vec![vec![[0., 0.], [1., 1.]]], 0.).is_err());
        assert!(fit_template(
            &vec![1; 100],
            10,
            10,
            &vec![vec![[f64::NAN, 0.], [1., 1.]]],
            0.
        )
        .is_err());
    }
}
#[cfg(test)]
mod schedule_tests {
    use super::*;
    #[test]
    fn layer_replay_order_does_not_change_compositing_and_finishes_all_visible_ink() {
        let data=br#"{"op":"schedule","fps":2,"seconds":2,"ordering":"layer","page":{"groups":[{"group_id":"low","visible":true},{"group_id":"high","visible":true}],"strokes":[{"stroke_id":"a","group_id":"high"},{"stroke_id":"b","group_id":"low"}],"replay_order":["a","b"],"compositing_order":["low","high"]}}"#;
        let result = match_json(data).unwrap();
        let frames: serde_json::Value = serde_json::from_slice(&result).unwrap();
        assert_eq!(frames.as_array().unwrap().len(), 6);
        assert_eq!(frames[0]["active_stroke_id"], "b");
        assert_eq!(
            frames[5]["completed_stroke_ids"],
            serde_json::json!(["a", "b"])
        );
    }
}
