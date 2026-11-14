use crate::model::{Point, Stroke};

pub fn length(points: &[Point]) -> f64 {
    points
        .windows(2)
        .map(|p| (p[1].x - p[0].x).hypot(p[1].y - p[0].y))
        .sum()
}

pub fn prefix_points(stroke: &Stroke, progress: f64) -> Vec<Point> {
    if stroke.points.is_empty() || progress <= 0.0 {
        return Vec::new();
    }
    if progress >= 1.0 || stroke.points.len() == 1 {
        return stroke.points.clone();
    }
    let total = length(&stroke.points);
    if total == 0.0 {
        return vec![stroke.points[0].clone()];
    }
    let target = total * progress;
    let mut traversed = 0.0;
    let mut result = vec![stroke.points[0].clone()];
    for pair in stroke.points.windows(2) {
        let (a, b) = (&pair[0], &pair[1]);
        let segment = (b.x - a.x).hypot(b.y - a.y);
        if traversed + segment <= target {
            result.push(b.clone());
            traversed += segment;
            continue;
        }
        let fraction = if segment == 0.0 {
            0.0
        } else {
            (target - traversed) / segment
        };
        let interpolate = |left: Option<f64>, right: Option<f64>| match (left, right) {
            (Some(l), Some(r)) => Some(l + (r - l) * fraction),
            (l, r) => l.or(r),
        };
        result.push(Point {
            x: a.x + (b.x - a.x) * fraction,
            y: a.y + (b.y - a.y) * fraction,
            pressure: a.pressure + (b.pressure - a.pressure) * fraction,
            speed: interpolate(a.speed, b.speed),
            direction: interpolate(a.direction, b.direction),
            width: interpolate(a.width, b.width),
        });
        break;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sample() -> Stroke {
        serde_json::from_str(r#"{"stroke_id":"a","group_id":"g","rgba":[0,0,0,255],"thickness_scale":1,"points":[{"x":0,"y":0,"pressure":0,"width":4},{"x":3,"y":4,"pressure":100,"width":12,"speed":8},{"x":6,"y":8,"pressure":200,"width":20,"speed":16}]}"#).unwrap()
    }
    #[test]
    fn distance_prefix_interpolates_retained_channels() {
        let points = prefix_points(&sample(), 0.25);
        assert_eq!(points.len(), 2);
        assert_eq!(points[1].x, 1.5);
        assert_eq!(points[1].y, 2.0);
        assert_eq!(points[1].pressure, 50.0);
        assert_eq!(points[1].width, Some(8.0));
        assert_eq!(points[1].speed, Some(8.0));
    }
    #[test]
    fn zero_full_and_degenerate_prefixes() {
        let mut stroke = sample();
        assert!(prefix_points(&stroke, 0.0).is_empty());
        assert_eq!(prefix_points(&stroke, 1.0), stroke.points);
        stroke.points = vec![stroke.points[0].clone(); 3];
        assert_eq!(prefix_points(&stroke, 0.5).len(), 1);
    }
}
