use redraw::{
    calligraphy, generic,
    model::{Point, Stroke},
    raster::Image,
    simple,
};
use sha2::{Digest, Sha256};

#[test]
fn drawing_tools_match_desktop_masks() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../artifacts/rust-renderer-raster/tools.rgba");
    let expected = std::fs::read(path).ok();
    // SHA-256 of complete 38×28 RGBA surfaces produced by Pillow 12.3.0.
    let hashes = [
        "90bddf5c0a1f34630936d5a9e74963e78c9dd9926d2557744078dd6a30434c95",
        "9eebe0e38a01a4a5cc0648ef6724441ccc3f7ebc6a8fc96156afcc03ceb61e2a",
        "aed2d46e0813af365fe54c2a396a2728d4492722607d49d1d2f05d85ce3a3267",
        "2344e007ae81a3b1baf866709cb270710924a466c2f6d4148df5ccd2b2af2cb4",
        "d1a972ca8808836e305bb885ff38cf3a2d2a4bbd6d9f239f8e382d1b9d13ae92",
        "4376e322a16f154bf75f87f8559f040e2cc9bb8085c059287e4cc55c37c806f3",
        "afb0431545128d5c80902b93bd8984fc18450763280d537d4b17fb06c52aab9d",
    ];
    let points: Vec<_> = [(3.25, 17.5, 8.), (17.75, 6.25, 31.), (31.5, 20.75, 45.)]
        .into_iter()
        .map(|(x, y, width)| Point {
            x,
            y,
            width: Some(width),
            pressure: 178.,
            speed: Some(13.),
            direction: Some(61.),
        })
        .collect();
    let mut stroke = Stroke {
        stroke_id: "raster".into(),
        group_id: "ink".into(),
        points: points.clone(),
        rgba: [233, 118, 68, 177],
        thickness_scale: 8.2,
        tool_code: None,
        tool_name: None,
    };
    for (index, code) in [17, 16, 18, 21, 6, 15, 23].into_iter().enumerate() {
        let mut layer = Image::new(38, 28, [45, 79, 182, 121]);
        stroke.tool_code = Some(code);
        match code {
            16..=18 => simple::draw(&mut layer, &points, &stroke, 1.1, 0.9),
            21 => calligraphy::draw(&mut layer, &points, &stroke, 1.1, 0.9),
            _ => generic::draw(&mut layer, &points, &stroke, 1.1, 0.9),
        }
        if let Some(expected) = &expected {
            let len = layer.data.len();
            let reference = &expected[index * len..(index + 1) * len];
            let errors: Vec<_> = layer
                .data
                .iter()
                .zip(reference)
                .enumerate()
                .filter_map(|(i, (&a, &b))| (a != b).then_some((i, a, b)))
                .collect();
            assert!(
                errors.is_empty(),
                "tool {code} differs in {} channels: {:?}",
                errors.len(),
                &errors[..errors.len().min(6)]
            );
        }
        assert_eq!(
            format!("{:x}", Sha256::digest(&layer.data)),
            hashes[index],
            "tool {code}"
        );
    }
}
