//! Raster arithmetic follows Pillow 12.3.0 AlphaComposite.c, Convert.c,
//! Draw.c, ImageDraw.py and Resample.c. See LICENSE-PILLOW (MIT-CMU).
//! Drawing algorithms from Draw.c: Copyright (c) 1996-2006 Fredrik Lundh
//! and Copyright (c) 1997-2006 Secret Labs AB.

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Image {
    pub width: usize,
    pub height: usize,
    pub data: Vec<u8>,
}

impl Image {
    pub fn new(width: usize, height: usize, color: [u8; 4]) -> Self {
        let mut data = vec![0; width * height * 4];
        for pixel in data.chunks_exact_mut(4) {
            pixel.copy_from_slice(&color);
        }
        Self {
            width,
            height,
            data,
        }
    }

    pub fn alpha_composite(&mut self, source: &Self, left: usize, top: usize) {
        let width = source.width.min(self.width.saturating_sub(left));
        let height = source.height.min(self.height.saturating_sub(top));
        if width == 0 || height == 0 {
            return;
        }
        for row in 0..height {
            let start = ((top + row) * self.width + left) * 4;
            let from = row * source.width * 4;
            for (dst, src) in self.data[start..start + width * 4]
                .chunks_exact_mut(4)
                .zip(source.data[from..from + width * 4].chunks_exact(4))
            {
                source_over(dst, src);
            }
        }
    }

    pub fn resized(&self, width: usize, height: usize, filter: Filter) -> Self {
        if (self.width, self.height) == (width, height) {
            return self.clone();
        }
        let mut associated = self.data.clone();
        for pixel in associated.chunks_exact_mut(4) {
            let alpha = u32::from(pixel[3]);
            for channel in &mut pixel[..3] {
                *channel = div_255(u32::from(*channel) * alpha + 128) as u8;
            }
        }
        let mut data = resize::<4>(associated, self.width, self.height, width, height, filter);
        for pixel in data.chunks_exact_mut(4) {
            let alpha = u32::from(pixel[3]);
            if alpha != 0 && alpha != 255 {
                for channel in &mut pixel[..3] {
                    *channel = (255 * u32::from(*channel) / alpha).min(255) as u8;
                }
            }
        }
        Self {
            width,
            height,
            data,
        }
    }
}

fn div_255(value: u32) -> u32 {
    ((value >> 8) + value) >> 8
}

fn source_over(dst: &mut [u8], src: &[u8]) {
    let sa = u32::from(src[3]);
    if sa == 0 {
        return;
    }
    let blended = u32::from(dst[3]) * (255 - sa);
    let alpha = sa * 255 + blended;
    let source = sa * 255 * 255 * 128 / alpha;
    let backdrop = 255 * 128 - source;
    for channel in 0..3 {
        let value = u32::from(src[channel]) * source + u32::from(dst[channel]) * backdrop;
        dst[channel] = (div_255(value + (128 << 7)) >> 7) as u8;
    }
    dst[3] = div_255(alpha + 128) as u8;
}

#[derive(Clone, Copy)]
pub enum Filter {
    Box,
    Bilinear,
    Lanczos,
}

impl Filter {
    fn support(self) -> f64 {
        match self {
            Self::Box => 0.5,
            Self::Bilinear => 1.0,
            Self::Lanczos => 3.0,
        }
    }

    fn weight(self, x: f64) -> f64 {
        match self {
            Self::Box => u8::from(x > -0.5 && x <= 0.5).into(),
            Self::Bilinear => (1.0 - x.abs()).max(0.0),
            Self::Lanczos if (-3.0..3.0).contains(&x) => sinc(x) * sinc(x / 3.0),
            Self::Lanczos => 0.0,
        }
    }
}

fn sinc(x: f64) -> f64 {
    if x == 0.0 {
        1.0
    } else {
        let x = x * std::f64::consts::PI;
        x.sin() / x
    }
}

const PRECISION: u32 = 22;

fn weights(source: usize, target: usize, filter: Filter) -> Vec<(usize, Vec<i32>)> {
    let scale = source as f64 / target as f64;
    let inverse = 1.0 / scale.max(1.0);
    let support = filter.support() * scale.max(1.0);
    (0..target)
        .map(|coordinate| {
            let center = (coordinate as f64 + 0.5) * scale;
            let first = (center - support + 0.5) as usize;
            let last = source.min((center + support + 0.5) as usize);
            let raw: Vec<_> = (first..last)
                .map(|index| filter.weight((index as f64 - center + 0.5) * inverse))
                .collect();
            let sum: f64 = raw.iter().sum();
            let coefficients = raw
                .into_iter()
                .map(|weight| {
                    let normalized = if sum == 0.0 { weight } else { weight / sum };
                    (normalized * f64::from(1 << PRECISION)).round() as i32
                })
                .collect();
            (first, coefficients)
        })
        .collect()
}

fn resampled_pixel<const N: usize>(sample: impl Fn(usize, usize) -> u8, coeff: &[i32]) -> [u8; N] {
    let mut result = [0; N];
    for (channel, output) in result.iter_mut().enumerate() {
        let mut sum = 1_i32 << (PRECISION - 1);
        for (index, weight) in coeff.iter().enumerate() {
            sum += i32::from(sample(index, channel)) * weight;
        }
        *output = (sum >> PRECISION).clamp(0, 255) as u8;
    }
    result
}

fn resize<const N: usize>(
    mut data: Vec<u8>,
    source_width: usize,
    source_height: usize,
    width: usize,
    height: usize,
    filter: Filter,
) -> Vec<u8> {
    if source_width != width {
        let columns = weights(source_width, width, filter);
        let mut output = Vec::with_capacity(width * source_height * N);
        for row in 0..source_height {
            for (first, coeff) in &columns {
                output.extend(resampled_pixel::<N>(
                    |index, channel| data[(row * source_width + first + index) * N + channel],
                    coeff,
                ));
            }
        }
        data = output;
    }
    if source_height != height {
        let rows = weights(source_height, height, filter);
        let mut output = Vec::with_capacity(width * height * N);
        for (first, coeff) in &rows {
            for column in 0..width {
                output.extend(resampled_pixel::<N>(
                    |index, channel| data[((first + index) * width + column) * N + channel],
                    coeff,
                ));
            }
        }
        data = output;
    }
    data
}

pub fn resize_mask(
    mask: &[u8],
    width: usize,
    height: usize,
    new_width: usize,
    new_height: usize,
    filter: Filter,
) -> Vec<u8> {
    resize::<1>(mask.to_vec(), width, height, new_width, new_height, filter)
}

pub(crate) type Position = (f64, f64);
type Pixel = (i32, i32);

pub(crate) struct Bounds {
    pub left: usize,
    pub top: usize,
    pub width: usize,
    pub height: usize,
}

impl Bounds {
    pub fn clipped(layer: &Image, left: f64, top: f64, right: f64, bottom: f64) -> Option<Self> {
        let (left, top) = (left as usize, top as usize);
        let (right, bottom) = (
            layer.width.min(right as usize),
            layer.height.min(bottom as usize),
        );
        (right > left && bottom > top).then(|| Self {
            left,
            top,
            width: right - left,
            height: bottom - top,
        })
    }

    pub fn local(&self, point: Position, supersample: usize) -> Position {
        let ss = supersample as f64;
        (
            (point.0 - self.left as f64) * ss,
            (point.1 - self.top as f64) * ss,
        )
    }
}

pub(crate) fn extent(points: &[Position]) -> (f64, f64, f64, f64) {
    points.iter().fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |(left, top, right, bottom), &(x, y)| {
            (left.min(x), top.min(y), right.max(x), bottom.max(y))
        },
    )
}

pub(crate) fn ink_from_mask(mask: &[u8], width: usize, height: usize, color: [u8; 4]) -> Image {
    let mut image = Image::new(width, height, color);
    for (pixel, &alpha) in image.data.chunks_exact_mut(4).zip(mask) {
        pixel[3] = div_255(u32::from(alpha) * u32::from(color[3]) + 128) as u8;
    }
    image
}

pub(crate) fn darken(layer: &mut Image, ink: &Image, bounds: &Bounds) {
    for y in 0..ink.height {
        let start = ((bounds.top + y) * layer.width + bounds.left) * 4;
        let source_start = y * ink.width * 4;
        for (dst, src) in layer.data[start..start + ink.width * 4]
            .chunks_exact_mut(4)
            .zip(ink.data[source_start..source_start + ink.width * 4].chunks_exact(4))
        {
            let sa = f64::from(src[3]) / 255.0;
            let da = f64::from(dst[3]) / 255.0;
            let alpha = sa + da * (1.0 - sa);
            for channel in 0..3 {
                let s = f64::from(src[channel]) / 255.0;
                let d = f64::from(dst[channel]) / 255.0;
                let premul = sa * (1.0 - da) * s + sa * da * s.min(d) + (1.0 - sa) * da * d;
                let color = if alpha > 0.0 { premul / alpha } else { 0.0 };
                dst[channel] = (color.clamp(0.0, 1.0) * 255.0).round_ties_even() as u8;
            }
            dst[3] = (alpha.clamp(0.0, 1.0) * 255.0).round_ties_even() as u8;
        }
    }
}

pub(crate) trait Surface<const N: usize> {
    fn size(&self) -> (usize, usize);
    fn pixels(&mut self) -> &mut [u8];

    fn span(&mut self, x0: i32, y: i32, x1: i32, ink: [u8; N]) {
        let (width, height) = self.size();
        let left = x0.max(0) as usize;
        let right = (i64::from(x1) + 1).max(0) as usize;
        let right = right.min(width);
        if y < 0 || y as usize >= height || right <= left {
            return;
        }
        let offset = y as usize * width;
        for pixel in self.pixels()[(offset + left) * N..(offset + right) * N].chunks_exact_mut(N) {
            pixel.copy_from_slice(&ink);
        }
    }
}

impl Surface<4> for Image {
    fn size(&self) -> (usize, usize) {
        (self.width, self.height)
    }

    fn pixels(&mut self) -> &mut [u8] {
        &mut self.data
    }
}

pub(crate) struct Mask {
    pub width: usize,
    pub height: usize,
    pub data: Vec<u8>,
}

impl Mask {
    pub fn new(width: usize, height: usize) -> Self {
        Self {
            width,
            height,
            data: vec![0; width * height],
        }
    }

    pub fn resized(self, width: usize, height: usize, filter: Filter) -> Vec<u8> {
        resize::<1>(self.data, self.width, self.height, width, height, filter)
    }
}

impl Surface<1> for Mask {
    fn size(&self) -> (usize, usize) {
        (self.width, self.height)
    }

    fn pixels(&mut self) -> &mut [u8] {
        &mut self.data
    }
}

fn pixel(position: Position) -> Pixel {
    (position.0 as i32, position.1 as i32)
}

pub(crate) fn rectangle<const N: usize>(
    surface: &mut impl Surface<N>,
    start: Position,
    end: Position,
    ink: [u8; N],
) {
    let (x0, y0) = pixel(start);
    let (x1, y1) = pixel(end);
    for y in y0.max(0)..=y1.min(surface.size().1 as i32 - 1) {
        surface.span(x0, y, x1, ink);
    }
}

#[derive(Clone, Copy)]
struct Edge {
    start: Pixel,
    xmin: i32,
    xmax: i32,
    ymin: i32,
    ymax: i32,
    slope: f32,
}

impl Edge {
    fn new(start: Pixel, end: Pixel) -> Self {
        Self {
            start,
            xmin: start.0.min(end.0),
            xmax: start.0.max(end.0),
            ymin: start.1.min(end.1),
            ymax: start.1.max(end.1),
            slope: if start.1 == end.1 {
                0.0
            } else {
                (i64::from(end.0) - i64::from(start.0)) as f32
                    / (i64::from(end.1) - i64::from(start.1)) as f32
            },
        }
    }

    fn covers(self, y: i32) -> bool {
        (self.ymin..=self.ymax).contains(&y)
    }

    fn x(self, y: i32) -> f32 {
        (i64::from(y) - i64::from(self.start.1)) as f32 * self.slope + self.start.0 as f32
    }
}

pub(crate) fn polygon<const N: usize>(
    surface: &mut impl Surface<N>,
    positions: &[Position],
    ink: [u8; N],
) {
    let points: Vec<_> = positions.iter().copied().map(pixel).collect();
    let mut edges: Vec<Edge> = Vec::with_capacity(points.len());
    for (index, pair) in points.windows(2).enumerate() {
        let [start, end] = [pair[0], pair[1]];
        if index != 0 && start.1 == end.1 && points[index - 1].1 == start.1 {
            let previous_x = points[index - 1].0;
            let previous = edges.last_mut().expect("there is a previous edge");
            if previous_x < start.0 && start.0 < end.0 {
                previous.xmax = end.0;
                continue;
            }
            if previous_x > start.0 && start.0 > end.0 {
                previous.xmin = end.0;
                continue;
            }
        }
        edges.push(Edge::new(start, end));
    }
    if let (Some(&first), Some(&last)) = (points.first(), points.last()) {
        if first != last {
            edges.push(Edge::new(last, first));
        }
    }
    scan_edges(surface, &edges, ink);
}

fn scan_edges<const N: usize>(surface: &mut impl Surface<N>, edges: &[Edge], ink: [u8; N]) {
    let height = surface.size().1 as i32;
    let mut first = height - 1;
    let mut last = 0;
    for edge in edges {
        first = first.min(edge.ymin);
        last = last.max(edge.ymax);
        if edge.ymin == edge.ymax {
            surface.span(edge.xmin, edge.ymin, edge.xmax, ink);
        }
    }
    let last = last.min(height);
    let mut hits = Vec::with_capacity(edges.len() * 2);
    for y in first.max(0)..=last {
        hits.clear();
        for (index, edge) in edges.iter().enumerate() {
            if edge.ymin == edge.ymax || !edge.covers(y) {
                continue;
            }
            let mut x = edge.x(y);
            if y == edge.ymax && y < last {
                hits.push(x);
            } else if (y == edge.ymin || y == edge.ymax) && edge.slope != 0.0 {
                let next_y = y + if y == edge.ymax { -1 } else { 1 };
                for other in &edges[..index] {
                    if (y == other.ymin || y == other.ymax)
                        && other.slope != 0.0
                        && other.covers(next_y)
                        && x.round() == other.x(y).round()
                    {
                        let next_x = edge.x(next_y);
                        let other_x = other.x(next_y);
                        if x > next_x + 1.0 && x > other_x + 1.0 {
                            x = next_x.max(other_x).round() + 1.0;
                        } else if x < next_x - 1.0 && x < other_x - 1.0 {
                            x = next_x.min(other_x).round() - 1.0;
                        }
                        break;
                    }
                }
            }
            hits.push(x);
        }
        hits.sort_unstable_by(f32::total_cmp);
        for pair in hits.chunks_exact(2) {
            let start = (pair[0].abs() + 0.5).floor().copysign(pair[0]);
            let end = (pair[1].abs() - 0.5).ceil().copysign(pair[1]);
            surface.span(start as i32, y, end as i32, ink);
        }
    }
}

// Draw.c's filled ellipse uses the first boundary point reached on each
// doubled-coordinate scanline, with a specified tie order for its steps.
fn ellipse_rows(a: i32, b: i32, mut row: impl FnMut(i32, i32, i32)) {
    if a < 0 || b < 0 || (a == 0 && b == 0) {
        return;
    }
    let a2 = i128::from(a) * i128::from(a);
    let b2 = i128::from(b) * i128::from(b);
    let error =
        |x: i32, y: i32| (a2 * i128::from(y).pow(2) + b2 * i128::from(x).pow(2) - a2 * b2).abs();
    let mut x = a;
    let mut y = b % 2;
    let mut previous_y = -1;
    loop {
        if y != previous_y {
            row(-x, -y, x);
            if y != 0 {
                row(-x, y, x);
            }
            previous_y = y;
        }
        if x == a % 2 && y == b {
            break;
        }
        let mut next = (x, y + 2);
        if x > 1 {
            if error(next.0, next.1) > error(x - 2, y + 2) {
                next = (x - 2, y + 2);
            }
            if error(next.0, next.1) > error(x - 2, y) {
                next = (x - 2, y);
            }
        }
        (x, y) = next;
    }
}

pub(crate) fn ellipse<const N: usize>(
    surface: &mut impl Surface<N>,
    start: Position,
    end: Position,
    ink: [u8; N],
) {
    let (x0, y0) = pixel(start);
    let (x1, y1) = pixel(end);
    let (width, height) = surface.size();
    if x0 >= width as i32 || y0 >= height as i32 || x1 < 0 || y1 < 0 {
        return;
    }
    let a = x1.saturating_sub(x0);
    let b = y1.saturating_sub(y0);
    ellipse_rows(a, b, |left, y, right| {
        surface.span(
            x0 + (left + a) / 2,
            y0 + (y + b) / 2,
            x0 + (right + a) / 2,
            ink,
        );
    });
}

fn line1<const N: usize>(surface: &mut impl Surface<N>, a: Pixel, b: Pixel, ink: [u8; N]) {
    let (dx, dy) = (
        i64::from(b.0) - i64::from(a.0),
        i64::from(b.1) - i64::from(a.1),
    );
    let horizontal = dx.abs() >= dy.abs();
    let (major, minor, start, limit) = if horizontal {
        (dx, dy, i64::from(a.0), surface.size().0 as i64)
    } else {
        (dy, dx, i64::from(a.1), surface.size().1 as i64)
    };
    let (first, last) = if major >= 0 {
        ((-start).max(0), (limit - start).min(major))
    } else {
        ((start - limit + 1).max(0), (start + 1).min(-major))
    };
    let steps = major.abs();
    for step in first..last {
        let along = step * major.signum();
        // This is the Bresenham tie rule with the invisible prefix skipped.
        let across = ((i128::from(step) * i128::from(minor.abs()) * 2 + i128::from(steps))
            / (2 * i128::from(steps))) as i64
            * minor.signum();
        let (x, y) = if horizontal {
            (along, across)
        } else {
            (across, along)
        };
        let x = (i64::from(a.0) + x) as i32;
        let y = (i64::from(a.1) + y) as i32;
        surface.span(x, y, x, ink);
    }
}

fn round_down(value: f64) -> f64 {
    (value.abs() - 0.5).ceil().copysign(value)
}

fn wide_line<const N: usize>(
    surface: &mut impl Surface<N>,
    a: Pixel,
    b: Pixel,
    width: i32,
    ink: [u8; N],
) {
    let (dx, dy) = (
        f64::from(b.0) - f64::from(a.0),
        f64::from(b.1) - f64::from(a.1),
    );
    if a == b {
        surface.span(a.0, a.1, a.0, ink);
        return;
    }
    let length = dx.hypot(dy);
    let half = f64::from(width - 1) / 2.0;
    let outer = half.round() / length;
    let inner = round_down(half) / length;
    let (min_x, max_x) = (round_down(inner * dy), round_down(outer * dy));
    let (min_y, max_y) = (round_down(inner * dx), round_down(outer * dx));
    let vertices = [
        pixel((f64::from(a.0) - min_x, f64::from(a.1) + max_y)),
        pixel((f64::from(b.0) - min_x, f64::from(b.1) + max_y)),
        pixel((f64::from(b.0) + max_x, f64::from(b.1) - min_y)),
        pixel((f64::from(a.0) + max_x, f64::from(a.1) - min_y)),
    ];
    let edges = std::array::from_fn::<_, 4, _>(|index| {
        Edge::new(vertices[index], vertices[(index + 1) % 4])
    });
    scan_edges(surface, &edges, ink);
}

pub(crate) fn line<const N: usize>(
    surface: &mut impl Surface<N>,
    points: &[Position],
    width: i32,
    curved: bool,
    ink: [u8; N],
) {
    let points_i: Vec<_> = points.iter().copied().map(pixel).collect();
    for pair in points_i.windows(2) {
        if width == 1 {
            line1(surface, pair[0], pair[1], ink);
        } else {
            wide_line(surface, pair[0], pair[1], width, ink);
        }
    }
    if width == 1 && points_i.len() > 1 {
        let (x, y) = points_i[points_i.len() - 1];
        surface.span(x, y, x, ink);
    }
    if curved && width > 4 {
        for triple in points.windows(3) {
            curve_join(surface, triple[0], triple[1], triple[2], width, ink);
        }
    }
}

fn curve_join<const N: usize>(
    surface: &mut impl Surface<N>,
    previous: Position,
    point: Position,
    next: Position,
    width: i32,
    ink: [u8; N],
) {
    let angle =
        |a: Position, b: Position| (b.0 - a.0).atan2(a.1 - b.1).to_degrees().rem_euclid(360.0);
    let (incoming, outgoing) = (angle(previous, point), angle(point, next));
    if incoming == outgoing {
        return;
    }
    let flipped = (outgoing > incoming && outgoing - 180.0 > incoming)
        || (outgoing < incoming && outgoing + 180.0 > incoming);
    let distance = f64::from(width) / 2.0 - 1.0;
    let (start, end) = if flipped {
        (outgoing, incoming)
    } else {
        (incoming - 180.0, outgoing - 180.0)
    };
    pie(
        surface,
        (point.0 - distance, point.1 - distance),
        (point.0 + distance, point.1 + distance),
        start,
        end,
        ink,
    );
    if width > 8 {
        let offset = |angle: f64| {
            let angle = angle.to_radians();
            (
                point.0 + (distance * angle.cos()).trunc(),
                point.1 + (distance * angle.sin()).trunc(),
            )
        };
        let shift = if flipped { 0.0 } else { -180.0 };
        line(
            surface,
            &[offset(incoming + shift), point, offset(outgoing + shift)],
            3,
            false,
            ink,
        );
    }
}

fn pie<const N: usize>(
    surface: &mut impl Surface<N>,
    start: Position,
    end: Position,
    angle0: f64,
    angle1: f64,
    ink: [u8; N],
) {
    let angle0 = angle0 as f32;
    let angle1 = angle1 as f32;
    let start_angle = angle0.rem_euclid(360.0);
    let end_angle = start_angle + (angle1 - start_angle).rem_euclid(360.0);
    let sweep = end_angle - start_angle;
    if sweep == 0.0 {
        return;
    }
    let (x0, y0) = pixel(start);
    let (x1, y1) = pixel(end);
    let (a, b) = (x1.saturating_sub(x0), y1.saturating_sub(y0));
    let point_at = |angle: f32| {
        let radians = f64::from(angle) * std::f64::consts::PI / 180.0;
        (f64::from(a) * radians.cos(), f64::from(b) * radians.sin())
    };
    let (lx, ly) = point_at(start_angle);
    let (rx, ry) = point_at(end_angle);
    ellipse_rows(a, b, |left, y, right| {
        let span = (left, right);
        let left_side = clip_half_plane(span, y, -ly, lx);
        let right_side = clip_half_plane(span, y, ry, -rx);
        let mut emit = |mut span| {
            if sweep < 90.0 {
                let Some(clipped) = clip_half_plane(span, y, (lx + rx) / 2.0, (ly + ry) / 2.0)
                else {
                    return;
                };
                span = clipped;
            }
            let (left, right) = span;
            surface.span(
                x0 + (left + a) / 2,
                y0 + (y + b) / 2,
                x0 + (right + a) / 2,
                ink,
            );
        };
        if sweep < 180.0 {
            if let (Some(l), Some(r)) = (left_side, right_side) {
                let intersection = (l.0.max(r.0), l.1.min(r.1));
                if intersection.0 <= intersection.1 {
                    emit(intersection);
                }
            }
        } else {
            for side in [left_side, right_side].into_iter().flatten() {
                emit(side);
            }
        }
    });
}

fn clip_half_plane((mut left, mut right): Pixel, y: i32, a: f64, b: f64) -> Option<Pixel> {
    const EPSILON: f64 = 1e-9;
    let by = b * f64::from(y);
    if a.abs() < EPSILON {
        return (by >= -EPSILON).then_some((left, right));
    }
    let intersection = -by / a;
    if a * f64::from(left) + by < EPSILON {
        left = f64::from(left).max(intersection).round() as i32;
    }
    if a * f64::from(right) + by < EPSILON {
        right = f64::from(right).min(intersection).round() as i32;
    }
    (left <= right).then_some((left, right))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_over_and_resampling_follow_pillow_integer_rounding() {
        let mut image = Image::new(2, 2, [71, 117, 19, 101]);
        let source = Image::new(1, 1, [222, 31, 103, 153]);
        image.alpha_composite(&source, 1, 0);
        assert_eq!(
            image.data,
            [71, 117, 19, 101, 190, 49, 85, 193, 71, 117, 19, 101, 71, 117, 19, 101]
        );
        assert_eq!(image.resized(1, 1, Filter::Box).data, [117, 90, 45, 124]);
        assert_eq!(
            resize_mask(&[0, 64, 128, 255, 0, 255], 3, 2, 2, 1, Filter::Box),
            [80, 192]
        );
    }

    #[test]
    fn clipped_polygon_and_ellipse_follow_pillow_scanlines() {
        let mut canvas = Image::new(8, 7, [0; 4]);
        polygon(
            &mut canvas,
            &[(0.4, 3.5), (5.7, -1.3), (7.5, 5.4), (2.8, 6.1)],
            [255; 4],
        );
        let rows = |image: &Image| -> Vec<String> {
            image
                .data
                .chunks_exact(8 * 4)
                .map(|row| {
                    row.chunks_exact(4)
                        .map(|pixel| if pixel[0] == 0 { '.' } else { '#' })
                        .collect()
                })
                .collect()
        };
        assert_eq!(
            rows(&canvas),
            ["....##..", "...####.", ".######.", "#######.", ".#######", ".#######", "..#....."]
        );
        let mut canvas = Image::new(8, 7, [0; 4]);
        ellipse(&mut canvas, (2.4, 0.8), (6.8, 5.9), [255; 4]);
        ellipse(&mut canvas, (1., 6.), (1., 6.), [255; 4]);
        assert_eq!(
            rows(&canvas),
            ["...###..", "..#####.", "..#####.", "..#####.", "..#####.", "...###..", "........"]
        );
    }
}
