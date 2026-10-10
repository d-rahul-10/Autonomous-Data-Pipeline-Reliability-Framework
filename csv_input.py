"""CSV reading helpers for pipeline datasets."""
import csv
import io
from pathlib import Path

import pandas as pd


_DELIMITERS = (",", ";", "\t", "|")
_SAMPLE_SIZE = 128 * 1024


def _read_sample(source):
    stream = getattr(source, "stream", source)
    if hasattr(stream, "read") and hasattr(stream, "seek"):
        position = stream.tell()
        stream.seek(0)
        try:
            return stream.read(_SAMPLE_SIZE)
        finally:
            stream.seek(position)

    with Path(source).open("rb") as file:
        return file.read(_SAMPLE_SIZE)


def _find_table_header(source):
    try:
        text = _read_sample(source).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None

    candidates = []
    for delimiter in _DELIMITERS:
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            rows = []
            previous_line = 0
            for row in reader:
                start_line = previous_line
                previous_line = reader.line_num
                if row and any(value.strip() for value in row):
                    rows.append((start_line, len(row)))
        except csv.Error:
            continue

        for index, (start_line, width) in enumerate(rows):
            if start_line == 0 or width < 8:
                continue
            following_rows = rows[index + 1:]
            matching_rows = sum(row_width == width for _, row_width in following_rows)
            if matching_rows:
                candidates.append((width, matching_rows, -start_line, start_line, delimiter))

    if not candidates:
        return None
    _, _, _, start_line, delimiter = max(candidates)
    return start_line, delimiter


def read_csv_table(source, *, low_memory=False):
    """Read a CSV, retrying only when a consistent table follows metadata rows."""
    try:
        return pd.read_csv(source, low_memory=low_memory)
    except pd.errors.ParserError as original_error:
        header = _find_table_header(source)
        if header is None:
            raise

        skiprows, delimiter = header
        stream = getattr(source, "stream", source)
        if hasattr(stream, "seek"):
            stream.seek(0)
        try:
            return pd.read_csv(
                source,
                skiprows=skiprows,
                sep=delimiter,
                low_memory=low_memory,
            )
        except pd.errors.ParserError:
            raise original_error
