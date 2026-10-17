import csv
from pathlib import Path

REQUIRED_TABLES = {
    "studentInfo.csv",
    "studentAssessment.csv",
    "studentVle.csv",
    "assessments.csv",
    "courses.csv",
    "vle.csv",
    "studentRegistration.csv",
}


class OuladDatasetAdapter:
    version = "oulad-2017-official-v1"

    def validate_directory(self, directory: Path) -> None:
        missing = REQUIRED_TABLES - {path.name for path in directory.glob("*.csv")}
        if missing:
            raise ValueError(f"OULAD directory is missing: {', '.join(sorted(missing))}")
        with (directory / "studentInfo.csv").open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle))
        required = {"code_module", "code_presentation", "id_student", "final_result"}
        if not required.issubset(header):
            raise ValueError("studentInfo.csv does not match the expected official schema")
