-- Incremental migration for private retrieval diagnostics. Prefer Alembic in deployment.
CREATE TABLE knowledge_retrieval_traces (
  id BIGINT NOT NULL AUTO_INCREMENT,
  public_id VARCHAR(40) NOT NULL UNIQUE,
  task_public_id VARCHAR(40) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  knowledge_base_id VARCHAR(40), document_public_id VARCHAR(40), version_public_id VARCHAR(40),
  status VARCHAR(16) NOT NULL, query_text TEXT,
  retrieval_json JSON NOT NULL, agent_events_json JSON NOT NULL, selected_source_ids_json JSON NOT NULL,
  validation_json JSON NOT NULL, timings_json JSON NOT NULL,
  error_code VARCHAR(64), error_message VARCHAR(200),
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id), FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_knowledge_trace_created ON knowledge_retrieval_traces (created_at);
CREATE INDEX ix_knowledge_trace_document ON knowledge_retrieval_traces (document_public_id, created_at);

CREATE TABLE knowledge_bad_cases (
  id BIGINT NOT NULL AUTO_INCREMENT,
  public_id VARCHAR(40) NOT NULL UNIQUE, trace_id BIGINT NOT NULL,
  case_type VARCHAR(64) NOT NULL, severity VARCHAR(16) NOT NULL, status VARCHAR(16) NOT NULL,
  details_json JSON NOT NULL, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id), FOREIGN KEY (trace_id) REFERENCES knowledge_retrieval_traces(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_knowledge_bad_case_status ON knowledge_bad_cases (status, created_at);
CREATE INDEX ix_knowledge_bad_case_type ON knowledge_bad_cases (case_type, created_at);
