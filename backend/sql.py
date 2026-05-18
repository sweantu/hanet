HYBRID_SEARCH_SQL = """
    WITH semantic AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY d.embedding <=> $1::vector) AS rank
        FROM documents d
        WHERE d.embedding IS NOT NULL
          AND d.collection = 'message'
        ORDER BY d.embedding <=> $1::vector
        LIMIT 50
    ),
    keyword AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY ts_rank(d.fts, query) DESC) AS rank
        FROM documents d, plainto_tsquery('english', $2) query
        WHERE d.fts @@ query
          AND d.collection = 'message'
        ORDER BY rank
        LIMIT 50
    ),
    fused AS (
        SELECT
            COALESCE(s.id, k.id) AS id,
            COALESCE(1.0 / (60 + s.rank), 0.0) +
            COALESCE(1.0 / (60 + k.rank), 0.0) AS rrf_score
        FROM semantic s
        FULL OUTER JOIN keyword k USING (id)
    )
    SELECT
        f.id,
        d.content,
        d.metadata,
        c.title AS conversation_title,
        c.created_at AS conversation_created_at,
        f.rrf_score
    FROM fused f
    JOIN documents d ON d.id = f.id
    JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
    ORDER BY f.rrf_score DESC
    LIMIT $3
"""

HYBRID_SEARCH_ASSISTANT_SQL = """
    WITH semantic AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY d.embedding <=> $1::vector) AS rank
        FROM documents d
        WHERE d.embedding IS NOT NULL
          AND d.collection = 'message'
          AND d.metadata->>'role' = 'assistant'
        ORDER BY d.embedding <=> $1::vector
        LIMIT 50
    ),
    keyword AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY ts_rank(d.fts, query) DESC) AS rank
        FROM documents d, plainto_tsquery('english', $2) query
        WHERE d.fts @@ query
          AND d.collection = 'message'
          AND d.metadata->>'role' = 'assistant'
        ORDER BY rank
        LIMIT 50
    ),
    fused AS (
        SELECT
            COALESCE(s.id, k.id) AS id,
            COALESCE(1.0 / (60 + s.rank), 0.0) +
            COALESCE(1.0 / (60 + k.rank), 0.0) AS rrf_score
        FROM semantic s
        FULL OUTER JOIN keyword k USING (id)
    )
    SELECT
        f.id,
        d.content,
        d.metadata,
        c.title AS conversation_title,
        c.created_at AS conversation_created_at,
        f.rrf_score
    FROM fused f
    JOIN documents d ON d.id = f.id
    JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
    ORDER BY f.rrf_score DESC
    LIMIT $3
"""
