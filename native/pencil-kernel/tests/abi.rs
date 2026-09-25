use rm_pencil_kernel::{rm_pencil_draw, rm_pencil_kernel_version};

fn gains() -> Vec<f64> {
    (0..65536)
        .map(|i| (0.5 * (2.0 * (i as f64 / 65535.0) - 1.0)).exp())
        .collect()
}

#[test]
fn version_is_one() {
    assert_eq!(rm_pencil_kernel_version(), 1);
}

#[test]
fn null_pointer_is_rejected() {
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                std::ptr::null_mut(),
                1,
                1,
                0,
                0,
                1.0,
                1.0,
                255,
                std::ptr::null(),
                0,
                std::ptr::null(),
                65536,
            )
        },
        1
    );
}

#[test]
fn invalid_scale_is_rejected_without_mutation() {
    let mut alpha = [19u8];
    let samples = [0.5, 0.5, 1.4, 1.0];
    let gains = gains();
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                alpha.as_mut_ptr(),
                1,
                1,
                0,
                0,
                0.0,
                1.0,
                255,
                samples.as_ptr(),
                1,
                gains.as_ptr(),
                gains.len(),
            )
        },
        2
    );
    assert_eq!(alpha, [19]);
}

#[test]
fn all_samples_are_validated_before_deposition() {
    let mut alpha = [19u8];
    let samples = [0.5, 0.5, 1.4, 1.0, f64::NAN, 0.5, 1.4, 1.0];
    let gains = gains();
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                alpha.as_mut_ptr(),
                1,
                1,
                0,
                0,
                1.0,
                1.0,
                255,
                samples.as_ptr(),
                2,
                gains.as_ptr(),
                gains.len(),
            )
        },
        3
    );
    assert_eq!(alpha, [19]);
}

#[test]
fn known_center_pixel_and_zero_pressure() {
    let mut alpha = [0u8];
    let gains = gains();
    for (occupancy, expected) in [(0.0, 0), (1.0, 173)] {
        let samples = [0.5, 0.5, 1.4, occupancy];
        assert_eq!(
            unsafe {
                rm_pencil_draw(
                    alpha.as_mut_ptr(),
                    1,
                    1,
                    0,
                    0,
                    1.0,
                    1.0,
                    173,
                    samples.as_ptr(),
                    1,
                    gains.as_ptr(),
                    gains.len(),
                )
            },
            0
        );
        assert_eq!(alpha, [expected]);
    }
}

#[test]
fn origin_overflow_is_rejected_before_mutation() {
    let mut alpha = [11u8; 2];
    let gain = gains();
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                alpha.as_mut_ptr(),
                2,
                1,
                i64::MAX,
                0,
                1.0,
                1.0,
                255,
                std::ptr::null(),
                0,
                gain.as_ptr(),
                gain.len(),
            )
        },
        2
    );
    assert_eq!(alpha, [11; 2]);
}

#[test]
fn derived_sample_overflow_is_rejected_before_mutation() {
    let mut alpha = [11u8];
    let gain = gains();
    let samples = [f64::MAX, 0.0, f64::MAX, 1.0];
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                alpha.as_mut_ptr(),
                1,
                1,
                0,
                0,
                2.0,
                2.0,
                255,
                samples.as_ptr(),
                1,
                gain.as_ptr(),
                gain.len(),
            )
        },
        3
    );
    assert_eq!(alpha, [11]);
}

#[test]
fn python_bitmap_baseline_with_negative_origin_and_anisotropic_scale() {
    let mut alpha = [0u8; 63];
    let gain = gains();
    let samples = [
        0.1,
        0.2,
        0.7,
        0.4185567010309279,
        1.8,
        1.1,
        0.45,
        0.7854639175257733,
        2.7,
        0.9,
        0.6,
        1.0,
    ];
    assert_eq!(
        unsafe {
            rm_pencil_draw(
                alpha.as_mut_ptr(),
                9,
                7,
                -2,
                -1,
                1.3333333333333333,
                2.125,
                173,
                samples.as_ptr(),
                3,
                gain.as_ptr(),
                gain.len(),
            )
        },
        0
    );
    assert_eq!(
        alpha,
        [
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 157, 0, 22, 89, 13, 0, 0, 0, 0, 89, 0, 71, 173, 70, 0,
            0, 0, 0, 76, 56, 173, 173, 29, 0, 0, 0, 0, 0, 12, 85, 107, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        ]
    );
}
