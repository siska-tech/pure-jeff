//! Contiguous Trilu candidate. Return false before mutation if the legacy i64
//! row+k calculation could overflow; the caller retains its existing fallback.
pub fn fill<T: Default + Clone>(
    data: &mut [T],
    rows: usize,
    cols: usize,
    upper: bool,
    k: i64,
) -> bool {
    if rows == 0 || cols == 0 {
        return data.is_empty();
    }
    let Some(matrix) = rows.checked_mul(cols) else {
        return false;
    };
    let Ok(last_row) = i64::try_from(rows - 1) else {
        return false;
    };
    if !data.len().is_multiple_of(matrix) || last_row.checked_add(k).is_none() {
        return false;
    }
    for (index, row) in data.chunks_exact_mut(cols).enumerate() {
        let diagonal = (index % rows) as i128 + k as i128;
        let boundary = (diagonal + i128::from(!upper)).clamp(0, cols as i128) as usize;
        if upper {
            row[..boundary].fill(T::default());
        } else {
            row[boundary..].fill(T::default());
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::fill;

    #[test]
    fn exhaustive_rectangular_batched_boundaries() {
        for rows in 0..10 {
            for cols in 0..10 {
                for batches in 0..4 {
                    for k in -20..=20 {
                        for upper in [false, true] {
                            let mut actual: Vec<i64> =
                                (1..=rows * cols * batches).map(|v| v as i64).collect();
                            let mut expected = actual.clone();
                            for (ix, value) in expected.iter_mut().enumerate() {
                                let row = (ix / cols) % rows;
                                let col = ix % cols;
                                let diagonal = row as i128 + k as i128;
                                if (upper && (col as i128) < diagonal)
                                    || (!upper && (col as i128) > diagonal)
                                {
                                    *value = 0;
                                }
                            }
                            assert!(fill(&mut actual, rows, cols, upper, k));
                            assert_eq!(actual, expected);
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn extreme_k_fallback_and_bit_preservation() {
        let mut data = vec![1_i32; 6];
        assert!(!fill(&mut data, 2, 3, true, i64::MAX));
        assert_eq!(data, vec![1; 6]);
        assert!(fill(&mut data, 2, 3, false, i64::MIN));
        assert_eq!(data, vec![0; 6]);
        assert!(!fill(&mut [1; 5], 2, 3, false, 0));
        let mut bits = [f32::from_bits(0x7fc00123), -0.0, f32::INFINITY, -4.];
        assert!(fill(&mut bits, 2, 2, false, 0));
        assert_eq!(
            bits.map(f32::to_bits),
            [0x7fc00123, 0, 0x7f800000, (-4_f32).to_bits()]
        );
        let mut strings = vec!["x".to_string(); 4];
        assert!(fill(&mut strings, 2, 2, true, 0));
        assert_eq!(strings, ["x", "x", "", "x"]);
    }
}
