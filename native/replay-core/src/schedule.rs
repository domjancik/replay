use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
#[derive(Deserialize)]
struct Group {
    group_id: String,
    visible: bool,
}
#[derive(Deserialize)]
struct Stroke {
    stroke_id: String,
    group_id: String,
}
#[derive(Deserialize)]
struct Page {
    groups: Vec<Group>,
    strokes: Vec<Stroke>,
    replay_order: Vec<String>,
    compositing_order: Vec<String>,
}
#[derive(Deserialize)]
struct Request {
    page: Page,
    fps: usize,
    seconds: f64,
    ordering: String,
}
#[derive(Clone, Serialize)]
struct Visibility {
    completed_stroke_ids: Vec<String>,
    active_stroke_id: Option<String>,
    active_progress: f64,
}
pub fn schedule(bytes: &[u8]) -> Result<Vec<u8>, String> {
    let r: Request = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if r.fps < 1
        || r.fps > 30
        || !r.seconds.is_finite()
        || r.seconds <= 0.
        || !matches!(r.ordering.as_str(), "entry" | "layer")
    {
        return Err("Invalid replay timing".into());
    }
    let visible: HashSet<_> = r
        .page
        .groups
        .iter()
        .filter(|g| g.visible)
        .map(|g| g.group_id.as_str())
        .collect();
    let composing: HashSet<_> = r
        .page
        .compositing_order
        .iter()
        .map(String::as_str)
        .collect();
    let groups: HashMap<_, _> = r
        .page
        .strokes
        .iter()
        .map(|s| (s.stroke_id.as_str(), s.group_id.as_str()))
        .collect();
    if groups.len() != r.page.strokes.len() || r.page.replay_order.iter().any(|id| id.len() > 128) {
        return Err("Invalid stroke identifiers".into());
    }
    let mut order = Vec::new();
    if r.ordering == "layer" {
        for group in &r.page.compositing_order {
            if visible.contains(group.as_str()) {
                for id in &r.page.replay_order {
                    if groups.get(id.as_str()) == Some(&group.as_str()) {
                        order.push(id.clone());
                    }
                }
            }
        }
    } else {
        for id in &r.page.replay_order {
            if groups
                .get(id.as_str())
                .is_some_and(|g| visible.contains(g) && composing.contains(g))
            {
                order.push(id.clone());
            }
        }
    }
    if order.is_empty() {
        return Err("No visible replay strokes".into());
    }
    if order.iter().collect::<HashSet<_>>().len() != order.len() {
        return Err("Duplicate replay entry".into());
    }
    let estimated = (r.fps as f64 * r.seconds).ceil();
    if !estimated.is_finite() || estimated > (usize::MAX - r.fps) as f64 {
        return Err("Replay schedule exceeds browser memory budget".into());
    }
    let count = estimated as usize;
    if order.len().saturating_mul(count + r.fps) > 4_000_000 {
        return Err("Replay schedule exceeds browser memory budget".into());
    }
    let mut frames = Vec::with_capacity(count + r.fps);
    for index in 1..=count {
        let completed = index * order.len() / count;
        let remainder = index * order.len() % count;
        let mut ids = order[..completed].to_vec();
        ids.sort();
        frames.push(Visibility {
            completed_stroke_ids: ids,
            active_stroke_id: if remainder > 0 {
                Some(order[completed].clone())
            } else {
                None
            },
            active_progress: remainder as f64 / count as f64,
        });
    }
    for _ in 0..r.fps {
        frames.push(frames.last().unwrap().clone());
    }
    let json = serde_json::to_vec(&frames).map_err(|e| e.to_string())?;
    if json.len() > 32 * 1024 * 1024 {
        return Err("Replay schedule exceeds output limit".into());
    }
    Ok(json)
}

#[cfg(test)]
mod duration_tests {
    #[test]
    fn schedules_more_than_two_minutes() {
        let input = br#"{"fps":6,"seconds":180,"ordering":"layer","page":{"groups":[{"group_id":"g","visible":true}],"strokes":[{"stroke_id":"s","group_id":"g"}],"replay_order":["s"],"compositing_order":["g"]}}"#;
        let frames: serde_json::Value = serde_json::from_slice(&super::schedule(input).unwrap()).unwrap();
        assert_eq!(frames.as_array().unwrap().len(), 1086);
    }
}
