use rm_renderer::{
    model::{Point, Stroke},
    raster::Image,
    texture::draw,
};
use sha2::{Digest, Sha256};

fn stroke(code: i32) -> Stroke {
    Stroke {
        stroke_id: "texture-parity".into(),
        group_id: "g".into(),
        rgba: [92, 18, 215, 201],
        thickness_scale: 3.5,
        points: vec![
            Point {
                x: -3.25,
                y: 8.7,
                pressure: 70.0,
                speed: Some(44.0),
                direction: Some(252.0),
                width: Some(19.0),
            },
            Point {
                x: 19.25,
                y: 24.5,
                pressure: 155.0,
                speed: Some(12.0),
                direction: Some(3.0),
                width: Some(32.0),
            },
            Point {
                x: 35.4,
                y: 16.9,
                pressure: 230.0,
                speed: Some(31.0),
                direction: Some(113.0),
                width: None,
            },
        ],
        tool_code: Some(code),
        tool_name: None,
    }
}

#[test]
fn textured_tools_match_pillow_rgba_at_partial_and_complete_lengths() {
    // Raw RGBA digests from Python draw_texture(), with a translucent destination,
    // anisotropic scale, a clipped origin, wrapped direction and missing final width.
    let cases = [
        (
            0,
            false,
            "a4c2ac75432ba50cd250d64496084e4ea26d1ad0455449b0c7e44b4dfa8b3d4c",
            "cfdf5b08eb10e557c836bd026b02b89c9c8b5dfecf5c5013f5658c117075f940",
        ),
        (
            1,
            false,
            "2477cc6d1bcb1efccf9fb7cf604f3ede44f2dd4f63c88ead0ffc2f7914031783",
            "a632ae90f12fa18e46b80df3fe516ffcda212e9631bad0c156bf4db18ee0060a",
        ),
        (
            7,
            false,
            "892bb362f6b104d25fb8da68684f71bbad7e61027962f006df526c81df659e8f",
            "1d9557022f5b5ccb0dad59b417e79bf2f7fedf1c291a905efad35199c2544f1a",
        ),
        (
            12,
            false,
            "5842655b89d03708c254fb5c7510dd9d006c91d6e2f6bd942d866f079f7c6371",
            "3aef062ceced863abee181c7ec2a523b2410778978b718ce09e8925ba38551c7",
        ),
        (
            13,
            false,
            "986f3c8947ea4f04b687df043ca4b0b3033dffc900f762214534a738ea94acf0",
            "0986a6db687d092e0f870440a4905a4a317408f00bb01b45788a6723a0f845af",
        ),
        (
            14,
            false,
            "986f3c8947ea4f04b687df043ca4b0b3033dffc900f762214534a738ea94acf0",
            "0986a6db687d092e0f870440a4905a4a317408f00bb01b45788a6723a0f845af",
        ),
        (
            14,
            true,
            "1c3ca0688d8b1af4fda2bc25fbb92dfce211276350af6a2e1965d8cb7c1ee478",
            "9c7efd8000063c55139fc7b83cb8e1af93f4615005ca8dacf6d90493953a2825",
        ),
    ];
    for (code, boundary, partial, complete) in cases {
        for (visible_length, expected) in [(17.25, partial), (100.0, complete)] {
            let mut layer = Image::new(39, 35, [40, 55, 70, 163]);
            draw(
                &mut layer,
                &stroke(code),
                visible_length,
                1.11,
                0.89,
                boundary,
            );
            assert_eq!(
                format!("{:x}", Sha256::digest(&layer.data)),
                expected,
                "tool {code}, boundary {boundary}, visible length {visible_length}"
            );
        }
    }
}

#[test]
fn current_texture_taps_and_stationary_strokes_stay_blank() {
    for code in [12, 13, 14] {
        let mut stroke = stroke(code);
        stroke.points = vec![stroke.points[1].clone()];
        let mut layer = Image::new(39, 35, [0; 4]);
        draw(&mut layer, &stroke, 0.0, 1.0, 1.0, false);
        stroke.points.push(stroke.points[0].clone());
        draw(&mut layer, &stroke, 0.0, 1.0, 1.0, false);
        assert!(layer.data.iter().all(|value| *value == 0), "tool {code}");
    }
}

#[test]
fn legacy_taps_and_current_pressure_knots_match_pillow() {
    let cases = [
        (
            0,
            128.0,
            "d6a72760f9128461b92ceb9d764111ffbc1db4c01442f0cbfb2ff81514ab2670",
        ),
        (
            1,
            128.0,
            "01e670df20800da5014a3473bceb11addab2e00556f7c165f04d0f27c67b610d",
        ),
        (
            7,
            128.0,
            "9cf135659aeca853609cad2dc0b9bb9aa53ec2da2cf58d3af4a5ec3dd770a559",
        ),
        (
            12,
            16.0,
            "8ce8ba8e726ee8925e6560d86ac35be1097691d1cfac888e6bd20e804ea9eb15",
        ),
        (
            12,
            64.0,
            "666f16c663a8c87df1739ba2fd1f09c0d87f8a47898a568088100f456dcae214",
        ),
        (
            12,
            128.0,
            "b11bf9de28e48b8d6e1efbab8d488eab981b73efa62604c9ea5d5bd98042363f",
        ),
        (
            14,
            16.0,
            "fbff6f68beb87ece00edf96f61f2843aca2cac01d3b82e0ecce641716727e62a",
        ),
        (
            14,
            64.0,
            "61defb361cf683dd454b012839d6fa2aae89614fc041d49dea7f088ead78c51b",
        ),
        (
            14,
            128.0,
            "e7ee1762bd36b9fd2317bd58f51c942936f667e1b2bb72a92ec4d2501f08eb20",
        ),
        (
            14,
            255.0,
            "b1cfd0c13762e45883bb1f28d5e74c7c303bc9c07ea2688eacb9a23e16370bca",
        ),
    ];
    for (code, pressure, expected) in cases {
        let mut layer = Image::new(32, 20, [0; 4]);
        let mut sample = stroke(code);
        sample.stroke_id = "texture-probe".into();
        sample.rgba = [17, 131, 197, 255];
        let start = Point {
            x: 3.2,
            y: 10.0,
            pressure,
            speed: Some(0.0),
            direction: Some(0.0),
            width: Some(29.0),
        };
        sample.points = vec![start.clone()];
        if code > 7 {
            sample.points.push(Point { x: 29.0, ..start });
        }
        draw(&mut layer, &sample, 40.0, 1.0, 1.0, false);
        assert_eq!(
            format!("{:x}", Sha256::digest(&layer.data)),
            expected,
            "tool {code}, pressure {pressure}"
        );
    }
}
