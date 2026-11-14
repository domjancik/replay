fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1)
    }
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        return Err("Usage: rmdoc-json RAW_FILE OPTIONS_JSON_FILE".into());
    }
    let raw = std::fs::read(&args[1])?;
    let options: serde_json::Value = serde_json::from_slice(&std::fs::read(&args[2])?)?;
    let value = rm_rmdoc::bridge::execute(&raw, &options)?;
    serde_json::to_writer(std::io::stdout().lock(), &value)?;
    Ok(())
}
