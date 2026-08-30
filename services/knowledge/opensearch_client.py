import logging
import os

from opensearchpy import AsyncOpenSearch

logger = logging.getLogger("opensearch_client")

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME = "knowledge_hybrid"


def get_opensearch_client() -> AsyncOpenSearch:
    """Returns an active AsyncOpenSearch client."""
    return AsyncOpenSearch(
        hosts=[OPENSEARCH_URL],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
    )


async def init_opensearch_index():
    """Initializes the k-NN vector and text hybrid index in OpenSearch if not present."""
    client = get_opensearch_client()
    try:
        # Check if the index already exists
        exists = await client.indices.exists(index=INDEX_NAME)
        if exists:
            logger.info(f"OpenSearch index '{INDEX_NAME}' already exists.")
            return

        # Setup index settings with k-NN vector plugins enabled
        index_body = {
            "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 100}},
            "mappings": {
                "properties": {
                    "content": {"type": "text", "analyzer": "standard"},
                    "document_name": {"type": "keyword"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 1536,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                            "parameters": {"ef_construction": 128, "m": 24},
                        },
                    },
                }
            },
        }

        await client.indices.create(index=INDEX_NAME, body=index_body)
        logger.info(f"OpenSearch index '{INDEX_NAME}' created successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize OpenSearch index: {e}")
    finally:
        await client.close()
