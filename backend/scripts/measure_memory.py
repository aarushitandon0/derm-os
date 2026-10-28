"""Peak memory of the API process for one capture crop, with the real face detector.

    python scripts/measure_memory.py            # synthetic 12 MP phone-sized JPEG, no face photo

No network (the face model must already be downloaded), no YouCam call, no real photo: the
input is a generated gradient. The detector finds no face in it, so the crop step is run with a
centred stand-in box to measure the crop and scale as well. Prints the process's peak resident
memory (Linux VmHWM, Windows peak working set) after importing the app, after the detector
loads, and after one full crop.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def peak_mb() -> float:
    if sys.platform.startswith("linux"):
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / 2**20
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def phone_jpeg(w=3024, h=4032) -> bytes:
    from PIL import Image
    g = Image.linear_gradient("L").resize((w, h))
    im = Image.merge("RGB", (g, g.transpose(Image.Transpose.ROTATE_180), Image.new("L", (w, h), 140)))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue()


def main() -> int:
    import app.main  # noqa: F401  (the whole API, as uvicorn loads it)
    from app import facecrop as F
    print(f"after importing the app:        {peak_mb():7.1f} MB")
    det = F.get_detector()
    print(f"after loading the face model:   {peak_mb():7.1f} MB")
    data = phone_jpeg()
    img, notes = F.open_upright(data)
    faces = det(img)
    w, h = img.size
    box = faces[0] if len(faces) == 1 else F.Box(w * 0.3, h * 0.3, w * 0.4, w * 0.44)
    n = F.normalise(img, [box], "sd", notes=notes)
    n.png_bytes()
    print(f"after one 12 MP crop (SD):      {peak_mb():7.1f} MB peak  ({len(faces)} face(s) detected in the synthetic image)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
