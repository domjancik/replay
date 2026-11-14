use std::{env, fs, io::Read, process};
const MAX_INPUT: usize = 32 * 1024 * 1024;

fn read_request(reader: impl Read) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    reader
        .take((MAX_INPUT + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_INPUT {
        return Err("request exceeds 32 MiB".into());
    }
    Ok(bytes)
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        process::exit(1);
    }
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: render-json input.json output.rgba".into());
    }
    let bytes = read_request(fs::File::open(&args[1])?)?;
    let request = serde_json::from_slice(&bytes)?;
    let image = redraw::render::render(&request)?;
    fs::write(&args[2], &image.data)?;
    println!(
        "{}",
        serde_json::json!({"width":image.width,"height":image.height,"bytes":image.data.len()})
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn oversized_input_stops_reading_at_limit_plus_one() {
        let mut source = std::io::repeat(0).take((MAX_INPUT * 2) as u64);
        assert!(read_request(&mut source).is_err());
        assert_eq!(source.limit(), (MAX_INPUT - 1) as u64);
    }
}
