"""Export complete Audio and Camera subsets using the RF experiment flags."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / 'data/processed'
    source = directory / 'dataset_v1.parquet'
    files = [source] if source.exists() else sorted((directory / 'dataset_v1_parts').glob('*.parquet'))
    if not files:
        raise SystemExit('No dataset_v1 parquet files found')
    schema = pq.ParquetFile(files[0]).schema_arrow
    schema = pa.schema([pa.field(f.name, f.type.value_type if pa.types.is_dictionary(f.type) else f.type)
                        for f in schema])
    stats = {name: {'rows': 0, 'benign': 0, 'ddos': 0} for name in ('audio', 'camera')}
    writers = {}
    overlap = 0
    try:
        for name in stats:
            writers[name] = csv.CSVWriter(str(directory / f'dataset_v1_{name}.csv'), schema)
        for path in files:
            for batch in pq.ParquetFile(path).iter_batches(batch_size=100_000):
                table = pa.Table.from_batches([batch]).cast(schema)
                overlap += pc.sum(pc.cast(pc.and_(table['has_audio'], table['has_camera']), pa.int64())).as_py() or 0
                for name, writer in writers.items():
                    subset = table.filter(table[f'has_{name}'])
                    writer.write_table(subset)
                    benign = pc.sum(pc.cast(pc.equal(subset['binary_label'], 0), pa.int64())).as_py() or 0
                    stats[name]['rows'] += len(subset)
                    stats[name]['benign'] += benign
                    stats[name]['ddos'] += len(subset) - benign
            print(f'Finished {path.name}: {stats}', flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    # Parse the saved CSVs to verify row counts and subset flags.
    for name in stats:
        output = directory / f'dataset_v1_{name}.csv'
        rows = 0
        for batch in csv.open_csv(output, convert_options=csv.ConvertOptions(
                include_columns=[f'has_{name}'], column_types={f'has_{name}': pa.bool_()})):
            assert pc.all(batch.column(0)).as_py(), f'Invalid {name} flag'
            rows += len(batch)
        assert rows == stats[name]['rows'], f'Row count mismatch for {name}'
        stats[name]['bytes'] = output.stat().st_size
        print(f'Verified {output.name}: {stats[name]}', flush=True)
    (directory / 'dataset_v1_device_csv_summary.json').write_text(json.dumps(
        {'sources': [str(p.relative_to(ROOT)) for p in files], 'subsets': stats,
         'overlap_rows': overlap, 'columns': schema.names}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
