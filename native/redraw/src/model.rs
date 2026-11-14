use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Point {
    pub x: f64,
    pub y: f64,
    #[serde(default = "one")]
    pub pressure: f64,
    #[serde(default)]
    pub speed: Option<f64>,
    #[serde(default)]
    pub direction: Option<f64>,
    #[serde(default)]
    pub width: Option<f64>,
}
fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Stroke {
    pub stroke_id: String,
    pub group_id: String,
    pub rgba: [u8; 4],
    pub thickness_scale: f64,
    pub points: Vec<Point>,
    #[serde(default)]
    pub tool_code: Option<i32>,
    #[serde(default)]
    pub tool_name: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Group {
    pub group_id: String,
    pub visible: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Page {
    pub page_id: String,
    pub paper_size: Option<[f64; 2]>,
    pub groups: Vec<Group>,
    pub strokes: Vec<Stroke>,
    pub compositing_order: Vec<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
pub struct Viewport {
    pub width: usize,
    pub height: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Options {
    #[serde(default)]
    pub viewport: Option<Viewport>,
    #[serde(default = "white")]
    pub background: [u8; 4],
    #[serde(default)]
    pub pencil_boundary: bool,
}
fn white() -> [u8; 4] {
    [255; 4]
}
impl Default for Options {
    fn default() -> Self {
        Self {
            viewport: None,
            background: white(),
            pencil_boundary: false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, Default, PartialEq)]
pub struct Visibility {
    #[serde(default)]
    pub completed_stroke_ids: Vec<String>,
    #[serde(default)]
    pub active_stroke_id: Option<String>,
    #[serde(default)]
    pub active_progress: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Request {
    pub page: Page,
    #[serde(default)]
    pub options: Options,
    #[serde(default)]
    pub visibility: Option<Visibility>,
}
