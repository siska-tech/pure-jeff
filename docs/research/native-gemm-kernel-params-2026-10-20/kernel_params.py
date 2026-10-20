"""gemm-common 0.19 `kernel_params` and the small-size branch of `gemm_basic_generic`, for an explicit
CACHE_INFO (F32, sizeof 4). Kernels: fma (MR 16, NR 6), neon (MR 16, NR 4); avx512f (MR 64, NR 6) only with the x86-v4 feature (off)."""
import math

KERNELS = {"fma": (16, 6), "avx512f": (64, 6), "neon": (16, 4)}


def div_ceil(a, b):
    return -(-a // b)


def next_pow2(x):
    return 1 if x <= 1 else 1 << (x - 1).bit_length()


def round_down(a, b):
    return a // b * b


def kernel_params(m, n, k, mr, nr, info, sizeof=4):
    (l1, l1a, l1l), (l2, l2a, _), (l3, l3a, _) = [(c["bytes"], c["associativity"], c["line_bytes"]) for c in info]
    l1 = max(l1, 32 * 1024)
    l1_line = max(l1l, 64)
    l1a, l2a, l3a = max(l1a, 2), max(l2a, 2), max(l3a, 2)
    n_sets = l1 // (l1_line * l1a)
    g = math.gcd(mr * sizeof, l1_line * n_sets)
    kc0 = (l1_line * n_sets) // g
    c_lhs = (mr * sizeof) // g
    c_rhs = (nr * kc0 * sizeof) // (l1_line * n_sets)
    mult = l1a // (c_lhs + c_rhs)
    auto_kc = min(max(kc0 * next_pow2(mult), 512), k)
    k_iter = div_ceil(k, auto_kc)
    kc = div_ceil(k, k_iter)
    if l2 == 0:
        raise ValueError("L2 = 0 panics in gemm")
    rhs_micro = nr * kc * sizeof
    rhs_l2a = div_ceil(rhs_micro, l2 // l2a)
    lhs_l2a = max(l2a - 1 - rhs_l2a, 1)
    mc = round_down((lhs_l2a * l2) // (l2a * sizeof * kc), mr)
    m_iter = div_ceil(m, mc) if mc else 1
    mc = div_ceil(m, m_iter * mr) * mr
    mc = min(mc, 8 * mr)
    if l3 == 0:
        nc = 0
    else:
        nc = round_down(((l3a - 1) * l3) // l3a // (sizeof * kc), nr)
        n_iter = div_ceil(n, nc)
        nc = div_ceil(n, n_iter * nr) * nr
    return {"kc": kc, "mc": mc, "nc": nc}


def params(m, n, k, kernel, info):
    """The blocking `gemm_basic_generic` uses for a multi-row product (m > 1)."""
    mr, nr = KERNELS[kernel]
    if m <= 64 and n <= 64:
        kc = min(k, 512)
        mc = (info[1]["bytes"] // 4 // kc) // mr * mr
        return {"kc": kc, "mc": mc, "nc": div_ceil(n, nr) * nr, "path": "small"}
    return kernel_params(m, n, k, mr, nr, info) | {"path": "kernel_params"}


def k_chunks(k, kc):
    return [min(kc, k - s) for s in range(0, k, kc)]
