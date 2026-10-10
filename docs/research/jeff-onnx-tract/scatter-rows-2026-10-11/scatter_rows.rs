//! Copy contiguous ScatterElements rows when each row has one valid target.
//! Declines before mutation for unsupported shapes, layouts or indices.
pub fn copy<T: Clone>(
    data: &mut [T],
    data_shape: &[usize],
    indices: &[i64],
    updates: &[T],
    update_shape: &[usize],
    axis: usize,
) -> bool {
    if axis >= data_shape.len()
        || data_shape.len() != update_shape.len()
        || data_shape
            .iter()
            .zip(update_shape)
            .enumerate()
            .any(|(i, (d, u))| i != axis && d != u)
    {
        return false;
    }
    let volume = |shape: &[usize]| shape.iter().try_fold(1_usize, |v, d| v.checked_mul(*d));
    if volume(data_shape) != Some(data.len())
        || volume(update_shape) != Some(updates.len())
        || indices.len() != updates.len()
    {
        return false;
    }
    if updates.is_empty() {
        return true;
    }
    let Ok(extent) = i64::try_from(data_shape[axis]) else {
        return false;
    };
    let Some(inner) = volume(&data_shape[axis + 1..]) else {
        return false;
    };
    if extent == 0 || inner == 0 {
        return false;
    }
    for row in indices.chunks_exact(inner) {
        let index = row[0];
        if index < -extent || index >= extent || row.iter().any(|v| *v != index) {
            return false;
        }
    }
    for (row, values) in updates.chunks_exact(inner).enumerate() {
        let index = indices[row * inner];
        let target = if index < 0 { index + extent } else { index } as usize;
        let outer = row / update_shape[axis];
        let offset = (outer * data_shape[axis] + target) * inner;
        data[offset..offset + inner].clone_from_slice(values);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::copy;

    #[test]
    fn rectangular_negative_and_duplicate_targets() {
        for outer in 1..=4 {
            for extent in 1..=8 {
                for count in 0..=10 {
                    for inner in 1..=9 {
                        for negative in [false, true] {
                            let shape = [outer, extent, inner];
                            let updates_shape = [outer, count, inner];
                            let updates: Vec<i32> =
                                (0..outer * count * inner).map(|i| i as i32 + 7).collect();
                            let indices: Vec<i64> = (0..outer * count * inner)
                                .map(|i| {
                                    let target = (i / inner) % extent;
                                    target as i64 - if negative { extent as i64 } else { 0 }
                                })
                                .collect();
                            let mut actual = vec![-1; outer * extent * inner];
                            let mut expected = actual.clone();
                            for (i, value) in updates.iter().enumerate() {
                                let target = if indices[i] < 0 {
                                    indices[i] + extent as i64
                                } else {
                                    indices[i]
                                } as usize;
                                expected[((i / (count * inner)) * extent + target) * inner
                                    + i % inner] = *value;
                            }
                            assert!(copy(
                                &mut actual,
                                &shape,
                                &indices,
                                &updates,
                                &updates_shape,
                                1
                            ));
                            assert_eq!(actual, expected);
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn declines_before_mutation_and_preserves_bits() {
        for indices in [vec![0, 0, 1, 0], vec![0, 0, 2, 2], vec![0, 0, -3, -3]] {
            let mut actual = vec![5; 4];
            assert!(!copy(
                &mut actual,
                &[2, 2],
                &indices,
                &[1, 2, 3, 4],
                &[2, 2],
                0
            ));
            assert_eq!(actual, vec![5; 4]);
        }
        let mut bits = [0_f32; 4];
        let values = [f32::from_bits(0x7fc00123), -0.0];
        assert!(copy(&mut bits, &[2, 2], &[-1, -1], &values, &[1, 2], 0));
        assert_eq!(bits.map(f32::to_bits), [0, 0, 0x7fc00123, 0x80000000]);
        assert!(!copy(&mut [0; 4], &[2, 2], &[0], &[1], &[1, 1], 0));
        assert!(!copy(&mut [0; 4], &[2, 2], &[], &[], &[0, 2], 2));
        assert!(copy::<i32>(&mut [], &[0, 2], &[], &[], &[0, 2], 0));
        let mut strings = vec!["old".to_string(); 2];
        assert!(copy(
            &mut strings,
            &[2],
            &[0, 0],
            &["a".to_string(), "b".to_string()],
            &[2],
            0
        ));
        assert_eq!(strings, ["b", "old"]);
    }
}
