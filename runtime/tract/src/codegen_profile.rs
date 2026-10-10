//! Time public TypedPass callbacks without changing the pinned optimizer driver.
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fmt,
    sync::{Arc, Mutex},
    time::Instant,
};
use tract_onnx::{
    prelude::*,
    tract_core::optim::{Optimizer, OptimizerSession, TypedPass},
};

#[derive(Clone, Default)]
struct Counters {
    reset_calls: u64,
    next_calls: u64,
    direct_calls: u64,
    patches: u64,
    direct_changes: u64,
    reset_ns: u128,
    next_ns: u128,
    direct_ns: u128,
}

#[derive(Clone)]
struct TimedPass {
    inner: Box<dyn TypedPass>,
    key: String,
    counters: Arc<Mutex<BTreeMap<String, Counters>>>,
}

impl fmt::Debug for TimedPass {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.inner.fmt(f)
    }
}

impl TypedPass for TimedPass {
    fn reset(&mut self) -> TractResult<()> {
        let started = Instant::now();
        let result = self.inner.reset();
        let ns = started.elapsed().as_nanos();
        let mut counters = self.counters.lock().unwrap();
        let row = counters.entry(self.key.clone()).or_default();
        row.reset_calls += 1;
        row.reset_ns += ns;
        result
    }

    fn next(
        &mut self,
        session: &mut OptimizerSession,
        model: &TypedModel,
    ) -> TractResult<Option<TypedModelPatch>> {
        let started = Instant::now();
        let result = self.inner.next(session, model);
        let ns = started.elapsed().as_nanos();
        let mut counters = self.counters.lock().unwrap();
        let row = counters.entry(self.key.clone()).or_default();
        row.next_calls += 1;
        row.next_ns += ns;
        row.patches += u64::from(matches!(&result, Ok(Some(_))));
        result
    }

    fn run_direct(&mut self, model: &mut TypedModel) -> TractResult<bool> {
        let started = Instant::now();
        let result = self.inner.run_direct(model);
        let ns = started.elapsed().as_nanos();
        let mut counters = self.counters.lock().unwrap();
        let row = counters.entry(self.key.clone()).or_default();
        row.direct_calls += 1;
        row.direct_ns += ns;
        row.direct_changes += u64::from(matches!(&result, Ok(true)));
        result
    }
}

pub fn optimize(model: &mut TypedModel) -> TractResult<Value> {
    let counters = Arc::new(Mutex::new(BTreeMap::<String, Counters>::new()));
    let mut optimizer = Optimizer::codegen();
    optimizer.passes = optimizer
        .passes
        .into_iter()
        .enumerate()
        .map(|(i, inner)| {
            Box::new(TimedPass {
                key: format!("{i}:{inner:?}"),
                inner,
                counters: counters.clone(),
            }) as Box<dyn TypedPass>
        })
        .collect();
    let started = Instant::now();
    optimizer.optimize(model)?;
    let total_ns = started.elapsed().as_nanos();
    let counters = counters.lock().unwrap();
    let callback_ns: u128 = counters
        .values()
        .map(|r| r.reset_ns + r.next_ns + r.direct_ns)
        .sum();
    let rows: Vec<_> = counters
        .iter()
        .map(|(name, r)| {
            json!({"pass":name,
        "reset_calls":r.reset_calls,"next_calls":r.next_calls,"direct_calls":r.direct_calls,
        "patches_returned":r.patches,"direct_changes":r.direct_changes,
        "reset_ns":r.reset_ns,"next_ns":r.next_ns,"direct_ns":r.direct_ns,
        "callback_ns":r.reset_ns+r.next_ns+r.direct_ns})
        })
        .collect();
    Ok(json!({"total_ns":total_ns,"callback_ns":callback_ns,
        "driver_and_instrumentation_ns":total_ns-callback_ns,"passes":rows,
        "scope":"top-level callbacks; driver residual includes patch apply, compaction, checks and instrumentation"}))
}
