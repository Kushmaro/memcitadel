Brief: MemPalace-to-Elasticsearch (Serverless) Connector
1. Project Objective
Build a bridge between the MemPalace logical framework (Wings/Rooms/Halls) and Elasticsearch Serverless. We are replacing the default local ChromaDB backend with a high-performance, scalable ES index that preserves the "Memory Palace" hierarchical structure.

2. Architectural Pivot
While the original project is "local-first" for privacy, this version is Cloud-Hybrid:

Logic Layer: MemPalace (local agent or MCP server) handles the spatial navigation (e.g., "Moving to the API Wing").

Data Layer: Elasticsearch Serverless handles the heavy lifting—semantic search, BM25, and metadata-filtered retrieval.

3. Implementation Details for Claude Code
A. The Schema (Optimized for ES)
Since the user is an Elastic expert, don't just use a basic index. Use a schema that supports Hybrid Search:

content_raw: The original verbatim text (for BM25 and human-readability).

content_aaak: The AAAK-compressed version (to be returned to the LLM to maximize context window).

embedding: Vector field (use dense_vector with HNSW).

Spatial Metadata: wing_id, room_id, hall_type, and timestamp.

B. Logical Filter Translation
The connector must translate MemPalace's "Spatial" commands into Elasticsearch DSL.

Example: A request to "Search in the Billing Room for Late Fees" should generate a bool query where room_id: "billing" is a filter (not a score-influencer) to ensure strict logical isolation.

C. The AAAK Factor
Storage: Index both raw and AAAK.

Querying: Encode the user's query into AAAK before performing semantic search to ensure vector alignment (as AAAK uses specific entity codes/regex shorthand).

Inference: Leverage the Elasticsearch Inference API if possible to handle embeddings server-side.

4. Key Refinements
Skip Local-First Constraints: We are prioritizing Elasticsearch Serverless from Day 1.

Performance: Focus on Recall@K within a specific "Room." The goal is 100% recall because the search space is narrowed logically.

MCP Server: Implement the connector as an MCP (Model Context Protocol) server so Claude/other LLMs can "walk" the palace via tool calls.
