"""BI 에이전트가 쓰는 로컬 도구 모음.

- list_data_files : data/ 폴더의 분석 가능한 파일 목록
- preview_data    : 파일 구조(시트·컬럼·타입·상위 행) 미리보기
- run_python      : pandas 분석 코드 실행 (실행 전 사용자 승인)
- save_output     : 요청서·보고서 초안을 outputs/ 에 저장

모든 파일 접근은 data/, outputs/ 안으로 제한한다.
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"

DATA_SUFFIXES = {".csv", ".xlsx", ".xls", ".parquet", ".tsv"}
MAX_RESULT_CHARS = 20_000  # 도구 결과가 컨텍스트를 너무 많이 차지하지 않도록 자른다
PYTHON_TIMEOUT_SEC = 120


def _safe_path(root: Path, rel: str) -> Path:
    """root 밖으로 나가는 경로(../ 등)를 막는다."""
    path = (root / rel).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise ValueError(f"{root.name}/ 폴더 밖의 경로는 쓸 수 없습니다: {rel}")
    return path


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n... (출력 {len(text):,}자 중 앞부분만 표시)"


# ---------------------------------------------------------------------------
# 도구 구현
# ---------------------------------------------------------------------------

def list_data_files() -> str:
    files = [
        p for p in sorted(DATA_DIR.rglob("*"))
        if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
    ]
    if not files:
        return "data/ 폴더에 분석 가능한 파일(csv, xlsx, xls, parquet, tsv)이 없습니다."
    lines = [
        f"- {p.relative_to(DATA_DIR)} ({p.stat().st_size / 1024:,.0f} KB)" for p in files
    ]
    return "data/ 폴더 파일 목록:\n" + "\n".join(lines)


def preview_data(path: str, sheet: str | None = None, n_rows: int = 10) -> str:
    file = _safe_path(DATA_DIR, path)
    if not file.exists():
        return f"파일이 없습니다: {path}"
    suffix = file.suffix.lower()
    n_rows = max(1, min(int(n_rows), 50))

    out = []
    if suffix in (".xlsx", ".xls"):
        sheets = pd.ExcelFile(file).sheet_names
        out.append(f"시트 목록: {sheets}")
        target = sheet or sheets[0]
        df = pd.read_excel(file, sheet_name=target)
        out.append(f"[미리보기 시트: {target}]")
    elif suffix == ".parquet":
        df = pd.read_parquet(file)
    else:
        sep = "\t" if suffix == ".tsv" else ","
        df = pd.read_csv(file, sep=sep)

    out.append(f"행 {len(df):,} × 열 {df.shape[1]}")
    out.append("컬럼 / 타입 / 결측 수:")
    for col in df.columns:
        out.append(f"  - {col} | {df[col].dtype} | 결측 {df[col].isna().sum():,}")
    out.append(f"\n상위 {n_rows}행:")
    out.append(df.head(n_rows).to_string())
    return _truncate("\n".join(out))


def run_python(code: str, purpose: str) -> str:
    """분석 코드를 별도 프로세스에서 실행한다. 작업 폴더는 bi_agent/ 이다."""
    print("\n" + "=" * 70)
    print(f"[run_python] 목적: {purpose}")
    print("-" * 70)
    print(code)
    print("=" * 70)
    answer = input("이 코드를 실행할까요? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        return "사용자가 코드 실행을 거절했습니다. 코드를 수정하거나 다른 방법을 제안하세요."

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=PYTHON_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return f"실행 시간 초과({PYTHON_TIMEOUT_SEC}초). 데이터를 줄이거나 로직을 나눠 보세요."

    result = f"[exit code {proc.returncode}]\n"
    if proc.stdout:
        result += f"[stdout]\n{proc.stdout}\n"
    if proc.stderr:
        result += f"[stderr]\n{proc.stderr}\n"
    return _truncate(result)


def save_output(filename: str, content: str) -> str:
    file = _safe_path(OUTPUT_DIR, filename)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return f"저장 완료: outputs/{file.relative_to(OUTPUT_DIR)}"


# ---------------------------------------------------------------------------
# Claude에 넘기는 도구 정의 (JSON Schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_data_files",
        "description": "data/ 폴더에 있는 분석 가능한 데이터 파일(csv, xlsx, parquet 등) 목록을 보여준다. "
                       "데이터 분석 요청을 받으면 가장 먼저 호출해 어떤 데이터가 있는지 확인한다.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "eager_input_streaming": True,
    },
    {
        "name": "preview_data",
        "description": "data/ 폴더의 파일 하나를 열어 시트 목록, 행·열 수, 컬럼별 타입·결측 수, 상위 행을 보여준다. "
                       "분석 코드를 쓰기 전에 실제 컬럼명과 데이터 형태를 확인하는 용도.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "data/ 기준 상대 경로. 예: ubist_2026.xlsx"},
                "sheet": {"type": "string", "description": "엑셀 시트명. 생략하면 첫 시트."},
                "n_rows": {"type": "integer", "description": "보여줄 상위 행 수 (1~50, 기본 10)"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "run_python",
        "description": "pandas 등으로 분석하는 Python 코드를 실행하고 stdout/stderr를 돌려받는다. "
                       "작업 폴더는 bi_agent/ 이므로 데이터는 'data/파일명', 결과 파일은 'outputs/파일명'으로 접근한다. "
                       "결과는 print()로 출력해야 보인다. 오너가 읽을 수 있도록 로직마다 한국어 주석을 단다. "
                       "실행 전 사용자가 코드를 검토·승인한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "실행할 Python 코드 (한국어 주석 포함)"},
                "purpose": {"type": "string", "description": "이 코드가 무엇을 확인·계산하는지 한 문장"},
            },
            "required": ["code", "purpose"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "save_output",
        "description": "BI 분석 요청서, 보고서 초안, 분석 요약 등 텍스트 산출물을 outputs/ 폴더에 저장한다. "
                       "마크다운(.md) 형식을 권장한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "outputs/ 기준 파일명. 예: 요청서_A품목_점유율하락.md"},
                "content": {"type": "string", "description": "저장할 내용"},
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]

_HANDLERS = {
    "list_data_files": list_data_files,
    "preview_data": preview_data,
    "run_python": run_python,
    "save_output": save_output,
}


def _validate(name: str, args: dict) -> str | None:
    """스트리밍으로 받은 입력은 서버가 검증하지 않으므로 여기서 스키마를 확인한다."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), None)
    if schema is None:
        return f"알 수 없는 도구: {name}"
    if not isinstance(args, dict):
        return "도구 입력이 JSON 객체가 아닙니다."
    props = schema["properties"]
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"필수 입력 누락: {missing}"
    unknown = [k for k in args if k not in props]
    if unknown:
        return f"정의되지 않은 입력: {unknown}"
    type_map = {"string": str, "integer": int}
    for key, value in args.items():
        expected = type_map[props[key]["type"]]
        if not isinstance(value, expected) or isinstance(value, bool):
            return f"'{key}'의 타입이 {props[key]['type']}가 아닙니다."
    return None


def execute_tool(name: str, args: dict) -> tuple[str, bool]:
    """(결과 문자열, 오류 여부)를 돌려준다."""
    error = _validate(name, args)
    if error:
        return error, True
    try:
        return _HANDLERS[name](**args), False
    except Exception as exc:  # 도구 오류는 Claude에게 돌려줘서 스스로 고치게 한다
        return f"{type(exc).__name__}: {exc}", True


if __name__ == "__main__":
    print(json.dumps([t["name"] for t in TOOLS], ensure_ascii=False))
