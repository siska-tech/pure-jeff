//! Raw browser ABI (no wasm-bindgen). The page provides randomness, a clock and a panic sink
//! (`env.kj_random_fill`, `env.kj_now_ms`, `env.kj_panic`, the import names of the earlier
//! Wasm probe); results are JSON bytes read back from linear memory.
use crate::{Assets, Session, StreamHash};
use std::cell::RefCell;

#[link(wasm_import_module = "env")]
extern "C" {
    fn kj_random_fill(ptr: *mut u8, len: usize) -> i32;
    fn kj_now_ms() -> f64;
    fn kj_panic(ptr: *const u8, len: usize);
}

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

thread_local! {
    static OUTPUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
    static HASHES: RefCell<[Option<StreamHash>; 4]> = const { RefCell::new([None, None, None, None]) };
    static SESSION: RefCell<Option<Session<'static>>> = const { RefCell::new(None) };
}

/// Serializes the value directly, so struct fields (e.g. `Attempt`) keep their declared order.
fn finish<T: serde::Serialize>(result: anyhow::Result<T>) -> i32 {
    let (code, bytes) = match result {
        Ok(value) => (0, serde_json::to_vec(&value)),
        Err(error) => (
            1,
            serde_json::to_vec(&serde_json::json!({"error": format!("{error:#}")})),
        ),
    };
    OUTPUT.with(|o| *o.borrow_mut() = bytes.unwrap());
    code
}

#[derive(serde::Serialize)]
struct Evaluated {
    attempt: pure_jeff::Attempt,
    stages: Vec<serde_json::Value>,
}

/// # Safety
/// The range must be `len` initialized bytes.
unsafe fn bytes(ptr: *const u8, len: usize) -> &'static [u8] {
    std::slice::from_raw_parts(ptr, len)
}

#[no_mangle]
pub extern "C" fn demo_init() {
    std::panic::set_hook(Box::new(|info| {
        let message = info.to_string();
        unsafe { kj_panic(message.as_ptr(), message.len()) }
    }));
}

#[no_mangle]
pub extern "C" fn demo_alloc(len: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(len);
    let ptr = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    ptr
}

/// # Safety
/// `ptr`/`capacity` must come from one `demo_alloc` call and no open session may use it.
#[no_mangle]
pub unsafe extern "C" fn demo_free(ptr: *mut u8, capacity: usize) {
    drop(Vec::from_raw_parts(ptr, 0, capacity));
}

/// Starts the streamed digest of asset `slot` (`ASSET_PATHS` order) of `len` bytes.
#[no_mangle]
pub extern "C" fn demo_hash_begin(slot: usize, len: usize) -> i32 {
    HASHES.with(|h| match h.borrow_mut().get_mut(slot) {
        Some(entry) => {
            *entry = Some(StreamHash::new(len));
            0
        }
        None => 1,
    })
}

/// Hashes a chunk the page has just written to linear memory.
///
/// # Safety
/// `ptr`/`len` must be initialized bytes.
#[no_mangle]
pub unsafe extern "C" fn demo_hash_update(
    slot: usize,
    offset: usize,
    ptr: *const u8,
    len: usize,
) -> i32 {
    HASHES.with(
        |h| match h.borrow_mut().get_mut(slot).and_then(|e| e.as_mut()) {
            Some(stream) => i32::from(stream.update(offset, bytes(ptr, len)).is_err()),
            None => 1,
        },
    )
}

/// Opens (replacing any previous) session. Streamed digests are consumed; an asset whose
/// stream was incomplete is hashed here instead.
///
/// # Safety
/// Every range must be initialized bytes that stay allocated and unchanged until
/// `demo_close` or the next open.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn demo_open(
    manifest: *const u8,
    manifest_len: usize,
    config: *const u8,
    config_len: usize,
    tokenizer: *const u8,
    tokenizer_len: usize,
    readout: *const u8,
    readout_len: usize,
    model: *const u8,
    model_len: usize,
    expected_manifest_sha256: *const u8,
    expected_manifest_sha256_len: usize,
    engine_sha256: *const u8,
    engine_sha256_len: usize,
) -> i32 {
    SESSION.with(|s| s.borrow_mut().take());
    let streamed = HASHES.with(|h| {
        h.borrow_mut()
            .each_mut()
            .map(|e| e.take().and_then(StreamHash::finish))
    });
    let assets = Assets {
        manifest: bytes(manifest, manifest_len),
        files: [
            bytes(config, config_len),
            bytes(tokenizer, tokenizer_len),
            bytes(readout, readout_len),
            bytes(model, model_len),
        ],
    };
    let text = |ptr, len| std::str::from_utf8(bytes(ptr, len)).unwrap_or("");
    finish(
        Session::open(
            &assets,
            streamed,
            text(expected_manifest_sha256, expected_manifest_sha256_len),
            text(engine_sha256, engine_sha256_len),
        )
        .map(|(session, report)| {
            SESSION.with(|s| *s.borrow_mut() = Some(session));
            report
        }),
    )
}

/// Returns `{"attempt": ..., "stages": [...]}`; an unparsable or invalid request is code 1.
///
/// # Safety
/// `request` must be initialized bytes.
#[no_mangle]
pub unsafe extern "C" fn demo_evaluate(
    request: *const u8,
    request_len: usize,
    max_input_bytes: usize,
    max_input_tokens: usize,
) -> i32 {
    let result = (|| {
        let request: pure_jeff::DecisionRequest =
            serde_json::from_slice(bytes(request, request_len))?;
        SESSION.with(|s| {
            let session = s.borrow();
            let session = session
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("no open session"))?;
            let (attempt, stages) = session
                .evaluate(request, max_input_bytes, max_input_tokens)
                .map_err(|failure| anyhow::anyhow!("invalid request: {failure:?}"))?;
            Ok(Evaluated { attempt, stages })
        })
    })();
    finish(result)
}

#[no_mangle]
pub extern "C" fn demo_close() {
    SESSION.with(|s| s.borrow_mut().take());
}

#[no_mangle]
pub extern "C" fn demo_output_ptr() -> *const u8 {
    OUTPUT.with(|o| o.borrow().as_ptr())
}

#[no_mangle]
pub extern "C" fn demo_output_len() -> usize {
    OUTPUT.with(|o| o.borrow().len())
}
