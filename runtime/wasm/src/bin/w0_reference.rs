//! Native (x86_64) run of the same W0 fixtures; the browser output is compared against it.
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [tokenizer, job, output] = args.as_slice() else {
        anyhow::bail!("usage: w0_reference <tokenizer.json> <tokenize-job.json> <output.json>");
    };
    anyhow::ensure!(
        !std::path::Path::new(output).exists(),
        "output already exists"
    );
    let environment = kaze_judge_wasm_probe::environment();
    let ops = kaze_judge_wasm_probe::ops::run()?;
    let tokenize =
        kaze_judge_wasm_probe::tokenize::run(&std::fs::read(tokenizer)?, &std::fs::read(job)?)?;
    let value = serde_json::json!({"environment": environment, "ops": ops, "tokenize": tokenize});
    std::fs::write(output, serde_json::to_vec(&value)?)?;
    Ok(())
}
