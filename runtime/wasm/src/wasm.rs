//! Raw browser ABI (no wasm-bindgen). The page provides randomness, a clock and a panic sink;
//! results are JSON bytes read back from linear memory.
use std::sync::Mutex;

#[link(wasm_import_module = "env")]
extern "C" {
    fn kj_random_fill(ptr: *mut u8, len: usize) -> i32;
    fn kj_now_ms() -> f64;
    fn kj_panic(ptr: *const u8, len: usize);
}

static OUTPUT: Mutex<Vec<u8>> = Mutex::new(Vec::new());

pub fn now_ms() -> f64 {
    unsafe { kj_now_ms() }
}

/// getrandom 0.3 custom backend (built with `--cfg getrandom_backend="custom"`).
/// Used only by hash-map seeding in dependencies; inference does not sample.
#[no_mangle]
unsafe extern "Rust" fn __getrandom_v03_custom(
    dest: *mut u8,
    len: usize,
) -> Result<(), getrandom::Error> {
    if kj_random_fill(dest, len) == 0 {
        Ok(())
    } else {
        Err(getrandom::Error::UNSUPPORTED)
    }
}

fn finish(result: anyhow::Result<serde_json::Value>) -> i32 {
    let (code, value) = match result {
        Ok(value) => (0, value),
        Err(error) => (1, serde_json::json!({"error": format!("{error:#}")})),
    };
    *OUTPUT.lock().unwrap() = serde_json::to_vec(&value).unwrap();
    code
}

#[no_mangle]
pub extern "C" fn kj_init() {
    std::panic::set_hook(Box::new(|info| {
        let message = info.to_string();
        unsafe { kj_panic(message.as_ptr(), message.len()) }
    }));
}

#[no_mangle]
pub extern "C" fn kj_alloc(len: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(len);
    let ptr = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    ptr
}

/// # Safety
/// `ptr`/`capacity` must come from one `kj_alloc` call.
#[no_mangle]
pub unsafe extern "C" fn kj_free(ptr: *mut u8, capacity: usize) {
    drop(Vec::from_raw_parts(ptr, 0, capacity));
}

#[no_mangle]
pub extern "C" fn kj_environment() -> i32 {
    finish(Ok(crate::environment()))
}

#[no_mangle]
pub extern "C" fn kj_ops() -> i32 {
    finish(crate::ops::run())
}

/// # Safety
/// Both ranges must be initialized bytes allocated with `kj_alloc`.
#[no_mangle]
pub unsafe extern "C" fn kj_tokenize(
    tokenizer: *const u8,
    tokenizer_len: usize,
    job: *const u8,
    job_len: usize,
) -> i32 {
    let tokenizer = std::slice::from_raw_parts(tokenizer, tokenizer_len);
    let job = std::slice::from_raw_parts(job, job_len);
    finish(crate::tokenize::run(tokenizer, job))
}

/// # Safety
/// Every (ptr, len) pair must be initialized bytes allocated with `kj_alloc`.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn kj_decide(
    manifest: *const u8,
    manifest_len: usize,
    decision_config: *const u8,
    decision_config_len: usize,
    tokenizer: *const u8,
    tokenizer_len: usize,
    readout: *const u8,
    readout_len: usize,
    model: *const u8,
    model_len: usize,
    request: *const u8,
    request_len: usize,
    max_input_tokens: usize,
) -> i32 {
    let bytes = |ptr, len| std::slice::from_raw_parts(ptr, len);
    let assets = crate::decide::Assets {
        manifest: bytes(manifest, manifest_len),
        decision_config: bytes(decision_config, decision_config_len),
        tokenizer: bytes(tokenizer, tokenizer_len),
        readout: bytes(readout, readout_len),
        model: bytes(model, model_len),
    };
    finish(crate::decide::decide(
        &assets,
        bytes(request, request_len),
        max_input_tokens,
    ))
}

thread_local! {
    static SESSION: std::cell::RefCell<Option<crate::decide::Session<'static>>> =
        const { std::cell::RefCell::new(None) };
}

/// Opens (replacing any previous) session over page-owned asset buffers.
///
/// # Safety
/// Every (ptr, len) pair must be initialized bytes allocated with `kj_alloc`. The readout,
/// model, tokenizer and config buffers must stay allocated and unchanged until
/// `kj_session_close` or the next open.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn kj_session_open(
    manifest: *const u8,
    manifest_len: usize,
    decision_config: *const u8,
    decision_config_len: usize,
    tokenizer: *const u8,
    tokenizer_len: usize,
    readout: *const u8,
    readout_len: usize,
    model: *const u8,
    model_len: usize,
) -> i32 {
    SESSION.with(|s| s.borrow_mut().take());
    let bytes = |ptr, len| -> &'static [u8] { std::slice::from_raw_parts(ptr, len) };
    let assets = crate::decide::Assets {
        manifest: bytes(manifest, manifest_len),
        decision_config: bytes(decision_config, decision_config_len),
        tokenizer: bytes(tokenizer, tokenizer_len),
        readout: bytes(readout, readout_len),
        model: bytes(model, model_len),
    };
    finish(
        crate::decide::Session::open(&assets).map(|(session, stages)| {
            SESSION.with(|s| *s.borrow_mut() = Some(session));
            serde_json::json!({"stages": stages})
        }),
    )
}

/// # Safety
/// `request` must be initialized bytes allocated with `kj_alloc`.
#[no_mangle]
pub unsafe extern "C" fn kj_session_decide(
    request: *const u8,
    request_len: usize,
    max_input_tokens: usize,
) -> i32 {
    let request = std::slice::from_raw_parts(request, request_len);
    finish(SESSION.with(|s| match s.borrow().as_ref() {
        Some(session) => session.decide(request, max_input_tokens),
        None => Err(anyhow::anyhow!("no open session")),
    }))
}

#[no_mangle]
pub extern "C" fn kj_session_close() {
    SESSION.with(|s| s.borrow_mut().take());
}

#[no_mangle]
pub extern "C" fn kj_output_ptr() -> *const u8 {
    OUTPUT.lock().unwrap().as_ptr()
}

#[no_mangle]
pub extern "C" fn kj_output_len() -> usize {
    OUTPUT.lock().unwrap().len()
}
