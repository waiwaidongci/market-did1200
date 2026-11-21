from src.utils.time import iso


def gate_dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename,
            'row_count': item.row_count, 'checksum': item.checksum,
            'author': item.author, 'created_at': iso(item.created_at)}


def ledger_dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename,
            'row_count': item.row_count, 'version': item.version,
            'checksum': item.checksum, 'author': item.author,
            'created_at': iso(item.created_at)}


def bound_run(item, detail=False):
    view = {
        'id': item.id, 'name': item.name, 'status': item.status,
        'gate_dataset_id': item.gate_dataset_id, 'ledger_dataset_id': item.ledger_dataset_id,
        'ledger_version': item.ledger_version, 'stale': item.stale,
        'stale_reason': item.stale_reason, 'superseded_by': item.superseded_by,
        'replaces_run_id': item.replaces_run_id, 'author': item.author,
        'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
        'has_export': bool(item.export_file), 'error': item.error,
    }
    if detail:
        view.update(params=item.params, result=item.result)
    return view
