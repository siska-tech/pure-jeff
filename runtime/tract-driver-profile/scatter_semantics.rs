//! Direct ScatterElements checks linked to the actual isolated operator.
use tract_onnx::tract_core::{
    internal::*,
    ops::array::{ScatterElements, ScatterReduction},
    plan::{EvalContext, Seating, SessionId},
};

fn evaluate(data: TValue, indices: Tensor, updates: Tensor) -> TractResult<TValue> {
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
    Ok(ScatterElements {
        axis: 0,
        reduction: ScatterReduction::None,
    }
    .eval(&context, tvec!(data, indices.into(), updates.into()))?
    .remove(0))
}

#[test]
fn shared_input_duplicate_order_and_bit_preservation() -> TractResult<()> {
    let data = Tensor::from_shape(&[2, 2], &[1_f32, 2., 3., 4.])?.into_tvalue();
    let shared = data.clone();
    let indices = Tensor::from_shape(&[2, 2], &[-1_i64, -1, 1, 1])?;
    let updates = Tensor::from_shape(&[2, 2], &[5_f32, 6., f32::from_bits(0x7fc00123), -0.0])?;
    let output = evaluate(data, indices, updates)?;
    ensure!(
        output
            .to_plain_array_view::<f32>()?
            .iter()
            .map(|v| v.to_bits())
            .collect::<Vec<_>>()
            == [1_f32.to_bits(), 2_f32.to_bits(), 0x7fc00123, 0x80000000]
    );
    ensure!(
        shared
            .to_plain_array_view::<f32>()?
            .iter()
            .copied()
            .collect::<Vec<_>>()
            == [1., 2., 3., 4.]
    );
    Ok(())
}

#[test]
fn empty_updates_and_invalid_index_fallback() -> TractResult<()> {
    let data = Tensor::from_shape(&[2, 2], &[1_i32, 2, 3, 4])?.into_tvalue();
    let output = evaluate(
        data,
        Tensor::from_shape(&[0, 2], &[] as &[i64])?,
        Tensor::from_shape(&[0, 2], &[] as &[i32])?,
    )?;
    ensure!(output.shape() == [2, 2]);
    ensure!(
        output
            .to_plain_array_view::<i32>()?
            .iter()
            .copied()
            .collect::<Vec<_>>()
            == [1, 2, 3, 4]
    );
    for index in [-3_i64, 2, i64::MIN, i64::MAX] {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            evaluate(
                Tensor::from_shape(&[2, 2], &[1_i32, 2, 3, 4])
                    .unwrap()
                    .into_tvalue(),
                Tensor::from_shape(&[1, 2], &[index, index]).unwrap(),
                Tensor::from_shape(&[1, 2], &[5_i32, 6]).unwrap(),
            )
        }));
        ensure!(result.is_err() || result.unwrap().is_err());
    }
    Ok(())
}
