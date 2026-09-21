"""PDF rendering (fpdf2) + object-store abstraction (MinIO real, dict fake for tests)."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol


def render_rx_pdf(
    consultation_id: str, doctor_id: str, diagnosis: str, medicines: list[str]
) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Amrutam Prescription", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Consultation: {consultation_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Doctor: {doctor_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Diagnosis: {diagnosis}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Medicines:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for m in medicines:
        pdf.cell(0, 7, f"- {m}", new_x="LMARGIN", new_y="NEXT")
    out = pdf.output()
    return bytes(out) if isinstance(out, bytearray) else out


class PdfStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def signed_url(self, key: str, ttl_s: int = 300) -> str: ...


class MemoryPdfStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def signed_url(self, key: str, ttl_s: int = 300) -> str:
        return f"memory://{key}?ttl={ttl_s}"


class MinioPdfStore:
    def __init__(self, endpoint: str, access: str, secret: str, bucket: str) -> None:
        from minio import Minio

        host = endpoint.replace("http://", "").replace("https://", "")
        secure = endpoint.startswith("https://")
        self._client = Minio(host, access_key=access, secret_key=secret, secure=secure)
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    async def put(self, key: str, data: bytes) -> None:
        import io

        self._client.put_object(self._bucket, key, io.BytesIO(data), len(data))

    async def signed_url(self, key: str, ttl_s: int = 300) -> str:
        return self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=ttl_s)
        )
