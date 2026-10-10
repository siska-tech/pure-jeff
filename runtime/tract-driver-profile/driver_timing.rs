//! Diagnostic-only nested region timers; no operation or optimizer changes.
use std::{cell::RefCell, collections::BTreeMap, time::Instant};

#[derive(Default)]
struct State {
    enabled: bool,
    stack: Vec<Frame>,
    rows: BTreeMap<&'static str, (u64, u128, u128)>,
}
struct Frame {
    name: &'static str,
    started: Instant,
    child_ns: u128,
}
thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

pub fn begin(enabled: bool) {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        assert!(s.stack.is_empty());
        *s = State { enabled, ..State::default() };
    });
}

pub fn finish() -> BTreeMap<&'static str, (u64, u128, u128)> {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        assert!(s.stack.is_empty());
        s.enabled = false;
        std::mem::take(&mut s.rows)
    })
}

pub struct Span(bool);
impl Span {
    pub fn new(name: &'static str) -> Self {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            if s.enabled {
                s.stack.push(Frame { name, started: Instant::now(), child_ns: 0 });
            }
            Self(s.enabled)
        })
    }
}
impl Drop for Span {
    fn drop(&mut self) {
        if !self.0 { return; }
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let frame = s.stack.pop().expect("balanced diagnostic spans");
            let inclusive = frame.started.elapsed().as_nanos();
            let row = s.rows.entry(frame.name).or_default();
            row.0 += 1;
            row.1 += inclusive;
            row.2 += inclusive-frame.child_ns;
            if let Some(parent) = s.stack.last_mut() { parent.child_ns += inclusive; }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn nested_spans_and_disabled_mode() {
        begin(true);
        {
            let _outer = Span::new("outer");
            { let _inner = Span::new("inner"); }
        }
        let rows = finish();
        assert_eq!(rows["outer"].0, 1);
        assert_eq!(rows["inner"].0, 1);
        assert_eq!(rows["outer"].1, rows["outer"].2+rows["inner"].1);
        begin(false);
        { let _span = Span::new("disabled"); }
        assert!(finish().is_empty());
    }
}
