import torch
import time
def matmul_benchmark(device: torch.device, size: int = 2000, repeats: int = 3) -> float:
    """
    Perform a benchmark by creating random matrices on a given device,
    multiplying them several times, and measuring the average elapsed time.

    :param device: The torch device (cpu, cuda, or mps).
    :param size: Dimension of the square matrices (size x size).
    :param repeats: Number of times to repeat the multiplication for averaging.
    :return: Average time (in seconds) for the operation.
    """
    times = []
    for _ in range(repeats):
        # Create two large random matrices on the target device
        a = torch.randn((size, size), device=device)
        b = torch.randn((size, size), device=device)

        start = time.time()
        # Matrix multiply, then do some extra work (e.g., a trig function)
        c = torch.mm(a, b)
        c = torch.sin(c)  # Just a sample additional “fancy” operation

        # Synchronize so we measure real elapsed time on GPU/MPS
        if device.type == 'cuda':
            torch.cuda.synchronize()
        elif device.type == 'mps':
            torch.mps.synchronize()

        end = time.time()
        times.append(end - start)

    return sum(times) / len(times)


def robust_benchmark(device: torch.device, size: int = 2000, repeats: int = 3) -> float:
    """
    Perform a more comprehensive benchmark by creating random matrices/vectors
    on the given device, doing multiple Torch operations (matmul, element-wise
    sin/log, broadcasting, indexing, etc.), and measuring the average elapsed
    time over 'repeats' runs.

    :param device: Torch device (cpu, cuda, or mps).
    :param size: Base dimension for the tests operations.
    :param repeats: Number of times to repeat the entire operation.
    :return: Average time (in seconds) for the operation set.
    """
    times = []

    for _ in range(repeats):
        # Create some random tensors on the specified device
        a = torch.randn((size, size), device=device)
        b = torch.randn((size, size), device=device)

        # We also create a vector for broadcasting tests
        v = torch.randn((size,), device=device)

        start = time.time()

        # 1) Matrix multiplication
        c = torch.mm(a, b)

        # 2) Element-wise operations
        c = torch.sin(c)  # non-linear operation
        c = torch.log(torch.abs(c) + 1.0)  # another math transform

        # 3) Broadcasting + indexing
        d = c + v.unsqueeze(0)  # broadcast the vector across dim=0
        d[100:200, 50:100] = d[100:200, 50:100] * 2.0  # partial in-place modification

        # 4) A second matmul for variety
        e = torch.mm(d, b.t())

        # 5) Summation and mean to reduce the shape
        result = e.sum() / (size * size)

        # 6) Device synchronization for accurate timing
        if device.type == 'cuda':
            torch.cuda.synchronize()
        elif device.type == 'mps':
            torch.mps.synchronize()

        end = time.time()
        times.append(end - start)

    return sum(times) / len(times)


if __name__ == "__main__":
    # 1. CPU: Always benchmark CPU for reference
    cpu_device = torch.device("cpu")

    # Run both benchmarks on CPU
    cpu_mm_time = matmul_benchmark(cpu_device)
    cpu_rb_time = robust_benchmark(cpu_device)

    # Print CPU results
    print("\n===== CPU Benchmarks =====")
    print(f"[CPU - MatMul ] Average time: {cpu_mm_time:.4f} seconds")
    print(f"[CPU - Robust ] Average time: {cpu_rb_time:.4f} seconds")

    print("\n===== Hardware Accelerator Benchmarks =====")

    # 2. Check for MPS (Apple Silicon)
    if torch.backends.mps.is_available():
        print("\nUsing Metal Performance Shaders (MPS):\n")
        mps_device = torch.device("mps")

        mps_mm_time = matmul_benchmark(mps_device)
        speedup_mm_mps = cpu_mm_time / mps_mm_time

        mps_rb_time = robust_benchmark(mps_device)
        speedup_rb_mps = cpu_rb_time / mps_rb_time

        print(f"[MPS - MatMul ] Average time: {mps_mm_time:.4f} seconds "
              f"(~{speedup_mm_mps:.2f}x faster than CPU)")
        print(f"[MPS - Robust ] Average time: {mps_rb_time:.4f} seconds "
              f"(~{speedup_rb_mps:.2f}x faster than CPU)")

    # 3. Otherwise check for CUDA
    elif torch.cuda.is_available():
        print("\nUsing CUDA:\n")
        cuda_device = torch.device("cuda")

        cuda_mm_time = matmul_benchmark(cuda_device)
        speedup_mm_cuda = cpu_mm_time / cuda_mm_time

        cuda_rb_time = robust_benchmark(cuda_device)
        speedup_rb_cuda = cpu_rb_time / cuda_rb_time

        print(f"[CUDA - MatMul ] Average time: {cuda_mm_time:.4f} seconds "
              f"(~{speedup_mm_cuda:.2f}x faster than CPU)")
        print(f"[CUDA - Robust ] Average time: {cuda_rb_time:.4f} seconds "
              f"(~{speedup_rb_cuda:.2f}x faster than CPU)")

    else:
        print("\nNo MPS or CUDA found. CPU only.")

    print("\n===== End of Benchmarks =====\n")
