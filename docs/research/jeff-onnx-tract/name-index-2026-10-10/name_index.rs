//! Experimental suffix selection; preserve the pinned Graph::unique_name rules.
use std::{borrow::Cow, collections::HashSet};

pub fn unique_name<'a, 'n>(
    names: impl Iterator<Item = &'a str> + Clone,
    prefix: Cow<'n, str>,
) -> Cow<'n, str> {
    if names.clone().all(|name| name != prefix.as_ref()) {
        return prefix;
    }
    let occupied: HashSet<usize> = names
        .filter_map(|name| {
            let suffix = name.strip_prefix(prefix.as_ref())?.strip_prefix('.')?;
            // The old formatter emits positive decimal integers without leading zeroes.
            if !matches!(suffix.as_bytes().first(), Some(b'1'..=b'9')) {
                return None;
            }
            suffix.parse().ok()
        })
        .collect();
    let suffix = (1..).find(|i| !occupied.contains(i)).unwrap();
    Cow::Owned(format!("{prefix}.{suffix}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reference(names: &[&str], prefix: &str) -> String {
        if names.iter().all(|name| *name != prefix) {
            return prefix.into();
        }
        for i in 1.. {
            let name = format!("{prefix}.{i}");
            if names.iter().all(|n| *n != name) {
                return name;
            }
        }
        unreachable!()
    }

    #[test]
    fn exhaustive_names_and_order() {
        let universe = [
            "a",
            "a.1",
            "a.2",
            "a.4",
            "a.01",
            "a.+1",
            "a.0",
            "a.18446744073709551616",
            "a#x",
            "",
            ".1",
            "日本",
            "日本.1",
        ];
        for mask in 0..(1 << universe.len()) {
            let mut names: Vec<_> = universe
                .iter()
                .enumerate()
                .filter_map(|(i, name)| ((mask & (1 << i)) != 0).then_some(*name))
                .collect();
            for _ in 0..2 {
                for prefix in ["a", "", "日本", "a.1", "a#x", "absent"] {
                    assert_eq!(
                        unique_name(names.iter().copied(), prefix.into()),
                        reference(&names, prefix)
                    );
                }
                names.reverse();
            }
        }
        assert_eq!(
            unique_name(["a", "a", "a.1", "a.1"].into_iter(), "a".into()),
            "a.2"
        );
    }
}
