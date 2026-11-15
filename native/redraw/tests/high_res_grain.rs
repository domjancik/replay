use redraw::{model::Request, render::render};
fn request(scale: f64, refined: bool, pressure: u8, angle: f64) -> Request {
    let dy = angle.sin() * 50.0;
    let dx = angle.cos() * 50.0;
    serde_json::from_value(serde_json::json!({"page":{"page_id":"grain","paper_size":[128,128],"groups":[{"group_id":"g","visible":true}],"compositing_order":["g"],"strokes":[{"stroke_id":"s","group_id":"g","rgba":[0,0,0,255],"thickness_scale":1,"tool_code":14,"points":[{"x":64.0-dx,"y":64.0-dy,"width":80,"pressure":pressure},{"x":64.0+dx,"y":64.0+dy,"width":80,"pressure":pressure}]}]},"options":{"viewport":{"width":(128.0*scale) as usize,"height":(128.0*scale) as usize},"high_res_grain":refined}})).unwrap()
}
fn mass(bytes: &[u8]) -> f64 {
    bytes.chunks_exact(4).map(|p| 255.0 - p[0] as f64).sum()
}
#[test]
fn optional_grain_changes_high_resolution_without_changing_pressure_density() {
    for scale in [2.0, 4.0] {
        for angle in [0.0, 0.6, 1.57] {
            let mut previous = 0.0;
            for pressure in [32, 64, 128, 192, 255] {
                let base = render(&request(scale, false, pressure, angle)).unwrap();
                let refined = render(&request(scale, true, pressure, angle)).unwrap();
                assert!(
                    base.data != refined.data,
                    "high resolution option must change grain"
                );
                let a = mass(&base.data);
                let b = mass(&refined.data);
                assert!(
                    (b / a - 1.0).abs() < 0.035,
                    "scale={scale} angle={angle} pressure={pressure} delta={}",
                    b / a - 1.0
                );
                assert!(b > previous);
                previous = b;
            }
        }
    }
}
#[test]
fn option_is_inert_below_double_resolution() {
    for scale in [0.5, 1.0, 1.5] {
        assert_eq!(
            render(&request(scale, false, 128, 0.6)).unwrap().data,
            render(&request(scale, true, 128, 0.6)).unwrap().data
        );
    }
}

#[test]
fn refined_replay_and_cache_match_static_and_options_invalidate_cache() {
    use redraw::{model::Visibility, render::CachedRenderer};
    let mut req = request(2.0, true, 128, 0.6);
    let mut cache = CachedRenderer::default();
    for progress in [0.25, 0.5, 0.75, 1.0] {
        req.visibility = Some(Visibility {
            active_stroke_id: Some("s".into()),
            active_progress: progress,
            ..Default::default()
        });
        assert_eq!(cache.render(&req).unwrap().data, render(&req).unwrap().data);
    }
    req.visibility = None;
    assert_eq!(cache.render(&req).unwrap().data, render(&req).unwrap().data);
    req.options.high_res_grain = false;
    assert_eq!(cache.render(&req).unwrap().data, render(&req).unwrap().data);
}

#[test]
fn grain_option_does_not_change_other_tools() {
    for tool in [0, 1, 7, 12, 16, 17, 18, 21] {
        let mut req = request(2.0, false, 128, 0.6);
        req.page.strokes[0].tool_code = Some(tool);
        let base = render(&req).unwrap();
        req.options.high_res_grain = true;
        assert_eq!(base.data, render(&req).unwrap().data);
    }
}

#[test]
fn repeated_shading_does_not_fill_grain_holes() {
    let mut req = request(2.0, false, 128, 0.6);
    let template = req.page.strokes[0].clone();
    for i in 1..20 {
        let mut stroke = template.clone();
        stroke.stroke_id = format!("s{i}");
        for point in &mut stroke.points {
            point.y += i as f64 / 8.0;
        }
        req.page.strokes.push(stroke);
    }
    let baseline = mass(&render(&req).unwrap().data);
    req.options.high_res_grain = true;
    let refined = mass(&render(&req).unwrap().data);
    assert!(
        (refined / baseline - 1.0).abs() < 0.035,
        "overdraw density delta {}",
        refined / baseline - 1.0
    );
}
