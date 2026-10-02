"""Import statistics and drop-reason tracking for Takeout ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DropRecord:
    source_file: str
    reason: str
    detail: str = ""


@dataclass
class FileReport:
    path: str
    records_seen: int = 0
    records_imported: int = 0
    drops: List[DropRecord] = field(default_factory=list)
    parse_error: str = ""


@dataclass
class ImportReport:
    """Full audit trail for a single Takeout import run."""

    source: str = ""
    zip_total_entries: int = 0
    json_files_matched: int = 0
    json_files_parsed: int = 0
    json_files_failed: int = 0
    csv_files_matched: int = 0
    csv_files_parsed: int = 0
    non_json_skipped: int = 0
    files: List[FileReport] = field(default_factory=list)
    total_raw_records: int = 0
    total_imported: int = 0
    drops_by_reason: Dict[str, int] = field(default_factory=dict)

    def record_drop(self, source_file: str, reason: str, detail: str = "") -> None:
        self.drops_by_reason[reason] = self.drops_by_reason.get(reason, 0) + 1
        for fr in self.files:
            if fr.path == source_file:
                fr.drops.append(DropRecord(source_file=source_file, reason=reason, detail=detail))
                return
        self.files.append(
            FileReport(
                path=source_file,
                drops=[DropRecord(source_file=source_file, reason=reason, detail=detail)],
            )
        )

    def get_or_create_file(self, path: str) -> FileReport:
        for fr in self.files:
            if fr.path == path:
                return fr
        fr = FileReport(path=path)
        self.files.append(fr)
        return fr

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "zip_total_entries": self.zip_total_entries,
            "json_files_matched": self.json_files_matched,
            "json_files_parsed": self.json_files_parsed,
            "json_files_failed": self.json_files_failed,
            "csv_files_matched": self.csv_files_matched,
            "csv_files_parsed": self.csv_files_parsed,
            "non_json_skipped": self.non_json_skipped,
            "total_raw_records": self.total_raw_records,
            "total_imported": self.total_imported,
            "drops_by_reason": dict(self.drops_by_reason),
            "files": [
                {
                    "path": f.path,
                    "records_seen": f.records_seen,
                    "records_imported": f.records_imported,
                    "parse_error": f.parse_error,
                    "drops": [
                        {"reason": d.reason, "detail": d.detail[:200]}
                        for d in f.drops[:50]
                    ],
                }
                for f in self.files
            ],
        }
