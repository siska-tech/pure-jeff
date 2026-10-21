//! Diagnostic (#18, PR #41): where the k chunks of `backbone::matmul` cost time, and which ways
//! of running the same chunks keep the bits. For each product of the forward that `matmul`
//! splits (k > 512, m > 1), with random inputs in the forward's layouts:
//!
//! - `plain`: one gemm call over all of k (main's path; gemm picks kc from CACHE_INFO).
//! - `chunks`: PR #41 as it is: one gemm call per chunk of at most 512, all threads in each.
//! - `columns`: the same chunks, but this program splits the output's columns among the threads
//!   once, and each thread runs every chunk for its columns with one thread in gemm.
//! - `rows`: as `columns`, splitting the output's rows (multiples of 16).
//! - `heads`: (attention value product only) the 8 heads among the threads, every chunk of a head
//!   on one thread.
//! - `rule1`, `rule2`: the candidate rule (`rule_blocks`), about 1 or 2 blocks per thread.
//!
//! Every variant except `plain` adds the same chunks in the same order into each output element;
//! only which thread computes which elements differs. The program checks that against `chunks`
//! bit for bit and reports it. It also times each chunk call of `chunks` (`first_call_s`,
//! `later_calls_s`) and a chunk call that writes instead of adding (`write_only_s`, bits not
//! compared) to separate the accumulation from the rest of a call.
//!
//!   gemm_chunk_profile <threads> <seq>... [--repeats N]
use anyhow::{ensure, Context, Result};
use rayon::prelude::*;
use serde_json::json;
use std::time::Instant;

const K_CHUNK: usize = 512;

fn uniform(seed: &mut u64, n: usize) -> Vec<f32> {
    (0..n)
        .map(|_| {
            *seed ^= *seed << 13;
            *seed ^= *seed >> 7;
            *seed ^= *seed << 17;
            ((*seed >> 40) as f32 / (1u64 << 24) as f32) * 2.0 - 1.0
        })
        .collect()
}

fn chunks(k: usize) -> Vec<(usize, usize)> {
    let chunk = k.div_ceil(k.div_ceil(K_CHUNK));
    (0..k)
        .step_by(chunk)
        .map(|s| (s, chunk.min(k - s)))
        .collect()
}

/// One operand: its elements and how gemm steps through them (column and row strides).
#[derive(Clone, Copy)]
struct Operand<'a> {
    data: &'a [f32],
    cs: usize,
    rs: usize,
}

/// A raw output pointer that threads write disjoint parts of.
#[derive(Clone, Copy)]
struct Out(*mut f32);
unsafe impl Send for Out {}
unsafe impl Sync for Out {}

impl Out {
    /// The pointer `offset` elements further (a method, so closures capture the whole `Out`).
    unsafe fn add(self, offset: usize) -> Out {
        Out(self.0.add(offset))
    }
}

/// dst[i * dst_rs + j] for i < m, j < n gets the product of lhs rows `row0..row0 + m` and rhs
/// columns `col0..col0 + n` over every chunk of k, in order: the first chunk written, the others
/// added (or, with `write_only`, every chunk written: a timing probe whose bits are not used).
///
/// SAFETY: the caller guarantees that the m x n block at `dst` (row stride dst_rs) is valid and
/// written by no one else meanwhile, and that the rows, columns and k range stay inside lhs and
/// rhs (checked with asserts here for the operands).
#[allow(clippy::too_many_arguments)]
unsafe fn run_chunks(
    dst: Out,
    dst_rs: usize,
    lhs: Operand,
    rhs: Operand,
    (row0, m): (usize, usize),
    (col0, n): (usize, usize),
    k: usize,
    parallelism: gemm::Parallelism,
    write_only: bool,
    mut each_call: impl FnMut(f64),
) {
    assert!(m > 0 && n > 0);
    assert!((row0 + m - 1) * lhs.rs + (k - 1) * lhs.cs < lhs.data.len());
    assert!((k - 1) * rhs.rs + (col0 + n - 1) * rhs.cs < rhs.data.len());
    for (start, size) in chunks(k) {
        let accumulate = start > 0 && !write_only;
        let t = Instant::now();
        gemm::gemm(
            m,
            n,
            size,
            dst.0,
            1,
            dst_rs as isize,
            accumulate,
            lhs.data.as_ptr().add(row0 * lhs.rs + start * lhs.cs),
            lhs.cs as isize,
            lhs.rs as isize,
            rhs.data.as_ptr().add(start * rhs.rs + col0 * rhs.cs),
            rhs.cs as isize,
            rhs.rs as isize,
            if accumulate { 1.0 } else { 0.0 },
            1.0,
            false,
            false,
            false,
            parallelism,
        );
        each_call(t.elapsed().as_secs_f64());
    }
}

/// Splits `len` into at most `parts` blocks of whole `unit`s.
fn blocks(len: usize, parts: usize, unit: usize) -> Vec<(usize, usize)> {
    let units = len.div_ceil(unit);
    let per = units.div_ceil(parts.max(1)).max(1) * unit;
    (0..len)
        .step_by(per)
        .map(|s| (s, per.min(len - s)))
        .collect()
}

/// The candidate rule: the output of each of `batch` products split along its larger dimension
/// into about `per_thread` x threads blocks in all (whole 16s, at least 64 long), every block run
/// on one thread with all its chunks. None (the caller keeps gemm's own threads) when that gives
/// fewer than two blocks or a block gemm would compute on another path: m x n <= 256 (its
/// horizontal kernels) or a side of 1 (gemv).
fn rule_blocks(
    batch: usize,
    m: usize,
    n: usize,
    threads: usize,
    per_thread: usize,
) -> Option<Vec<(usize, (usize, usize), (usize, usize))>> {
    if threads <= 1 {
        return None;
    }
    let along_rows = m >= n;
    let len = if along_rows { m } else { n };
    let parts = (threads * per_thread).div_ceil(batch).min(len / 64).max(1);
    let split = blocks(len, parts, 16);
    let tasks: Vec<_> = (0..batch)
        .flat_map(|b| {
            split.iter().map(move |&s| {
                if along_rows {
                    (b, s, (0, n))
                } else {
                    (b, (0, m), s)
                }
            })
        })
        .collect();
    let safe = tasks
        .iter()
        .all(|&(_, (_, rows), (_, cols))| rows >= 2 && cols >= 2 && rows * cols > 256);
    (tasks.len() >= 2 && safe).then_some(tasks)
}

fn median(mut v: Vec<f64>) -> f64 {
    v.sort_by(f64::total_cmp);
    v[v.len() / 2]
}

fn bits(v: &[f32]) -> Vec<u32> {
    v.iter().map(|x| x.to_bits()).collect()
}

/// One product of the forward: `count` per forward, `batch` independent (m, k) x (k, n) parts.
struct Shape {
    name: &'static str,
    count: usize,
    batch: usize,
    m: usize,
    n: usize,
    k: usize,
    /// rhs is the transposed weight (k, n) of `linear` (strides 1, k), else row-major (k, n).
    weight: bool,
}

fn shapes(seq: usize) -> Vec<Shape> {
    let linear = |name, count, n, k| Shape {
        name,
        count,
        batch: 1,
        m: seq,
        n,
        k,
        weight: true,
    };
    let mut out = vec![
        linear("in_proj_qkv", 18, 6144, 1024),
        linear("in_proj_z", 18, 2048, 1024),
        linear("in_proj_b/a", 36, 16, 1024),
        linear("out_proj", 18, 1024, 2048),
        linear("mlp_gate/up", 48, 3584, 1024),
        linear("mlp_down", 24, 1024, 3584),
        linear("attn_q", 6, 4096, 1024),
        linear("attn_k/v", 12, 512, 1024),
        linear("attn_o", 6, 1024, 2048),
    ];
    if seq > K_CHUNK {
        // The value product of each query block of 512 rows (the last block may be shorter).
        let blocks = seq.div_ceil(512);
        out.push(Shape {
            name: "attn_value",
            count: 6 * blocks,
            batch: 8,
            m: 512.min(seq),
            n: 256,
            k: seq,
            weight: false,
        });
    }
    out
}

fn main() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let repeats = match args.iter().position(|a| a == "--repeats") {
        Some(i) => {
            let r = args.remove(i + 1).parse()?;
            args.remove(i);
            r
        }
        None => 5,
    };
    let threads: usize = args.first().context("threads")?.parse()?;
    let seqs: Vec<usize> = args[1..]
        .iter()
        .map(|s| s.parse())
        .collect::<Result<_, _>>()?;
    ensure!(
        !seqs.is_empty(),
        "usage: gemm_chunk_profile <threads> <seq>..."
    );
    pure_jeff::configure_threads(threads)?;
    ensure!(rayon::current_num_threads() == threads, "rayon pool size");
    let par = if threads > 1 {
        gemm::Parallelism::Rayon(threads)
    } else {
        gemm::Parallelism::None
    };
    let mut seed = 0x9f0f_11e5_u64;
    for seq in seqs {
        for s in shapes(seq) {
            let (m, n, k, batch) = (s.m, s.n, s.k, s.batch);
            let lhs_v = uniform(&mut seed, batch * m * k);
            let rhs_v = uniform(&mut seed, batch * k * n);
            // lhs row-major (m, k) per batch; rhs as the forward has it.
            let lhs = |b: usize| Operand {
                data: &lhs_v[b * m * k..][..m * k],
                cs: 1,
                rs: k,
            };
            let rhs = |b: usize| {
                let data = &rhs_v[b * k * n..][..k * n];
                if s.weight {
                    Operand { data, cs: k, rs: 1 }
                } else {
                    Operand { data, cs: 1, rs: n }
                }
            };
            let run = |variant: &str, first: &mut Vec<f64>, later: &mut Vec<f64>| -> Vec<f32> {
                let mut dst = vec![0f32; batch * m * n];
                let out = Out(dst.as_mut_ptr());
                // SAFETY (all variants): each task writes its own rows or columns of one batch
                // element's m x n block of dst, which outlives the calls; the operand ranges
                // are asserted in run_chunks.
                unsafe {
                    match variant {
                        "plain" => (0..batch).for_each(|b| {
                            gemm::gemm(
                                m,
                                n,
                                k,
                                out.add(b * m * n).0,
                                1,
                                n as isize,
                                false,
                                lhs(b).data.as_ptr(),
                                1,
                                k as isize,
                                rhs(b).data.as_ptr(),
                                rhs(b).cs as isize,
                                rhs(b).rs as isize,
                                0.0,
                                1.0,
                                false,
                                false,
                                false,
                                par,
                            )
                        }),
                        "chunks" | "write_only" => (0..batch).for_each(|b| {
                            let mut i = 0;
                            run_chunks(
                                out.add(b * m * n),
                                n,
                                lhs(b),
                                rhs(b),
                                (0, m),
                                (0, n),
                                k,
                                par,
                                variant == "write_only",
                                |t| {
                                    if i == 0 {
                                        first.push(t)
                                    } else {
                                        later.push(t)
                                    }
                                    i += 1;
                                },
                            )
                        }),
                        "columns" => {
                            let tasks: Vec<(usize, (usize, usize))> = (0..batch)
                                .flat_map(|b| {
                                    blocks(n, threads, 16).into_iter().map(move |c| (b, c))
                                })
                                .collect();
                            tasks.into_par_iter().for_each(|(b, cols)| {
                                run_chunks(
                                    out.add(b * m * n + cols.0),
                                    n,
                                    lhs(b),
                                    rhs(b),
                                    (0, m),
                                    (cols.0, cols.1),
                                    k,
                                    gemm::Parallelism::None,
                                    false,
                                    |_| {},
                                )
                            })
                        }
                        "rows" => {
                            let tasks: Vec<(usize, (usize, usize))> = (0..batch)
                                .flat_map(|b| {
                                    blocks(m, threads, 16).into_iter().map(move |r| (b, r))
                                })
                                .collect();
                            tasks.into_par_iter().for_each(|(b, rows)| {
                                run_chunks(
                                    out.add(b * m * n + rows.0 * n),
                                    n,
                                    lhs(b),
                                    rhs(b),
                                    (rows.0, rows.1),
                                    (0, n),
                                    k,
                                    gemm::Parallelism::None,
                                    false,
                                    |_| {},
                                )
                            })
                        }
                        "heads" => (0..batch).into_par_iter().for_each(|b| {
                            run_chunks(
                                out.add(b * m * n),
                                n,
                                lhs(b),
                                rhs(b),
                                (0, m),
                                (0, n),
                                k,
                                gemm::Parallelism::None,
                                false,
                                |_| {},
                            )
                        }),
                        "rule1" | "rule2" => {
                            let per = if variant == "rule1" { 1 } else { 2 };
                            match rule_blocks(batch, m, n, threads, per) {
                                Some(tasks) => tasks.into_par_iter().for_each(|(b, rows, cols)| {
                                    run_chunks(
                                        out.add(b * m * n + rows.0 * n + cols.0),
                                        n,
                                        lhs(b),
                                        rhs(b),
                                        rows,
                                        cols,
                                        k,
                                        gemm::Parallelism::None,
                                        false,
                                        |_| {},
                                    )
                                }),
                                None => (0..batch).for_each(|b| {
                                    run_chunks(
                                        out.add(b * m * n),
                                        n,
                                        lhs(b),
                                        rhs(b),
                                        (0, m),
                                        (0, n),
                                        k,
                                        par,
                                        false,
                                        |_| {},
                                    )
                                }),
                            }
                        }
                        _ => unreachable!(),
                    }
                }
                dst
            };
            let mut variants = vec![
                "plain",
                "chunks",
                "write_only",
                "columns",
                "rows",
                "rule1",
                "rule2",
            ];
            if batch > 1 {
                variants.push("heads");
            }
            let mut reference: Option<Vec<u32>> = None;
            let mut times: Vec<(&str, Vec<f64>, Option<bool>)> =
                variants.iter().map(|v| (*v, Vec::new(), None)).collect();
            let (mut first, mut later) = (Vec::new(), Vec::new());
            for rep in 0..repeats + 1 {
                // Rotate the order each repeat; repeat 0 is a warm-up and not timed.
                for i in 0..variants.len() {
                    let at = (i + rep) % variants.len();
                    let variant = variants[at];
                    let (mut f, mut l) = (Vec::new(), Vec::new());
                    let t = Instant::now();
                    let out = run(variant, &mut f, &mut l);
                    let elapsed = t.elapsed().as_secs_f64();
                    if rep > 0 {
                        times[at].1.push(elapsed);
                        if variant == "chunks" {
                            first.push(f.iter().sum::<f64>());
                            later.push(l.iter().sum::<f64>());
                        }
                    }
                    if variant == "chunks" && reference.is_none() {
                        reference = Some(bits(&out));
                    }
                    if !matches!(variant, "plain" | "write_only") {
                        let equal = reference.as_ref().map(|r| *r == bits(&out));
                        if let Some(eq) = equal {
                            times[at].2 = Some(times[at].2.unwrap_or(true) && eq);
                        }
                    }
                }
            }
            let row: serde_json::Map<_, _> = times
                .iter()
                .map(|(v, t, eq)| {
                    (
                        (*v).to_owned(),
                        json!({"median_s": median(t.clone()), "bitwise_equal_to_chunks": eq}),
                    )
                })
                .collect();
            println!(
                "{}",
                json!({"threads": threads, "seq": seq, "name": s.name, "count": s.count,
                    "batch": batch, "m": m, "n": n, "k": k, "chunks": chunks(k).len(),
                    "first_call_s": median(first), "later_calls_s": median(later),
                    "variants": row})
            );
        }
    }
    Ok(())
}
