import requests
from HTMLArticleScrapper import HTMLArticleScrapper, matmul_benchmark, robust_benchmark
import torch

def test_html_article_scrapper(url: str):
    """
    1. Downloads the webpage.
    2. Extracts the main article text via HTMLArticleScrapper.
    3. Prints a snippet of the extracted text.
    """
    response = requests.get(url)
    response.raise_for_status()  # Raises an exception if the request failed

    html_content = response.text

    scrapper = HTMLArticleScrapper()
    main_article = scrapper.extract_main_article(html_content)

    print("\n===== Main Article Extracted =====")
    # Print up to 1000 characters, for brevity
    snippet = main_article[:1000].replace('\n', ' ')
    print(f"Extracted article snippet (first 1000 chars):\n{snippet}...")
    print("===================================\n")

def test_benchmarks():
    """
    Runs the matmul_benchmark and robust_benchmark on CPU and whichever accelerator is available,
    mirroring the logic in your main method.
    """
    cpu_device = torch.device("cpu")

    # CPU Benchmarks
    cpu_mm_time = matmul_benchmark(cpu_device)
    cpu_rb_time = robust_benchmark(cpu_device)

    print("\n===== CPU Benchmarks =====")
    print(f"[CPU - MatMul ] Average time: {cpu_mm_time:.4f} seconds")
    print(f"[CPU - Robust ] Average time: {cpu_rb_time:.4f} seconds")

    print("\n===== Hardware Accelerator Benchmarks =====")

    # Check MPS
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

    # Otherwise, check CUDA
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


if __name__ == "__main__":
    # 1) Test the HTMLArticleScrapper with a real webpage (example: Wikipedia)
    test_url = "https://www.bancsabadell.com/bsnacional/es/blog/como-hacer-tu-primera-factura-como-autonomo/"
    test_html_article_scrapper(test_url)
