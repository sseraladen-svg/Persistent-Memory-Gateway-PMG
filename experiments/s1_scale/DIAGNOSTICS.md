# S1 diagnostics (100,000 chunks, descriptive only)
- queries containing a very common word: 300, median 31.6 ms
- stage `retrieve.search` (the FTS5 BM25 query) median 18.7 ms of `retrieve.total` median 29.7 ms
