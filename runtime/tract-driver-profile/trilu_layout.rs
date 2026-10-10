//! Direct operator tests linked to the isolated candidate rlib, outside its tree.
use tract_onnx::tract_core::{
    internal::*,
    ops::array::Trilu,
    plan::{EvalContext, Seating, SessionId},
};

fn evaluate(input: TValue, upper: bool, k: i64) -> TractResult<TValue> {
    let symbols = SymbolValues::default();
    let seating = Seating::single();
    let context = EvalContext {
        session: SessionId::NONE,
        node_id: 0,
        symbols: &symbols,
        scenario: None,
        shared: None,
        seating: &seating,
    };
    Ok(Trilu { upper }
        .eval(&context, tvec!(input, tensor0(k).into()))?
        .remove(0))
}

#[test]
fn shared_input_remains_unchanged() -> TractResult<()> {
    for upper in [false, true] {
        for k in [i64::MIN, -1, 0, 1, i64::MAX] {
            let input = Tensor::from_shape(&[2, 3], &[1_i32, 2, 3, 4, 5, 6])?.into_tvalue();
            let shared = input.clone();
            let mut expected = vec![1, 2, 3, 4, 5, 6];
            for (index, value) in expected.iter_mut().enumerate() {
                let diagonal = (index as i64 / 3).wrapping_add(k);
                let col = index as i64 % 3;
                if (upper && col < diagonal) || (!upper && col > diagonal) {
                    *value = 0;
                }
            }
            let output = evaluate(input, upper, k)?;
            ensure!(
                output
                    .to_plain_array_view::<i32>()?
                    .iter()
                    .copied()
                    .collect::<Vec<_>>()
                    == expected
            );
            ensure!(
                shared
                    .to_plain_array_view::<i32>()?
                    .iter()
                    .copied()
                    .collect::<Vec<_>>()
                    == [1, 2, 3, 4, 5, 6]
            );
        }
    }
    Ok(())
}

#[test]
fn empty_dimensions_remain_empty() -> TractResult<()> {
    for shape in [&[0, 5][..], &[5, 0], &[0, 0], &[2, 0, 5]] {
        for upper in [false, true] {
            let input = Tensor::from_shape(shape, &[] as &[f32])?;
            let output = evaluate(input.into_tvalue(), upper, 0)?;
            ensure!(output.shape() == shape && output.len() == 0);
        }
    }
    Ok(())
}
