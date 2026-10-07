'''
Reads a CSV downloaded from the results of the presenter survey Google Form and fills papers.csv
The latest submission per paper wins entirely.
'''

import csv
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

INPUT_PATH = '~/ismir2026/presenter_survey.csv'  # Use your own path
TIMESTAMP_FORMAT = '%d/%m/%Y %H:%M:%S'

OUTPUT_PATH = '../../sitedata/papers.csv'


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def parse_required_text(value: str) -> str:
    if not value:
        raise ValueError('Unexpected empty value')
    return value


def parse_mode(value: str) -> bool:
    match value.lower():
        case 'in-person':
            return True
        case 'remote':
            return False
        case _:
            raise ValueError(f'Unexpected mode of presentation: {value}')


def parse_paper_id(value: str) -> int:
    return int(value.lstrip('#'))

def format_mode(value: bool) -> str:
    return 'In-person' if value else 'Virtual'


@dataclass(frozen=True)
class PresenterInfo:
    timestamp: datetime = field(metadata={'header': 'Timestamp', 'parse': parse_timestamp}) # no timezone info; non-critical
    paper_id: int = field(metadata={'header': 'Paper ID', 'parse': parse_paper_id})
    presenter_name: str = field(metadata={'header': 'Name of the Presenter', 'output': 'oral_session_presenter'})
    do_present_onsite: bool = field(metadata={'header': 'Mode of Presentation', 'output': 'paper_presentation', 'parse': parse_mode, 'format': format_mode})


def parse_presenters(path: str | Path = INPUT_PATH) -> dict[int, PresenterInfo]:
    """Fail fast on unexpected exports; a later submission for the same paper overwrites an earlier one."""
    info_fields = fields(PresenterInfo)
    field_names = {item.name for item in info_fields}
    header_map = {item.metadata['header']: item.name for item in info_fields}
    parsers = {item.name: item.metadata.get('parse', parse_required_text) for item in info_fields}

    papers: dict[int, PresenterInfo] = {}
    with Path(path).expanduser().open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers:
            raise ValueError('Missing CSV header')
        columns: list[str | None] = []
        for header_cell in headers:
            matches = [name for header, name in header_map.items() if header in header_cell]
            if len(matches) == 0:
                print(f'Info: discarding column "{header_cell[:40]}".')
                columns.append(None)
                continue
            if len(matches) >= 2:
                raise ValueError(f'Expected one header match for {header_cell!r}, got {matches}')
            if matches[0] in columns:
                raise ValueError(f'Duplicate column for {matches[0]!r}')
            columns.append(matches[0])
        if missing := field_names - set(columns):
            raise ValueError(f'Missing columns: {sorted(missing)}')

        for row in reader:
            if len(row) != len(columns):
                raise ValueError(f'CSV line {reader.line_num}: expected {len(columns)} cells, got {len(row)}')
            try:
                values = {name: parsers[name](cell.strip())
                          for name, cell in zip(columns, row) if name is not None}
            except (ValueError, TypeError) as exc:
                raise ValueError(f'CSV line {reader.line_num}: invalid value') from exc
            current = PresenterInfo(**values)
            if current.paper_id <= 0:
                raise ValueError(f'CSV line {reader.line_num}: nonpositive paper ID {current.paper_id}')

            previous = papers.get(current.paper_id)
            if previous is not None:
                if current.timestamp == previous.timestamp:
                    raise ValueError(f'Paper {current.paper_id}: repeated timestamp {current.timestamp}')
                print(f'Info: paper {current.paper_id} submitted more than once; keeping the latest.')
                current = max(current, previous, key=lambda entry: entry.timestamp)
            papers[current.paper_id] = current

    if not papers:
        raise ValueError('CSV contains no submissions')
    return papers


def write_into_sitedata(papers: dict[int, PresenterInfo]) -> None:
    output_path = (Path(__file__).resolve().parent / OUTPUT_PATH).resolve()
    output_fields = [item for item in fields(PresenterInfo) if 'output' in item.metadata]
    output_map = {item.name: item.metadata['output'] for item in output_fields}
    formatters = {item.name: item.metadata.get('format', str) for item in output_fields}
    with output_path.open(newline='', encoding='utf-8') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers or len(headers) != len(set(headers)):
            raise ValueError('Missing or duplicate output CSV headers')
        if missing := {'uid', *output_map.values()} - set(headers):
            raise ValueError(f'Missing output columns: {sorted(missing)}')
        uid_index = headers.index('uid')
        output_columns = {name: headers.index(column) for name, column in output_map.items()}
        rows: list[list[str]] = []
        seen: set[int] = set()
        for row in reader:
            if len(row) != len(headers):
                raise ValueError(f'Output CSV line {reader.line_num}: expected {len(headers)} cells, got {len(row)}')
            paper_id = int(row[uid_index])
            if paper_id <= 0 or paper_id in seen:
                raise ValueError(f'Invalid or duplicate output paper ID: {paper_id}')
            seen.add(paper_id)
            if paper_id in papers:
                info = papers[paper_id]
                if info.paper_id != paper_id:
                    raise ValueError(f'Paper ID does not match dictionary key: {paper_id}')
                for name, index in output_columns.items():
                    row[index] = formatters[name](getattr(info, name))
            rows.append(row)
    if unknown := papers.keys() - seen:
        raise ValueError(f'Submitted paper IDs missing from output CSV: {sorted(unknown)}')

    with output_path.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f'Presenter info updated in {output_path}.')
    print(f'Please paste the updated {", ".join(output_map.values())} columns back into the Google Sheet '
          'papers tab before running pull_from_google_sheet.py.')


if __name__ == '__main__':
    write_into_sitedata(parse_presenters())
