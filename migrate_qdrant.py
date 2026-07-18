"""Разовая миграция embedded Qdrant (./qdrant_db) → сервис qdrant.

Запуск (воркеры должны быть остановлены — embedded держит файловый лок):
    docker compose stop worker
    docker compose run --rm worker python migrate_qdrant.py
    docker compose up -d

Переносит все коллекции с векторами и payload. Уже существующие коллекции
на сервере пересоздаются.
"""

import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from build_equation_index import QDRANT_PATH

BATCH = 128


def main():
    url = os.environ.get('QDRANT_URL')
    if not url:
        sys.exit('QDRANT_URL не задан — мигрировать некуда')

    src = QdrantClient(path=QDRANT_PATH)
    dst = QdrantClient(url=url)

    for coll in src.get_collections().collections:
        name = coll.name
        info = src.get_collection(name)
        params = info.config.params.vectors
        total = src.count(name).count
        print(f'{name}: {total} точек, размерность {params.size}')

        if dst.collection_exists(name):
            dst.delete_collection(name)
        dst.create_collection(name, vectors_config=VectorParams(
            size=params.size, distance=params.distance))

        offset = None
        moved = 0
        while True:
            points, offset = src.scroll(name, limit=BATCH, offset=offset,
                                        with_vectors=True, with_payload=True)
            if not points:
                break
            dst.upsert(name, [
                PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                for p in points])
            moved += len(points)
            if offset is None:
                break
        print(f'  перенесено: {moved}')

    print('Готово.')


if __name__ == '__main__':
    main()
