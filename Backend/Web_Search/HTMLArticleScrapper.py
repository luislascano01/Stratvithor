import re
import time
import logging
from typing import List
import torch
from bs4 import BeautifulSoup, Tag
from sentence_transformers import SentenceTransformer

class HTMLArticleScrapper:
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.device = self._select_device()
        self.model = SentenceTransformer(model_name).to(self.device)

    def _select_device(self) -> torch.device:
        if torch.backends.mps.is_available():
            return torch.device("mps")
        elif torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def extract_main_article(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        self._remove_boilerplate(soup)
        paragraphs = self._extract_text_blocks(soup)
        if not paragraphs:
            print("[INFO] No paragraphs found, trying alternative extraction.")
            paragraphs = self._extract_alternative_text_blocks(soup)
        main_article = self._extract_main_article_from_blocks(paragraphs)
        return main_article

    def _remove_boilerplate(self, soup: BeautifulSoup):
        for tag_name in ["nav", "footer", "aside", "script", "style"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

    def _extract_text_blocks(self, soup: BeautifulSoup, min_length=50) -> List[str]:
        blocks = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) >= min_length]
        if len(blocks) < 5:  # If not enough paragraphs, try less strict criteria
            for div in soup.find_all("div"):
                text = div.get_text(separator=" ", strip=True)
                if len(text) >= 100:  # Increased minimum length for broader capture
                    blocks.append(text)
        return blocks

    def _extract_alternative_text_blocks(self, soup: BeautifulSoup) -> List[str]:
        texts = []
        if not texts:  # Simplified check
            texts.append(soup.get_text(separator=" ", strip=True))
        return texts

    def _extract_main_article_from_blocks(self, paragraphs: List[str]) -> str:
        paragraph_embeddings = self.model.encode(paragraphs, convert_to_tensor=True, device=self.device)
        scores = [0.5 for _ in paragraphs]  # Simplified scoring: assume all paragraphs are equally relevant
        top_paragraphs = [p for p, score in zip(paragraphs, scores) if score > 0.3][:5]
        return "\n\n".join(top_paragraphs)



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
    :param size: Base dimension for the test operations.
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
        c = torch.sin(c)   # non-linear operation
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